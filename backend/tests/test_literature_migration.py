import asyncio
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.migrate_legacy_literature import migrate, preflight
from src.api.literature import LiteratureStore, router
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal
from tests.test_literature import pdf_bytes


def legacy(tmp_path):
    source = tmp_path / "old"
    source.mkdir()
    raw = pdf_bytes("legacy paper")
    (source / "old.pdf").write_bytes(raw)
    catalog = source / "catalog.json"
    catalog.write_text(json.dumps([{"file": "old.pdf", "ref_id": 1, "title": "Old paper",
                                   "year": "2021", "tags": ["machine-tag"],
                                   "pdf_meta_author": "Administrator", "sha256": hashlib.sha256(raw).hexdigest()}]))
    return source, catalog, raw


def test_migration_global_visibility_original_and_resume(tmp_path):
    source, catalog, raw = legacy(tmp_path)
    database, files = tmp_path / "new.sqlite3", tmp_path / "files"
    prepared = preflight(catalog, source)
    first = asyncio.run(migrate(prepared, source, database, files, tmp_path / "first.json"))
    assert first["created"] == 1 and first["failed"] == 0
    app = FastAPI()
    db = app.state.literature = LiteratureStore(str(database), str(files))
    app.include_router(router, prefix="/api")
    try:
        with TestClient(app) as client:
            for role in ("tester", "reviewer", "developer"):
                app.dependency_overrides[current_user] = lambda role=role: Principal(tester_id=f"other-{role}", role=role)
                page = client.get("/api/literature/papers").json()
                assert page["total"] == 1
                paper = page["items"][0]
                assert paper["registration"] == "draft" and paper["usage"] == "normal"
                assert paper["tag_ids"] == [] and paper["authors"] == []
                assert paper["year"] == 2021 and paper["title"] == "Old paper"
            pid = paper["id"]
            detail = client.get(f"/api/literature/papers/{pid}").json()
            assert detail["events"][0]["actor"] == "legacy-migration"
            assert client.get(f"/api/literature/papers/{pid}/file").content == raw
            dim = client.post("/api/literature/dimensions", json={"name": "人工分类"}).json()["id"]
            tag = client.post(f"/api/literature/dimensions/{dim}/tags", json={"name": "后续标注"}).json()["id"]
            assert client.put(f"/api/literature/papers/{pid}", json={**paper, "title": "Reviewed title", "tag_ids": [tag]}).status_code == 200
            second = asyncio.run(migrate(prepared, source, database, files, tmp_path / "second.json"))
            assert second["created"] == 0 and second["existing"] == 1 and second["failed"] == 0
            saved = client.get(f"/api/literature/papers/{pid}").json()
            assert saved["title"] == "Reviewed title" and saved["tag_ids"] == [tag]
            assert len(saved["events"]) == 2
            assert client.get("/api/literature/papers").json()["total"] == 1
        assert (source / "old.pdf").read_bytes() == raw
    finally:
        db.close()


def test_preflight_rejects_changed_or_uncatalogued_pdf_before_import(tmp_path):
    source, catalog, _ = legacy(tmp_path)
    (source / "extra.pdf").write_bytes(pdf_bytes("extra"))
    with pytest.raises(ValueError, match="file lists differ"):
        preflight(catalog, source)
    (source / "extra.pdf").unlink()
    (source / "old.pdf").write_bytes(pdf_bytes("changed"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        preflight(catalog, source)
