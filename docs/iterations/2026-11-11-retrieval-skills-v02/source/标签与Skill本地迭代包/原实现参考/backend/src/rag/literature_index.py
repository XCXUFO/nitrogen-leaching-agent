"""Versioned bridge between the managed PDFs and existing RAG components."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from src.agent.understanding import assess_conditions, terms
from src.agent.composition import supports_crop
from src.rag.chunker import chunk_text
from src.rag.ingest import load_text
from src.rag.retriever import RetrievalResult


class LiteratureIndex:
    def __init__(self, library):
        self.library = library
        self._legacy_hashes = {}
        self._legacy_chunk_maps = {}
        with library.lock, library.db:
            library.db.executescript("""
                CREATE TABLE IF NOT EXISTS literature_search_sync (
                    paper_id TEXT PRIMARY KEY, content_key TEXT NOT NULL, job_id TEXT NOT NULL,
                    status TEXT NOT NULL, indexed_at TEXT, error TEXT, mode TEXT, chunks_json TEXT);
            """)
            library.db.execute("UPDATE literature_search_sync SET status='failed',error='服务重启导致同步中断，请手动重试。' WHERE status='processing'")

    @staticmethod
    def content_key(paper):
        return hashlib.sha256(json.dumps({key: paper.get(key) for key in (
            "sha256", "title", "authors", "year", "source_note", "source_url", "tag_ids", "registration", "usage")},
            ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def status(self, paper):
        if paper["usage"] != "normal": return {"status": "excluded", "reason": "文献已停用，不参与新检索"}
        with self.library.lock:
            row = self.library.db.execute("SELECT * FROM literature_search_sync WHERE paper_id=?", (paper["id"],)).fetchone()
        if not row: return {"status": "not_prepared", "reason": "尚未同步全文索引"}
        if row["content_key"] != self.content_key(paper): return {"status": "stale", "reason": "当前内容或检索元数据已变更，旧索引暂停使用", "indexed_at": row["indexed_at"]}
        return {"status": row["status"], "version": row["content_key"], "indexed_at": row["indexed_at"],
                "reason": row["error"] or "", "mode": row["mode"], "job_id": row["job_id"]}

    @staticmethod
    def _inherited(paper, row):
        # A metadata-review draft created by the legacy migration must not
        # silently unpublish a PDF that was already in the searchable library.
        return bool(row and paper.get("created_by") == "legacy-migration"
                    and row["mode"] in {"legacy_text", "legacy_vector_and_text"})

    def adopt_legacy_index(self, store):
        """Attach verified pre-existing chunks to migration records, once.

        Do not register drafts, infer bibliographic fields, or recompute vectors.
        An existing sync row (including failed/stale rows) is never overwritten.
        """
        from src.rag.documents import PAPERS_DIR
        grouped = {}
        for hit in store.iter_chunks():
            if hit["metadata"].get("paper_id"):
                continue
            filename = str(hit["metadata"].get("source", "")).replace("\\", "/").rsplit("/", 1)[-1]
            grouped.setdefault(filename, []).append(hit)
        result = {"adopted": 0, "chunks": 0, "skipped": []}
        for filename, hits in grouped.items():
            file_hash = self.legacy_hash(filename)
            if not file_hash:
                continue
            with self.library.lock:
                row = self.library.db.execute("SELECT p.* FROM papers p LEFT JOIN literature_search_sync s ON s.paper_id=p.id "
                    "WHERE p.sha256=? AND p.created_by='legacy-migration' AND p.deleted=0 AND p.usage='normal' AND s.paper_id IS NULL", (file_hash,)).fetchone()
                if row is None:
                    continue
                paper = self.library.paper(row)
            try:
                original = load_text(PAPERS_DIR / filename)
                chunks = []
                for hit in sorted(hits, key=lambda item: item["chunk_id"]):
                    start, end = hit["metadata"].get("char_start"), hit["metadata"].get("char_end")
                    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(original)
                            or original[start:end] != hit["document"]):
                        raise ValueError("legacy_chunk_mismatch")
                    chunks.append({"text": hit["document"], "char_start": start, "char_end": end,
                                   "file_sha256": file_hash, "legacy_chunk_id": hit["chunk_id"]})
                if not chunks:
                    continue
            except (OSError, ValueError):
                result["skipped"].append({"paper_id": paper["id"], "reason": "历史片段与原件无法核对，未接入。"})
                continue
            key = self.content_key(paper)
            with self.library.write():
                latest = self.library.get_paper(paper["id"])
                if latest["usage"] != "normal" or self.content_key(latest) != key:
                    continue
                cursor = self.library.db.execute("INSERT OR IGNORE INTO literature_search_sync VALUES (?,?,?,'ready',?,NULL,'legacy_vector_and_text',?)",
                    (paper["id"], key, str(uuid4()), datetime.now(timezone.utc).isoformat(), json.dumps(chunks, ensure_ascii=False)))
                if cursor.rowcount:
                    self.library.event("paper", paper["id"], "search_sync", "legacy-index-reconciliation",
                        after={"version": key, "status": "ready", "mode": "legacy_vector_and_text", "chunks": len(chunks)},
                        reason="核对已有向量片段、原件指纹和正文位置，恢复历史检索关联；登记状态未改变。")
                    result["adopted"] += 1
                    result["chunks"] += len(chunks)
        return result

    def prepare_pending(self, *, actor="automatic-fulltext-sync"):
        """Index saved PDFs independently of bibliographic registration.

        Reuse existing text for metadata changes. Failed extraction stays
        visible for explicit retry; it is not replayed on every worker pass.
        """
        with self.library.lock:
            papers = [self.library.paper(row) for row in self.library.db.execute(
                "SELECT * FROM papers WHERE deleted=0 AND usage='normal'").fetchall()]
        result = {"ready": 0, "failed": 0}
        for paper in papers:
            if self.status(paper)["status"] not in {"not_prepared", "stale"}:
                continue
            try:
                status = self.sync(paper["id"], actor=actor)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            if status["status"] in result:
                result[status["status"]] += 1
        return result

    def sync(self, paper_id, *, actor, retriever=None, loader=load_text):
        db = self.library
        with db.write():
            paper = db.get_paper(paper_id)
            current = db.db.execute("SELECT * FROM literature_search_sync WHERE paper_id=?", (paper_id,)).fetchone()
            previous_chunks = json.loads(current["chunks_json"]) if current and current["chunks_json"] else []
            inherited = self._inherited(paper, current) and bool(previous_chunks) and all(item.get("file_sha256") == paper["sha256"] for item in previous_chunks)
            if paper["usage"] != "normal":
                return self.status(paper)
            key = self.content_key(paper)
            if current and current["content_key"] == key and current["status"] in {"ready", "processing"}: return self.status(paper)
            job_id = str(uuid4())
            db.db.execute("INSERT INTO literature_search_sync VALUES (?,?,?,'processing',NULL,NULL,NULL,?) ON CONFLICT(paper_id) DO UPDATE SET content_key=excluded.content_key,job_id=excluded.job_id,status='processing',error=NULL",
                          (paper_id, key, job_id, json.dumps(previous_chunks, ensure_ascii=False)))
        mode, error, chunks = "legacy_text" if inherited else "text", None, []
        try:
            # Metadata-only updates reuse immutable original text, never an AI abstract.
            if previous_chunks and all(item.get("file_sha256") == paper["sha256"] for item in previous_chunks):
                chunks = previous_chunks
            else:
                path = db.root / f"blob-{paper['sha256']}.pdf"
                if not path.is_file(): path = db.root / f"{paper_id}.pdf"
                if not path.is_file(): raise FileNotFoundError()
                if hashlib.sha256(path.read_bytes()).hexdigest() != paper["sha256"]: raise ValueError("file_fingerprint_mismatch")
                text = loader(path)
                if not text.strip(): raise ValueError("no_readable_text")
                chunks = [{"text": chunk.text, "char_start": chunk.metadata["char_start"], "char_end": chunk.metadata["char_end"], "file_sha256": paper["sha256"]}
                          for chunk in chunk_text(text, paper_id, f"managed://{paper_id}/{paper['filename']}")]
                if not chunks: raise ValueError("no_readable_text")
            if retriever is not None:
                vectors = retriever._embedder.embed_documents([item["text"] for item in chunks])
                retriever._store.upsert(ids=[f"{paper_id}:{key}:{index}" for index in range(len(chunks))],
                    documents=[item["text"] for item in chunks], embeddings=vectors,
                    metadatas=[{"paper_id": paper_id, "content_key": key, "file_sha256": paper["sha256"], "source": f"managed://{paper_id}/{paper['filename']}",
                                "char_start": item["char_start"], "char_end": item["char_end"]} for item in chunks])
                mode = "legacy_vector_and_text" if inherited else "vector_and_text"
        except Exception as exc:
            error = {"no_readable_text": "PDF 没有可读正文，未标记全文就绪；当前不提供 OCR。", "file_fingerprint_mismatch": "原件指纹不一致，请核对文件。"}.get(str(exc),
                      "正文提取或索引同步失败，请核对原件及本地检索依赖后重试。")
        with db.write():
            latest = db.get_paper(paper_id)
            # Superseded jobs cannot declare newer content ready.
            row = db.db.execute("SELECT job_id FROM literature_search_sync WHERE paper_id=?", (paper_id,)).fetchone()
            if not row or row["job_id"] != job_id or self.content_key(latest) != key: return self.status(latest)
            db.db.execute("UPDATE literature_search_sync SET status=?,indexed_at=?,error=?,mode=?,chunks_json=? WHERE paper_id=? AND job_id=?",
                          ("failed" if error else "ready", datetime.now(timezone.utc).isoformat(), error, mode, json.dumps(chunks or previous_chunks, ensure_ascii=False), paper_id, job_id))
            db.event("paper", paper_id, "search_sync", actor, after={"version": key, "status": "failed" if error else "ready", "mode": mode}, reason=error or "")
            return self.status(latest)

    def eligible_hit(self, hit):
        paper_id = hit.metadata.get("paper_id")
        with self.library.lock:
            if not paper_id:
                filename = str(hit.metadata.get("source", "")).replace("\\", "/").rsplit("/", 1)[-1]
                file_hash = hit.metadata.get("file_sha256") or self.legacy_hash(filename)
                row = self.library.db.execute("SELECT * FROM papers WHERE sha256=?", (file_hash,)).fetchone() if file_hash else None
                if row is None:
                    return self.library.db.execute("SELECT 1 FROM papers WHERE filename=? AND created_by='legacy-migration'", (filename,)).fetchone() is None
                if row["deleted"] or row["usage"] != "normal" or self.legacy_hash(filename) != file_hash: return False
                paper = self.library.paper(row)
                sync = self.library.db.execute("SELECT * FROM literature_search_sync WHERE paper_id=?", (paper["id"],)).fetchone()
                return self._inherited(paper, sync) and self.status(paper)["status"] == "ready"
            row = self.library.db.execute("SELECT * FROM papers WHERE id=? AND deleted=0", (paper_id,)).fetchone()
            if not row: return False
            paper = self.library.paper(row)
            status = self.status(paper)
            return status["status"] == "ready" and hit.metadata.get("content_key") == status["version"]

    def bind_hit(self, hit):
        """Use the current managed identity for an adopted legacy vector hit."""
        if hit.metadata.get("paper_id") or not self.eligible_hit(hit): return hit
        filename = str(hit.metadata.get("source", "")).replace("\\", "/").rsplit("/", 1)[-1]
        file_hash = self.legacy_hash(filename)
        with self.library.lock:
            row = self.library.db.execute("SELECT * FROM papers WHERE sha256=? AND deleted=0", (file_hash,)).fetchone()
            if row is None: return hit
            paper = self.library.paper(row)
            sync = self.library.db.execute("SELECT * FROM literature_search_sync WHERE paper_id=?", (paper["id"],)).fetchone()
            if not self._inherited(paper, sync): return hit
            key = sync["content_key"]
            if key not in self._legacy_chunk_maps:
                self._legacy_chunk_maps[key] = {item.get("legacy_chunk_id"): index for index, item in enumerate(json.loads(sync["chunks_json"] or "[]")) if item.get("legacy_chunk_id")}
            index = self._legacy_chunk_maps[key].get(hit.chunk_id)
            if index is None: return hit
            return RetrievalResult(f"{paper['id']}:{key}:{index}", hit.document, hit.score, {
                **hit.metadata, "paper_id": paper["id"], "content_key": key, "file_sha256": file_hash,
                "title": paper["title"], "source": f"managed://{paper['id']}/{paper['filename']}"})

    def assess_hit(self, hit, *, understanding=None, mapping=None, crop=None):
        """Verify current access and content using the same scope as text search.

        Vector hits intentionally carry only immutable index metadata. Resolve
        their current paper here rather than treating missing tag IDs or a crop
        mentioned only in the title as a failed condition.
        """
        with self.library.lock:
            if not self.eligible_hit(hit):
                return [], False
            title, tag_ids = str(hit.metadata.get("title") or ""), []
            paper_id = hit.metadata.get("paper_id")
            if paper_id:
                paper = self.library.get_paper(paper_id)
                title, tag_ids = paper["title"], paper["tag_ids"]
            scoped_text = title + "\n" + hit.document
            checks, eligible = assess_conditions(scoped_text, tag_ids, understanding or {}, mapping or {})
            return checks, eligible and supports_crop(crop, scoped_text, str(hit.metadata.get("source", "")))

    def legacy_hash(self, filename):
        from src.rag.documents import PAPERS_DIR
        if Path(filename).name != filename: return None
        path = (PAPERS_DIR / filename).resolve()
        if path.parent != PAPERS_DIR.resolve() or not path.is_file(): return None
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key not in self._legacy_hashes:
            self._legacy_hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        return self._legacy_hashes[key]

    def legacy_file_allowed(self, filename):
        file_hash = self.legacy_hash(filename)
        if not file_hash: return True
        with self.library.lock:
            rows = self.library.db.execute("SELECT * FROM papers WHERE sha256=?", (file_hash,)).fetchall()
            if not rows:
                return self.library.db.execute("SELECT 1 FROM papers WHERE filename=? AND created_by='legacy-migration'", (filename,)).fetchone() is None
            return any(not row["deleted"] and row["usage"] == "normal" and
                (row["registration"] == "registered" or self.status(self.library.paper(row))["status"] == "ready") for row in rows)

    def search(self, query, *, understanding=None, mapping=None, limit=20):
        candidates, results = [], []
        query_terms = terms(query)
        with self.library.lock:
            rows = self.library.db.execute("SELECT p.*,s.content_key,s.chunks_json FROM papers p JOIN literature_search_sync s ON s.paper_id=p.id WHERE p.deleted=0 AND p.usage='normal' AND s.status='ready'").fetchall()
            for row in rows:
                paper = self.library.paper(row)
                if self.status(paper)["status"] != "ready" or self.content_key(paper) != row["content_key"]: continue
                for index, chunk in enumerate(json.loads(row["chunks_json"] or "[]")):
                    checks, eligible = assess_conditions(paper["title"] + "\n" + chunk["text"], paper["tag_ids"], understanding or {}, mapping or {})
                    score = len(query_terms & terms(chunk["text"] + paper["title"]))
                    cid = f"{paper['id']}:{row['content_key']}:{index}"
                    candidates.append({"chunk_id": cid, "paper_id": paper["id"], "version": row["content_key"], "checks": checks,
                                       "selected": eligible and score > 0, "reason": "eligible" if eligible else "condition_unconfirmed", "score": score})
                    if eligible and score > 0:
                        results.append(RetrievalResult(chunk_id=cid, document=chunk["text"], score=float(score), metadata={
                            "paper_id": paper["id"], "content_key": row["content_key"], "file_sha256": paper["sha256"], "title": paper["title"],
                            "source": f"managed://{paper['id']}/{paper['filename']}", "char_start": chunk["char_start"], "char_end": chunk["char_end"]}))
        results.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        return results[:limit], candidates

    def citation_metadata(self, source):
        """Resolve bibliography from the same current record as the workbench."""
        if source.startswith("session://"):
            return None
        with self.library.lock:
            if source.startswith("managed://"):
                paper_id = source.split("/", 3)[2]
                row = self.library.db.execute("SELECT * FROM papers WHERE id=? AND deleted=0", (paper_id,)).fetchone()
            else:
                filename = source.replace("\\", "/").rsplit("/", 1)[-1]
                file_hash = self.legacy_hash(filename)
                row = self.library.db.execute("SELECT * FROM papers WHERE sha256=? AND deleted=0", (file_hash,)).fetchone() if file_hash else None
            if row is None:
                return None
            paper = self.library.paper(row)
            authors = [author["name"].strip() if isinstance(author, dict) else author.strip() for author in paper["authors"]]
            return {"title": paper["title"] or None,
                    "author_hint": "、".join(author for author in authors if author) or None,
                    "year": str(paper["year"]) if paper["year"] is not None else None,
                    "document_id": paper["id"], "document_available": bool(self.public_file(paper["id"]))}

    def public_file(self, paper_id):
        paper = self.library.get_paper(paper_id)
        if paper["usage"] != "normal" or (paper["registration"] != "registered" and self.status(paper)["status"] != "ready"): return None
        path = self.library.root / f"blob-{paper['sha256']}.pdf"
        if not path.is_file(): path = self.library.root / f"{paper_id}.pdf"
        return (paper, path) if path.is_file() else None
