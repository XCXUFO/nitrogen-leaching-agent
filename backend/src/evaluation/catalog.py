"""Append-only asset provenance and revisioned Case drafts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from src.evaluation.contracts import AssetInput, AssetPairInput, CaseDraftBatchInput, CaseDraftInput, CaseDraftRevision, Principal
from src.evaluation.store import EvaluationStore, fail, now

ROOT = Path(__file__).resolve().parents[3]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CaseCatalog:
    def __init__(self, evaluations: EvaluationStore):
        self.evaluations = evaluations
        self.db, self.lock = evaluations.db, evaluations.lock
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS eval_assets (
                  asset_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_asset_pairs (
                  pair_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_case_drafts (
                  draft_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                  status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_case_draft_history (
                  draft_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(draft_id, revision));
            """)

    @staticmethod
    def asset_path(relative: str) -> Path:
        path = (ROOT / relative).resolve()
        if not (path.is_relative_to(ROOT / "data") or path.is_relative_to(ROOT / "docs")):
            raise fail("asset_path_forbidden", "资产必须位于项目 data/ 或 docs/ 下。", 422)
        if not path.is_file():
            raise fail("asset_not_found", "找不到该资产文件。", 422)
        return path

    def register_asset(self, body: AssetInput, user: Principal) -> dict:
        path = self.asset_path(body.path)
        if body.kind == "result_fixture" and path.suffix.lower() not in {".xls", ".xlsx"}:
            raise fail("fixture_format", "结果表资产须为 .xls 或 .xlsx。", 422)
        if body.kind == "result_fixture" and path.stat().st_size > 10 * 1024 * 1024:
            raise fail("fixture_size", "结果表资产超过单附件 10 MiB 上限，不能用于用例执行。", 422)
        record = {**body.model_dump(), "path": str(path.relative_to(ROOT)),
                  "asset_id": str(uuid4()), "filename": path.name, "sha256": hash_file(path),
                  "size_bytes": path.stat().st_size, "created_at": now(), "created_by": user.tester_id}
        with self.lock, self.db:
            self.db.execute("INSERT INTO eval_assets VALUES (?,?)", (record["asset_id"], json.dumps(record, ensure_ascii=False)))
        return record

    def upload_asset(self, raw: bytes, filename: str, body: AssetInput, user: Principal) -> dict:
        if (not raw or not filename or filename in {".", ".."} or "/" in filename or "\\" in filename
                or any(ord(char) < 32 or ord(char) == 127 for char in filename)
                or Path(filename).suffix.lower() not in {".xls", ".xlsx", ".csv", ".json", ".txt", ".md", ".pdf", ".docx", ".zip"}):
            raise fail("asset_upload_invalid", "请上传有内容的受支持资料文件；文件名不能包含路径。", 422)
        if len(raw) > 40 * 1024 * 1024:
            raise fail("asset_upload_too_large", "资产超过 40 MiB。", 413)
        directory = ROOT / "data/eval/uploads" / str(uuid4())
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / filename
        try:
            with path.open("xb") as stream:
                stream.write(raw)
            path.chmod(0o600)
            registered = AssetInput(**{**body.model_dump(), "path": str(path.relative_to(ROOT))})
            return self.register_asset(registered, user)
        except Exception:
            path.unlink(missing_ok=True)
            directory.rmdir()
            raise

    def assets(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT payload FROM eval_assets ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def asset(self, asset_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT payload FROM eval_assets WHERE asset_id=?", (asset_id,)).fetchone()
        if not row:
            raise fail("asset_not_found", "未找到该资产记录。", 404)
        return json.loads(row[0])

    def register_pair(self, body: AssetPairInput, user: Principal) -> dict:
        source, output = self.asset(body.input_asset_id), self.asset(body.output_asset_id)
        if source["kind"] != "model_input" or output["kind"] not in {"model_output", "result_fixture"}:
            raise fail("asset_pair_kind", "配对需要模型输入和模型输出或结果表。", 422)
        if body.status == "verified":
            if user.role != "reviewer" or not body.evidence_asset_id or not body.supersedes_pair_id or not body.notes.strip():
                raise fail("pair_verification_required", "核实配对需要专家审核身份、证据资产和候选配对。", 403)
            evidence = self.asset(body.evidence_asset_id)
            prior = self.pair(body.supersedes_pair_id)
            if (evidence["kind"] != "evidence" or prior["status"] != "candidate" or
                    (prior["input_asset_id"], prior["output_asset_id"]) != (body.input_asset_id, body.output_asset_id)):
                raise fail("pair_evidence_mismatch", "证据或原候选配对不匹配。", 422)
            for asset in (source, output, evidence):
                if hash_file(self.asset_path(asset["path"])) != asset["sha256"]:
                    raise fail("pair_asset_changed", "输入、输出或证据原件已变化，请重新登记资产并核对配对。", 422)
        elif user.role != "developer":
            raise fail("developer_required", "候选配对需开发者登记。", 403)
        record = {**body.model_dump(), "pair_id": str(uuid4()), "created_at": now(),
                  "created_by": user.tester_id, "reviewer_role": user.role,
                  "input_sha256": source["sha256"], "output_sha256": output["sha256"],
                  "evidence_sha256": self.asset(body.evidence_asset_id)["sha256"] if body.evidence_asset_id else None}
        with self.lock, self.db:
            self.db.execute("INSERT INTO eval_asset_pairs VALUES (?,?)", (record["pair_id"], json.dumps(record, ensure_ascii=False)))
        return record

    def pairs(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT payload FROM eval_asset_pairs ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def pair(self, pair_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT payload FROM eval_asset_pairs WHERE pair_id=?", (pair_id,)).fetchone()
        if not row:
            raise fail("pair_not_found", "未找到该配对记录。", 404)
        return json.loads(row[0])

    def _fixtures(self, body: CaseDraftInput) -> list[dict]:
        if len(set(body.fixture_asset_ids)) != len(body.fixture_asset_ids):
            raise fail("draft_duplicate_fixture", "同一附件资产不能重复关联。", 422)
        assets = [self.asset(asset_id) for asset_id in body.fixture_asset_ids]
        if any(asset["kind"] != "result_fixture" for asset in assets):
            raise fail("draft_fixture_kind", "用例附件必须登记为结果表资产。", 422)
        if sorted(asset["filename"] for asset in assets) != sorted(body.case.attachment_requirements):
            raise fail("draft_fixture_mismatch", "附件名称与用例要求不一致。", 422)
        return [{"asset_id": asset["asset_id"], "filename": asset["filename"],
                 "sha256": asset["sha256"], "path": asset["path"]} for asset in assets]

    def create_draft(self, body: CaseDraftInput, user: Principal) -> dict:
        fixtures = self._fixtures(body)
        record = {**body.model_dump(mode="json"), "fixtures": fixtures, "draft_id": str(uuid4()),
                  "revision": 1, "status": "draft", "created_at": now(), "created_by": user.tester_id,
                  "updated_at": now(), "updated_by": user.tester_id}
        with self.lock, self.db:
            self.db.execute("INSERT INTO eval_case_drafts VALUES (?,?,?,?)",
                            (record["draft_id"], 1, "draft", json.dumps(record, ensure_ascii=False)))
            self.db.execute("INSERT INTO eval_case_draft_history VALUES (?,?,?)",
                            (record["draft_id"], 1, json.dumps(record, ensure_ascii=False)))
        return record

    def import_drafts(self, body: CaseDraftBatchInput, user: Principal) -> list[dict]:
        # Validate the entire batch before the first INSERT; database transaction
        # keeps all draft/history rows together if any write fails.
        records = []
        for item in body.drafts:
            record = {**item.model_dump(mode="json"), "fixtures": self._fixtures(item),
                      "draft_id": str(uuid4()), "revision": 1, "status": "draft",
                      "created_at": now(), "created_by": user.tester_id,
                      "updated_at": now(), "updated_by": user.tester_id}
            records.append(record)
        with self.lock, self.db:
            for record in records:
                raw = json.dumps(record, ensure_ascii=False)
                self.db.execute("INSERT INTO eval_case_drafts VALUES (?,?,?,?)",
                                (record["draft_id"], 1, "draft", raw))
                self.db.execute("INSERT INTO eval_case_draft_history VALUES (?,?,?)",
                                (record["draft_id"], 1, raw))
        return records

    def drafts(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT payload FROM eval_case_drafts ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def draft(self, draft_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT payload FROM eval_case_drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if not row:
            raise fail("draft_not_found", "未找到该用例草稿。", 404)
        return json.loads(row[0])

    def draft_history(self, draft_id: str) -> list[dict]:
        self.draft(draft_id)
        with self.lock:
            rows = self.db.execute("SELECT payload FROM eval_case_draft_history WHERE draft_id=? ORDER BY revision", (draft_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update_draft(self, draft_id: str, body: CaseDraftRevision, user: Principal) -> dict:
        fixtures = self._fixtures(body)
        with self.lock, self.db:
            row = self.db.execute("SELECT revision,status,payload FROM eval_case_drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if not row:
                raise fail("draft_not_found", "未找到该用例草稿。", 404)
            old = json.loads(row[2])
            if row[1] != "draft" or row[0] != body.expected_revision:
                raise fail("draft_revision_conflict", "草稿已发布或版本发生变化，请刷新后重试。")
            if old["case"]["case_id"] != body.case.case_id:
                raise fail("draft_identity_change", "草稿不可改变用例 ID，请新建草稿。", 422)
            record = {**old, **body.model_dump(mode="json", exclude={"expected_revision"}),
                      "fixtures": fixtures, "revision": row[0] + 1, "updated_at": now(),
                      "updated_by": user.tester_id}
            self.db.execute("UPDATE eval_case_drafts SET revision=?,payload=? WHERE draft_id=?",
                            (record["revision"], json.dumps(record, ensure_ascii=False), draft_id))
            self.db.execute("INSERT INTO eval_case_draft_history VALUES (?,?,?)",
                            (draft_id, record["revision"], json.dumps(record, ensure_ascii=False)))
        return record

    def publish(self, draft_id: str, user: Principal, expected_revision: int) -> dict:
        with self.lock, self.db:
            row = self.db.execute("SELECT revision,status,payload FROM eval_case_drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if not row:
                raise fail("draft_not_found", "未找到该用例草稿。", 404)
            if row[1] != "draft":
                raise fail("draft_already_published", "草稿已发布；历史版本不可覆盖。")
            if row[0] != expected_revision:
                raise fail("draft_revision_conflict", "草稿已有新修订，请重新打开并核对内容后发布。")
            draft = json.loads(row[2]); case = draft["case"]
            latest = self.db.execute("SELECT MAX(version) FROM eval_cases WHERE case_id=?", (case["case_id"],)).fetchone()[0] or 0
            if case["version"] <= latest:
                raise fail("case_version_conflict", "发布版本必须高于已有最高版本。", 422)
            for fixture in draft["fixtures"]:
                path = self.asset_path(fixture["path"])
                if hash_file(path) != fixture["sha256"]:
                    raise fail("fixture_changed", "附件原件指纹已变化，不能发布。", 422)
            payload = {"case": case, "dataset_id": f"catalog-{draft_id}",
                       "professional_review": "pending", "fixtures": draft["fixtures"],
                       "draft_id": draft_id, "draft_revision": row[0],
                       "published_at": now(), "published_by": user.tester_id}
            self.db.execute("INSERT INTO eval_cases VALUES (?,?,?)",
                            (case["case_id"], case["version"], json.dumps(payload, ensure_ascii=False, sort_keys=True)))
            draft.update(status="published", revision=row[0] + 1, published_at=payload["published_at"],
                         published_by=user.tester_id, updated_at=now(), updated_by=user.tester_id)
            self.db.execute("UPDATE eval_case_drafts SET revision=?,status=?,payload=? WHERE draft_id=?",
                            (draft["revision"], "published", json.dumps(draft, ensure_ascii=False), draft_id))
            self.db.execute("INSERT INTO eval_case_draft_history VALUES (?,?,?)",
                            (draft_id, draft["revision"], json.dumps(draft, ensure_ascii=False)))
        return payload
