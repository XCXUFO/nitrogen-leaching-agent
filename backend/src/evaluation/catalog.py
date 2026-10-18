"""Revisioned Case drafts with existing evaluation fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from src.evaluation.contracts import CaseDraftBatchInput, CaseDraftInput, CaseDraftRevision, Principal
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
                CREATE TABLE IF NOT EXISTS eval_case_drafts (
                  draft_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                  status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_case_draft_history (
                  draft_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(draft_id, revision));
            """)

    @staticmethod
    def fixture_path(relative: str) -> Path:
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT):
            raise fail("fixture_path_forbidden", "评测附件必须位于项目目录下。", 422)
        if not path.is_file():
            raise fail("fixture_not_found", "找不到该评测附件。", 422)
        return path

    def _fixtures(self, body: CaseDraftInput, existing: list[dict] | None = None) -> list[dict]:
        names = body.case.attachment_requirements
        if len(set(names)) != len(names):
            raise fail("draft_duplicate_fixture", "同一评测附件不能重复关联。", 422)
        available = {**self.evaluations.fixtures,
                     **{item["filename"]: item for item in existing or []}}
        if any(name not in available for name in names):
            raise fail("draft_fixture_mismatch", "附件要求须使用已有评测样例的文件名。", 422)
        # Reuse frozen fixtures without registering or copying model output files.
        return [{key: available[name][key] for key in ("filename", "sha256", "path")}
                for name in names]

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
        with self.lock, self.db:
            row = self.db.execute("SELECT revision,status,payload FROM eval_case_drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if not row:
                raise fail("draft_not_found", "未找到该用例草稿。", 404)
            old = json.loads(row[2])
            if row[1] != "draft" or row[0] != body.expected_revision:
                raise fail("draft_revision_conflict", "草稿已发布或版本发生变化，请刷新后重试。")
            if old["case"]["case_id"] != body.case.case_id:
                raise fail("draft_identity_change", "草稿不可改变用例 ID，请新建草稿。", 422)
            fixtures = self._fixtures(body, old["fixtures"])
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
                path = self.fixture_path(fixture["path"])
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
