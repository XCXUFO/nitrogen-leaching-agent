"""Current workbench bibliography survives both chat response paths."""
import httpx
import pytest

from src.agent.chat_service import Citation
from src.rag import documents as catalog
from src.storage.run_store import RunStore
from src.api.literature import LiteratureStore
from tests.test_chat_runs import body, finished, make_app
from tests.test_literature_search_sync import edit, seed


@pytest.fixture
def managed(tmp_path, monkeypatch):
    library = LiteratureStore(str(tmp_path / "papers.sqlite3"), str(tmp_path / "files"))
    paper = seed(library)
    originals = tmp_path / "originals"
    originals.mkdir()
    monkeypatch.setattr(catalog, "PAPERS_DIR", originals)
    original = library.root / f"blob-{paper['sha256']}.pdf"
    (originals / "legacy.pdf").write_bytes(original.read_bytes())
    yield library, paper, original
    library.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("recoverable", [False, True], ids=["immediate", "recovered"])
@pytest.mark.parametrize("legacy", [False, True], ids=["managed", "legacy"])
@pytest.mark.parametrize("missing_file", [False, True], ids=["original_available", "original_missing"])
async def test_chat_transmits_current_title_all_authors_and_year(managed, tmp_path, recoverable, legacy, missing_file):
    library, paper, original = managed
    source = "data/papers/legacy.pdf" if legacy else f"managed://{paper['id']}/upload.pdf"
    runs = RunStore(tmp_path / "runs.sqlite3")
    app = make_app(runs)
    app.state.literature = library
    app.state.chat_service.citations = [Citation(index=1, source=source, chunk_id="original-chunk", score=.8,
        snippet="内部片段", title="旧题名", author_hint="旧作者", year="2020", char_start=3138, char_end=3586)]
    # Resolve the current workbench record instead of an index/catalog snapshot.
    current = edit(library, paper["id"], title="更正后的论文题名", year=2025,
        authors=[{"name": "张三", "kind": "person"}, {"name": "李四", "kind": "person"},
                 {"name": "农业研究所", "kind": "institution"}])
    if missing_file:
        original.unlink()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/api/chat", json=body() if recoverable else {"query": body()["query"]})
            assert response.status_code == (202 if recoverable else 200)
            if recoverable:
                terminal = await finished(client, response.json()["run_id"])
                assert terminal["status"] == "succeeded" and terminal["result_saved"]
                result = terminal["result"]
                restored = await client.get("/api/chat/requests/request-one", params={"session_id": "conversation-one"})
                assert restored.json()["result"] == result
            else:
                result = response.json()
        citation, = result["citations"]
        assert citation["title"] == current["title"]
        assert citation["author_hint"] == "、".join(author["name"] for author in current["authors"])
        assert citation["year"] == str(current["year"])
        assert citation["document_id"] == paper["id"]
        assert citation["document_available"] is (not missing_file)
        assert citation["source"] == source and citation["chunk_id"] == "original-chunk"
        assert citation["snippet"] == "内部片段"
        assert (citation["char_start"], citation["char_end"]) == (3138, 3586)
    finally:
        if hasattr(app.state, "chat_runs"):
            await app.state.chat_runs.shutdown()
        runs.close()


def test_unknown_fields_do_not_fall_back_to_stale_authors_or_guessed_year(managed):
    library, paper, _ = managed
    edit(library, paper["id"], authors=[], authors_unknown=True, year=None, year_unknown=True)
    metadata = library.search_index.citation_metadata(f"managed://{paper['id']}/2020_old-author.pdf")
    assert metadata["author_hint"] is None and metadata["year"] is None
    assert library.search_index.citation_metadata("session://upload/legacy.pdf") is None


def test_legacy_association_requires_matching_contents(managed):
    library, _, _ = managed
    (catalog.PAPERS_DIR / "legacy.pdf").write_bytes(b"different contents")
    assert library.search_index.citation_metadata("data/papers/legacy.pdf") is None
