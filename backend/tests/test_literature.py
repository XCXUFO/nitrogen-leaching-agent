"""Core registration rules without a network-bound test server."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import fitz
import pytest
from fastapi import HTTPException

from src.api.literature import (
    DimensionInput, LiteratureStore, PaperInput, PaperUpdateInput, ReasonInput, TagInput,
    create_dimension, create_paper, create_tag, delete_paper, disable_paper,
    duplicates, get_paper, list_papers, restore_paper, update_paper, update_tag, upload,
)
from src.evaluation.contracts import Principal


class FakeRequest:
    def __init__(self, db: LiteratureStore, raw: bytes = b""):
        self.app = SimpleNamespace(state=SimpleNamespace(literature=db))
        self.raw = raw
        self.headers = {}

    async def stream(self):
        yield self.raw


@pytest.fixture
def context(tmp_path):
    db = LiteratureStore(str(tmp_path / "papers.db"), str(tmp_path / "files"))
    yield db, Principal(tester_id="editor", role="tester")
    db.close()


def pdf_bytes(text="test"):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def upload_pdf(db, user, filename="paper.pdf", raw=None):
    return asyncio.run(upload(FakeRequest(db, raw or pdf_bytes()), filename, user))["upload_id"]


def test_lifecycle_duplicate_and_delete(context):
    db, user = context
    original = pdf_bytes()
    token = upload_pdf(db, user, raw=original)
    draft = create_paper(FakeRequest(db), PaperInput(upload_id=token), user)
    paper_id = draft["id"]
    assert draft["registration"] == "draft" and draft["title"] == "paper"
    with pytest.raises(HTTPException) as duplicate:
        upload_pdf(db, user, "copy.pdf", raw=original)
    assert duplicate.value.status_code == 409
    with pytest.raises(HTTPException) as incomplete:
        update_paper(FakeRequest(db), paper_id, PaperUpdateInput(expected_revision=draft["revision"], title="A", action="register"), user)
    assert incomplete.value.detail["code"] == "authors_required"
    registered = update_paper(FakeRequest(db), paper_id, PaperUpdateInput(expected_revision=draft["revision"], title="A", authors=["Li"], publication_type="期刊论文", venue="Journal", year=2024, language="英文", source_note="Archive", action="register"), user)
    assert registered["registration"] == "registered"
    with pytest.raises(HTTPException):
        update_paper(FakeRequest(db), paper_id, PaperUpdateInput(expected_revision=registered["revision"], action="draft"), user)
    disable_paper(FakeRequest(db), paper_id, ReasonInput(reason="Old"), user)
    assert db.get_paper(paper_id)["usage"] == "disabled"
    restore_paper(FakeRequest(db), paper_id, user)
    assert db.get_paper(paper_id)["usage"] == "normal"
    delete_paper(FakeRequest(db), paper_id, ReasonInput(reason="Mistake"), user)
    with pytest.raises(HTTPException):
        get_paper(FakeRequest(db), paper_id, user)
    assert upload_pdf(db, user, "again.pdf", raw=original)
    assert len(db.events("paper", paper_id)) >= 5
    assert all(event["summary"] for event in db.events("paper", paper_id))


def test_required_tag_and_ancestor_constraint(context):
    db, user = context
    dimension = create_dimension(FakeRequest(db), DimensionInput(name="主题", required=True), user)["id"]
    parent = create_tag(FakeRequest(db), dimension, TagInput(name="农业"), user)["id"]
    child = create_tag(FakeRequest(db), dimension, TagInput(name="氮素", parent_id=parent), user)["id"]
    token = upload_pdf(db, user, "tagged.pdf")
    base = dict(upload_id=token, title="Tagged", authors=["Zhang"], publication_type="预印本", venue="Repository", year_unknown=True, language="中文", source_url="https://example.org/paper", action="register")
    with pytest.raises(HTTPException) as missing:
        create_paper(FakeRequest(db), PaperInput(**base), user)
    assert missing.value.detail["code"] == "required_tag"
    with pytest.raises(HTTPException) as conflict:
        create_paper(FakeRequest(db), PaperInput(**base, tag_ids=[parent, child]), user)
    assert conflict.value.detail["code"] == "ancestor_conflict"
    paper = create_paper(FakeRequest(db), PaperInput(**base, tag_ids=[child]), user)
    assert paper["registration"] == "registered"
    assert child in db.descendants(parent, db.taxonomy()["tags"])
    assert db.db.execute("SELECT COUNT(*) FROM paper_tags WHERE paper_id=?", (paper["id"],)).fetchone()[0] == 1
    assert list_papers(FakeRequest(db), tags=parent, page=1, page_size=20, user=user)["total"] == 1
    assert list_papers(FakeRequest(db), year_unknown=True, page=1, page_size=20, user=user)["total"] == 1
    sibling = create_tag(FakeRequest(db), dimension, TagInput(name="施肥"), user)["id"]
    update_paper(FakeRequest(db), paper["id"], PaperUpdateInput(expected_revision=paper["revision"], **(base | {"upload_id": None, "tag_ids": [child, sibling]})), user)
    with pytest.raises(HTTPException) as move:
        update_tag(FakeRequest(db), sibling, TagInput(name="施肥", parent_id=child), user)
    assert move.value.detail["code"] == "tag_move_conflict"


def test_doi_duplicate_requires_version_link(context):
    db, user = context
    first = dict(title="Version one", authors=[{"name": "Lab", "kind": "institution"}], publication_type="预印本", venue="Repository", year=2024, language="英文", source_note="Archive", doi="https://doi.org/10.1234/example", action="register")
    original = create_paper(FakeRequest(db), PaperInput(**first, upload_id=upload_pdf(db, user)), user)
    assert original["doi"] == "10.1234/example"
    second_upload = upload_pdf(db, user, "version2.pdf", raw=pdf_bytes("second"))
    with pytest.raises(HTTPException) as conflict:
        create_paper(FakeRequest(db), PaperInput(**first, upload_id=second_upload), user)
    assert conflict.value.detail["code"] == "doi_confirmation_required"
    second = create_paper(FakeRequest(db), PaperInput(**(first | {"title": "Version two", "version_note": "Second edition", "related_paper_ids": [original["id"]], "confirm_same_doi": True}), upload_id=second_upload), user)
    assert second["id"] != original["id"]
    assert duplicates(FakeRequest(db), "10.1234/example", user)["papers"]


def test_upload_rejects_non_pdf_and_prunes_uncommitted_file(context):
    db, user = context
    with pytest.raises(HTTPException) as invalid:
        asyncio.run(upload(FakeRequest(db, b"not a pdf"), "bad.pdf", user))
    assert invalid.value.detail["code"] == "invalid_pdf"
    token = upload_pdf(db, user)
    path = db.root / f"upload-{token}"
    assert path.is_file()
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with db.db:
        db.db.execute("UPDATE uploads SET created_at=? WHERE id=?", (old, token))
    db.prune_uploads()
    assert not path.exists()
    assert db.db.execute("SELECT 1 FROM uploads WHERE id=?", (token,)).fetchone() is None
