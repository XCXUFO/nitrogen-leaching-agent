"""Pre-existing indexed PDFs stay searchable after metadata-only migration."""
import asyncio
from types import SimpleNamespace

import pytest

from src.agent.chat_service import ChatService, RAGQueryError
from src.api.literature import LiteratureStore, PaperInput, PaperUpdateInput, ReasonInput, create_paper, update_paper, disable_paper, delete_paper
from src.evaluation.contracts import Principal
from src.rag.chunker import chunk_text
from src.rag.ingest import load_text
from src.rag.retriever import RetrievalResult
from tests.test_chat_service import FakeLLMClient, FakeRetriever
from tests.test_literature import FakeRequest, pdf_bytes, upload_pdf


MIGRATOR = Principal(tester_id="legacy-migration", role="developer")
EDITOR = Principal(tester_id="reviewer", role="reviewer")
TEXT = "Maize nitrogen leaching depends on water and nitrogen. Irrigation transports nitrate through soil."


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    import src.rag.documents as documents
    originals = tmp_path / "originals"
    originals.mkdir()
    monkeypatch.setattr(documents, "PAPERS_DIR", originals)
    raw = pdf_bytes(TEXT)
    original = originals / "old.pdf"
    original.write_bytes(raw)
    library = LiteratureStore(str(tmp_path / "library.sqlite3"), str(tmp_path / "files"))
    token = upload_pdf(library, MIGRATOR, raw=raw, filename="old.pdf")
    paper = create_paper(FakeRequest(library), PaperInput(upload_id=token, title="Maize water and nitrogen", action="draft"), MIGRATOR)
    chunks = chunk_text(load_text(original), "old", "../data/papers/old.pdf")
    records = [{"chunk_id": item.chunk_id, "document": item.text, "metadata": item.metadata} for item in chunks]
    store = SimpleNamespace(iter_chunks=lambda: iter(records))
    hits = [RetrievalResult(item["chunk_id"], item["document"], .9, item["metadata"]) for item in records]
    yield library, paper, store, hits, original
    library.close()


def test_verified_existing_index_is_adopted_without_registering_or_reembedding(migrated):
    library, paper, store, hits, _ = migrated
    index = library.search_index
    assert not index.eligible_hit(hits[0])

    result = index.adopt_legacy_index(store)

    assert result == {"adopted": 1, "chunks": len(hits), "skipped": []}
    current = library.get_paper(paper["id"])
    assert current["registration"] == "draft" and current["registered_at"] is None
    assert current["search_sync"]["status"] == "ready"
    assert current["search_sync"]["mode"] == "legacy_vector_and_text"
    assert index.eligible_hit(hits[0]) and index.legacy_file_allowed("old.pdf")
    assert index.public_file(paper["id"])
    bound = index.bind_hit(hits[0])
    assert bound.metadata["paper_id"] == paper["id"] and bound.metadata["file_sha256"] == paper["sha256"]
    managed, _ = index.search("nitrogen leaching")
    assert managed[0].chunk_id == bound.chunk_id and managed[0].document == hits[0].document
    assert index.adopt_legacy_index(store) == {"adopted": 0, "chunks": 0, "skipped": []}
    events = library.events("paper", paper["id"])
    assert len(events) == 2 and events[0]["actor"] == "legacy-index-reconciliation"


@pytest.mark.parametrize("action", ["disable", "delete"])
def test_disabling_or_deleting_also_revokes_legacy_vectors_and_originals(migrated, action):
    library, paper, store, hits, _ = migrated
    index = library.search_index
    index.adopt_legacy_index(store)
    operation = disable_paper if action == "disable" else delete_paper
    operation(FakeRequest(library), paper["id"], ReasonInput(reason="stop using source"), EDITOR)

    assert not index.eligible_hit(hits[0]) and not index.legacy_file_allowed("old.pdf")
    assert index.search("nitrogen")[0] == []
    assert index.adopt_legacy_index(store)["adopted"] == 0


def test_new_upload_drafts_are_not_adopted_by_matching_a_filename_or_content(migrated):
    library, paper, store, hits, _ = migrated
    library.db.execute("UPDATE papers SET created_by='regular-uploader' WHERE id=?", (paper["id"],))
    library.db.commit()

    assert library.search_index.adopt_legacy_index(store)["adopted"] == 0
    assert not library.search_index.eligible_hit(hits[0])
    assert not library.search_index.legacy_file_allowed("old.pdf")
    assert library.get_paper(paper["id"])["search_sync"]["status"] == "not_prepared"


@pytest.mark.parametrize("mismatch", ["text", "offset", "original"])
def test_adoption_requires_matching_original_fingerprint_and_exact_body_span(migrated, mismatch):
    library, paper, store, hits, original = migrated
    if mismatch == "original":
        original.write_bytes(pdf_bytes("different PDF"))
    else:
        records = list(store.iter_chunks())
        if mismatch == "text": records[0]["document"] = "invented body"
        else: records[0]["metadata"]["char_start"] = -1
        store = SimpleNamespace(iter_chunks=lambda: iter(records))

    assert library.search_index.adopt_legacy_index(store)["adopted"] == 0
    assert not library.search_index.eligible_hit(hits[0])
    assert library.get_paper(paper["id"])["search_sync"]["status"] == "not_prepared"


def test_metadata_changes_require_sync_and_are_not_overwritten_by_adoption(migrated):
    library, paper, store, hits, _ = migrated
    index = library.search_index
    index.adopt_legacy_index(store)
    current = library.get_paper(paper["id"])
    update_paper(FakeRequest(library), paper["id"], PaperUpdateInput.model_validate({
        **current, "expected_revision": current["revision"], "action": "draft", "title": "Corrected maize study",
    }), EDITOR)

    assert library.get_paper(paper["id"])["search_sync"]["status"] == "stale"
    assert not index.eligible_hit(hits[0]) and index.search("nitrogen")[0] == []
    assert index.adopt_legacy_index(store)["adopted"] == 0
    assert library.get_paper(paper["id"])["search_sync"]["status"] == "stale"
    synced = index.sync(paper["id"], actor="reviewer")
    assert synced["status"] == "ready" and synced["mode"] == "legacy_text"
    assert index.eligible_hit(hits[0])
    assert index.bind_hit(hits[0]).metadata["title"] == "Corrected maize study"


def test_chat_uses_real_body_with_current_provenance_and_rechecks_availability(migrated):
    library, paper, store, hits, _ = migrated
    library.search_index.adopt_legacy_index(store)
    model = FakeLLMClient("该研究讨论水分与氮素迁移的关系。[1]")
    retriever = FakeRetriever(hits)
    service = ChatService(retriever, model, top_k=5, max_context_chars=4000, temperature=0,
                          literature_index=library.search_index)

    result = asyncio.run(service.answer("氮素淋失主要受哪些因素影响？", allow_general_knowledge=True))

    assert len(result.citations) == 1
    assert result.citations[0].document_id == paper["id"]
    assert result.citations[0].file_sha256 == paper["sha256"]
    assert result.citations[0].content_version == library.get_paper(paper["id"])["search_sync"]["version"]
    assert "Irrigation transports nitrate" in model.last_messages[0].content
    assert not result.answer.startswith("以下回答未引用")
    assert retriever.calls == []  # Verified text answers broad factors without a slow rerank.

    original_chat = model.chat
    async def close_during_generation(messages, **kwargs):
        disable_paper(FakeRequest(library), paper["id"], ReasonInput(reason="closed during generation"), EDITOR)
        return await original_chat(messages, **kwargs)
    model.chat = close_during_generation
    with pytest.raises(RAGQueryError, match="evidence_changed_during_generation"):
        asyncio.run(service.answer("nitrogen leaching", allow_general_knowledge=True))
