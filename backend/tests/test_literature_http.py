import fitz
import pytest
from fastapi.testclient import TestClient

from tests.literature_fixture import TOKENS, create_app
from tests.test_literature import pdf_bytes


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKENS['tester']}"
        yield client
    app.state.literature.close()


def upload(client, text="paper"):
    raw = pdf_bytes(text)
    result = client.post("/api/literature/uploads", params={"filename": f"{text}.pdf"}, content=raw)
    assert result.status_code == 200, result.text
    return result.json()["upload_id"], raw


def create(client, text="paper", **fields):
    token, raw = upload(client, text)
    result = client.post("/api/literature/papers", json={"upload_id": token, "title": text, **fields})
    assert result.status_code == 200, result.text
    return result.json(), raw


def complete(paper, **fields):
    return {**paper, "authors_unknown": True, "publication_type": "期刊论文", "venue_unknown": True,
            "year_unknown": True, "language": "英文", "source_note": "Synthetic fixture", "action": "register", **fields}


def test_http_auth_lifecycle_and_original(client):
    assert client.get("/api/literature/papers", headers={"Authorization": ""}).status_code == 401
    for role, token in TOKENS.items():
        assert client.get("/api/literature/users", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    paper, raw = create(client)
    pid = paper["id"]
    duplicate = client.post("/api/literature/uploads?filename=renamed.pdf", content=raw)
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["paper_id"] == pid
    saved = client.put(f"/api/literature/papers/{pid}", json=complete(paper))
    assert saved.status_code == 200, saved.text
    assert saved.json()["registered_by"] == "tester"
    download = client.get(f"/api/literature/papers/{pid}/file?download=true")
    assert download.content == raw and download.headers["content-disposition"].startswith("attachment;")
    assert client.post(f"/api/literature/papers/{pid}/disable", json={"reason": " "}).status_code == 400
    assert client.post(f"/api/literature/papers/{pid}/disable", json={"reason": "archive"}).status_code == 200
    page = client.get("/api/literature/papers").json()
    assert page["total"] == 0 and page["counts"] == {"total": 1, "draft": 0, "registered": 1, "disabled": 1}
    assert client.post(f"/api/literature/papers/{pid}/restore").json()["registration"] == "registered"
    assert client.post(f"/api/literature/papers/{pid}/delete", json={"reason": "test finished"}).status_code == 200
    assert client.get(f"/api/literature/papers/{pid}/file").status_code == 404
    assert client.post("/api/literature/uploads?filename=again.pdf", content=raw).status_code == 200


def test_edit_doi_cannot_bypass_confirmation(client):
    first, _ = create(client, "first", doi="10.1234/ONE")
    second, _ = create(client, "second")
    body = {**second, "doi": "https://doi.org/10.1234/one", "action": "draft"}
    blocked = client.put(f"/api/literature/papers/{second['id']}", json=body)
    assert blocked.status_code == 409
    accepted = client.put(f"/api/literature/papers/{second['id']}", json={**body, "version_note": "v2", "confirm_same_doi": True, "related_paper_ids": [first["id"]]})
    assert accepted.status_code == 200, accepted.text
    subsequent = client.put(f"/api/literature/papers/{second['id']}", json={**accepted.json(), "action": "draft", "internal_note": "corrected"})
    assert subsequent.status_code == 200, subsequent.text


def test_deleted_relation_remains_editable(client):
    first, _ = create(client, "first")
    second, _ = create(client, "second", related_paper_ids=[first["id"]])
    client.post(f"/api/literature/papers/{first['id']}/delete", json={"reason": "mistake"})
    response = client.put(f"/api/literature/papers/{second['id']}", json={**second, "title": "corrected", "action": "draft"})
    assert response.status_code == 200, response.text
    assert response.json()["related_papers"][0]["deleted"] is True
    token, _ = upload(client, "third")
    assert client.post("/api/literature/papers", json={"upload_id": token, "related_paper_ids": [first["id"]]}).status_code == 404


def test_pdf_rejection_and_upload_ownership(client):
    assert client.post("/api/literature/uploads?filename=x.pdf", content=b"invalid").status_code == 400
    document = fitz.open(stream=pdf_bytes(), filetype="pdf")
    protected = document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="password", owner_pw="owner")
    document.close()
    assert client.post("/api/literature/uploads?filename=locked.pdf", content=protected).json()["detail"]["code"] == "protected_pdf"
    token, _ = upload(client)
    wrong_owner = client.post("/api/literature/papers", headers={"Authorization": f"Bearer {TOKENS['reviewer']}"}, json={"upload_id": token})
    assert wrong_owner.status_code == 404


def test_failed_file_replacement_preserves_committed_original(client, monkeypatch):
    paper, original = create(client)
    token, replacement = upload(client, "replacement")
    db = client.app.state.literature
    def fail_event(*args, **kwargs):
        raise RuntimeError("simulated write failure")
    monkeypatch.setattr(db, "event", fail_event)
    with pytest.raises(RuntimeError, match="simulated"):
        client.put(f"/api/literature/papers/{paper['id']}", json={**paper, "upload_id": token, "action": "draft"})
    assert client.get(f"/api/literature/papers/{paper['id']}/file").content == original
    assert (db.root / f"upload-{token}").read_bytes() == replacement


def test_size_limit_and_failed_upload_cleanup(client, monkeypatch):
    from src.api.literature import settings
    monkeypatch.setattr(settings, "literature_max_pdf_mb", 1)
    response = client.post("/api/literature/uploads?filename=large.pdf", content=b"%PDF-" + b"x" * 1024 * 1024)
    assert response.status_code == 413
    assert not list(client.app.state.literature.root.glob("upload-*"))


def test_cleanup_keeps_deleted_original_but_removes_orphan_blob(client):
    import os
    import time
    paper, original = create(client)
    root = client.app.state.literature.root
    path = root / f"blob-{paper['sha256']}.pdf"
    orphan = root / f"blob-{'0' * 64}.pdf"
    orphan.write_bytes(b"uncommitted copy")
    old = time.time() - 2 * 86400
    for entry in (path, orphan): os.utime(entry, (old, old))
    client.post(f"/api/literature/papers/{paper['id']}/delete", json={"reason": "archive"})
    client.app.state.literature.prune_uploads()
    assert path.read_bytes() == original
    assert not orphan.exists()


def test_filter_tag_boolean_logic_unknown_and_global_counts(client):
    dim = client.post("/api/literature/dimensions", json={"name": "主题"}).json()["id"]
    other = client.post("/api/literature/dimensions", json={"name": "对象"}).json()["id"]
    def tag(d, name, parent=None):
        return client.post(f"/api/literature/dimensions/{d}/tags", json={"name": name, "parent_id": parent}).json()["id"]
    a = tag(dim, "A")
    child = tag(dim, "child", a)
    b = tag(dim, "B")
    c = tag(other, "C")
    first, _ = create(client, "Alpha", tag_ids=[child, c], doi="10.1234/alpha", year=2025)
    second, _ = create(client, "Beta", tag_ids=[b, c], year_unknown=True)
    create(client, "Gamma", tag_ids=[a])
    def query(**params):
        response = client.get("/api/literature/papers", params=params)
        assert response.status_code == 200, response.text
        return response.json()
    assert query(tags=",".join([a, b, c]))["total"] == 2
    assert query(tags=a)["total"] == 2
    assert query(tags=",".join([a, c]))["items"][0]["id"] == first["id"]
    assert query(year_unknown=True)["total"] == 1  # Missing draft year is not explicitly unknown.
    assert query(keyword="https://doi.org/10.1234/ALPHA")["total"] == 1
    assert query(field="id", keyword=first["id"][:-1])["total"] == 0
    assert query(keyword=" alpha ")["total"] == 1
    client.post(f"/api/literature/papers/{second['id']}/disable", json={"reason": "archive"})
    result = query(tags=b)
    assert result["total"] == 0 and result["counts"]["total"] == 3
    assert query(tags=b, usage="all")["total"] == 1
    client.put(f"/api/literature/tags/{b}", json={"name": "B", "enabled": False})
    assert client.get("/api/literature/papers", params={"tags": b}).status_code == 400
    assert query(tags=b, include_disabled_tags=True, usage="all")["total"] == 1
    assert [p["year"] for p in query(sort="year", direction="asc")["items"]] == [2025, None]


def test_historical_tags_and_new_registration_requirements(client):
    dim = client.post("/api/literature/dimensions", json={"name": "主题"}).json()["id"]
    tag = client.post(f"/api/literature/dimensions/{dim}/tags", json={"name": "旧标签"}).json()["id"]
    paper, _ = create(client, tag_ids=[tag])
    saved = client.put(f"/api/literature/papers/{paper['id']}", json=complete(paper)).json()
    client.put(f"/api/literature/tags/{tag}", json={"name": "旧标签", "enabled": False})
    # Existing history may be retained, but new associations must be active.
    assert client.put(f"/api/literature/papers/{paper['id']}", json={**saved, "action": "register", "internal_note": "correction"}).status_code == 200
    saved = client.get(f"/api/literature/papers/{paper['id']}").json()
    token, _ = upload(client, "new")
    assert client.post("/api/literature/papers", json={"upload_id": token, "tag_ids": [tag]}).status_code == 400
    client.put(f"/api/literature/dimensions/{dim}", json={"name": "主题", "required": True})
    assert client.put(f"/api/literature/papers/{paper['id']}", json={**saved, "action": "register"}).status_code == 400
    client.post(f"/api/literature/papers/{paper['id']}/disable", json={"reason": "archive"})
    restored = client.post(f"/api/literature/papers/{paper['id']}/restore").json()
    assert restored["registration"] == "registered"
    assert client.get(f"/api/literature/papers/{paper['id']}").json()["warnings"]


def test_concurrent_same_file_save_returns_existing_record(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    apps = [create_app(tmp_path), create_app(tmp_path)]
    clients = [TestClient(app) for app in apps]
    raw = pdf_bytes("concurrent")
    uploads = []
    for client in clients:
        client.headers["Authorization"] = f"Bearer {TOKENS['tester']}"
        uploads.append(client.post("/api/literature/uploads?filename=one.pdf", content=raw).json()["upload_id"])
    barrier = Barrier(2)
    def save(index):
        barrier.wait()
        return clients[index].post("/api/literature/papers", json={"upload_id": uploads[index]})
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, [0, 1]))
        assert sorted(r.status_code for r in results) == [200, 409]
        created = next(r.json() for r in results if r.status_code == 200)
        rejected = next(r.json() for r in results if r.status_code == 409)
        assert rejected["detail"]["paper_id"] == created["id"]
    finally:
        for client in clients: client.close()
        for app in apps: app.state.literature.close()
