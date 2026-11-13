"""Managed PDF/index association, real extraction, stale races and retrieval."""
from types import SimpleNamespace

import pytest

from src.api.literature import LiteratureStore, PaperInput, PaperUpdateInput, ReasonInput, create_paper, update_paper, disable_paper, delete_paper
from src.agent.chat_service import ChatService
from src.rag.reference_filter import is_reference_chunk
from src.agent.understanding import understand, map_tags
from src.agent.contracts import TaskState
from src.api.chat_schema import ChatRequest
from src.evaluation.contracts import Principal
from src.llm.base import ChatResult, ChatUsage
from tests.test_literature import FakeRequest, pdf_bytes, upload_pdf
from tests.test_chat_service import FakeLLMClient, FakeRetriever


@pytest.fixture
def library(tmp_path):
    store = LiteratureStore(str(tmp_path / "papers.sqlite3"), str(tmp_path / "files"))
    yield store
    store.close()


USER = Principal(tester_id="expert", role="reviewer")


def seed(store, title="玉米水肥试验", text="Maize nitrogen leaching depends on water and nitrogen. Irrigation transports nitrate through soil."):
    upload_id = upload_pdf(store, USER, raw=pdf_bytes(text))
    return create_paper(FakeRequest(store), PaperInput(upload_id=upload_id, title=title, authors=["Author"],
        publication_type="期刊论文", venue="Fixture Journal", year=2024, language="英文", source_note="仅测试夹具", action="register"), USER)


def test_body_matches_outrank_title_only_chunks_and_references_do_not_consume_limit(library):
    paper = seed(library, title='Vegetable nitrous oxide emissions')
    references = ('Liang, X., Wang, Y., 2011. Vegetable nitrous oxide emissions temporal peaks. '
                  'Agric. Water Manage. 208, 1-10.\nZhang, L., Hu, K., 2019. Vegetable emissions. '
                  'Field Crops Res. 204, 1-11.\n\n') * 4
    background = ('This paragraph introduces the model and its input requirements. ' * 8) + '\n\n'
    results = ('Observed vegetable emissions showed temporal peaks after irrigation. '
               'Nitrous oxide dynamics varied between seasons. ' * 5)
    library.search_index.sync(paper['id'], actor='fixture', loader=lambda _: background + references + results)
    hits, candidates = library.search_index.search('vegetable nitrous oxide emissions temporal peaks dynamics', limit=1)
    assert len(hits) == 1 and 'Observed vegetable emissions' in hits[0].document
    assert not is_reference_chunk(hits[0].document)
    assert candidates.diagnostics['excluded_reference_chunks'] > 0
    assert any(row['body_matches'] == 0 and row['title_matches'] > 0 for row in candidates)


def edit(store, paper_id, **changes):
    current = store.get_paper(paper_id)
    return update_paper(FakeRequest(store), paper_id, PaperUpdateInput.model_validate(current | {"expected_revision": current["revision"], "action": "register", **changes}), USER)


class VectorStore:
    def __init__(self): self.calls = []
    def upsert(self, **kwargs): self.calls.append(kwargs)


def test_registration_is_distinct_from_fulltext_sync_and_metadata_reuses_text(library):
    paper = seed(library)
    assert paper["search_sync"]["status"] == "not_prepared"
    vectors = VectorStore()
    retriever = SimpleNamespace(_embedder=SimpleNamespace(embed_documents=lambda texts: [[1., 0.] for _ in texts]), _store=vectors)
    sync = library.search_index.sync(paper["id"], actor="expert", retriever=retriever)
    assert sync["status"] == "ready" and sync["mode"] == "vector_and_text"
    original = vectors.calls[0]
    assert original["metadatas"][0]["paper_id"] == paper["id"]
    def must_not_extract(path): raise AssertionError("idempotent sync must not re-extract")
    assert library.search_index.sync(paper["id"], actor="expert", loader=must_not_extract) == sync
    edit(library, paper["id"], title="更正后的玉米试验")
    assert library.get_paper(paper["id"])["search_sync"]["status"] == "stale"
    updated = library.search_index.sync(paper["id"], actor="expert", loader=must_not_extract)
    assert updated["status"] == "ready" and updated["version"] != sync["version"]
    assert len(library.events("paper", paper["id"])) >= 4


def test_older_task_cannot_mark_new_metadata_ready_and_failure_can_retry(library):
    paper = seed(library)
    def change_during_extraction(path):
        edit(library, paper["id"], title="任务执行期间修改的标题")
        return "Maize nitrogen soil irrigation."
    result = library.search_index.sync(paper["id"], actor="expert", loader=change_during_extraction)
    assert result["status"] == "stale"
    failed = library.search_index.sync(paper["id"], actor="expert", loader=lambda path: "")
    assert failed["status"] == "failed" and "没有可读正文" in failed["reason"]
    assert library.search_index.sync(paper["id"], actor="expert")["status"] == "ready"


def test_untagged_content_recall_records_conditions_and_disable_excludes_immediately(library):
    paper = seed(library)
    library.search_index.sync(paper["id"], actor="expert")
    understanding = understand(ChatRequest(query="玉米氮淋失的影响因素"), TaskState(conversation_id="session"), SimpleNamespace(run_id="run", turn_id="turn"))
    hits, candidates = library.search_index.search("玉米氮淋失", understanding=understanding)
    assert hits and candidates[0]["checks"][0]["state"] == "satisfied"
    assert library.search_index.eligible_hit(hits[0])
    assert library.search_index.public_file(paper["id"])
    disable_paper(FakeRequest(library), paper["id"], ReasonInput(reason="停止采用"), USER)
    assert library.search_index.search("玉米氮淋失")[0] == []
    assert not library.search_index.eligible_hit(hits[0])
    assert library.search_index.public_file(paper["id"]) is None


@pytest.mark.parametrize("mode", ["answer", "mechanisms"])
def test_unavailable_vectors_are_filtered_before_reranking(library, mode):
    import asyncio
    from src.agent.composition import MechanismEvidenceError
    from src.rag.retriever import Retriever
    from tests.test_retriever import FakeEmbedder, _FakeReranker

    paper = seed(library)
    # A registered PDF without a current fulltext index cannot be used yet.
    class RecalledVectors:
        def query(self, vector, k):
            return {"ids": [["not-ready"]], "documents": [["Maize nitrogen leaching."]],
                    "distances": [[0.0]], "metadatas": [[{"paper_id": paper["id"], "content_key": "old"}]]}
    reranker = _FakeReranker()
    retriever = Retriever(FakeEmbedder(), RecalledVectors(), reranker=reranker)
    model = FakeLLMClient("通用知识说明。")
    service = ChatService(retriever, model, top_k=5, max_context_chars=3000, temperature=0,
                          literature_index=library.search_index)

    if mode == "mechanisms":
        with pytest.raises(MechanismEvidenceError, match="mechanism_evidence_missing"):
            asyncio.run(service.explain_mechanisms("氮素淋失影响因素"))
        assert model.last_messages is None
    else:
        result = asyncio.run(service.answer("氮素淋失影响因素", allow_general_knowledge=True))
        assert result.answer == "通用知识说明。" and result.citations == []
    assert reranker.calls == []


@pytest.mark.asyncio
async def test_managed_text_enters_real_prompt_and_changed_evidence_is_not_returned(library):
    # Seed outside an event-loop-owned upload helper.
    import asyncio
    paper = await asyncio.to_thread(seed, library)
    library.search_index.sync(paper["id"], actor="expert")
    class LLM:
        def __init__(self): self.messages = []; self.close_source = False
        async def chat(self, messages, **kwargs):
            self.messages = messages
            if self.close_source: disable_paper(FakeRequest(library), paper["id"], ReasonInput(reason="停用"), USER)
            return ChatResult(content="资料说明氮淋失与水分有关。[1]", model="fixture", usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))
    model = LLM()
    service = ChatService(SimpleNamespace(retrieve=lambda *args: []), model, top_k=5, max_context_chars=3000, temperature=0, literature_index=library.search_index)
    records = []
    result = await service.answer("玉米氮淋失", retrieval_observer=records.append)
    assert "Maize nitrogen" in model.messages[0].content
    assert result.citations[0].document_id == paper["id"]
    assert records[0]["source_type"] == "literature"
    model.close_source = True
    from src.agent.chat_service import RAGQueryError
    with pytest.raises(RAGQueryError): await service.answer("玉米氮淋失")


@pytest.mark.parametrize("explicit_tag", [False, True], ids=["title_scope", "tag_filter"])
@pytest.mark.parametrize("vector_only", [False, True], ids=["text_search", "vector_search"])
@pytest.mark.parametrize("mode", ["answer", "mechanisms"])
def test_managed_scope_and_tags_survive_answer_validation(library, monkeypatch, explicit_tag, vector_only, mode):
    import asyncio
    import json
    from src.api.literature import DimensionInput, TagInput, create_dimension, create_tag

    quote = "Irrigation transports nitrate through soil."
    text = ("Tomato nitrogen leaching. " if explicit_tag else "Nitrogen leaching. ") + quote
    paper = seed(library, title="番茄氮淋失试验", text=text)
    if explicit_tag:
        dimension = create_dimension(FakeRequest(library), DimensionInput(name="作物"), USER)
        tag = create_tag(FakeRequest(library), dimension["id"], TagInput(name="番茄"), USER)
        paper = edit(library, paper["id"], tag_ids=[tag["id"]])
    library.search_index.sync(paper["id"], actor="expert")
    query = "只查带番茄标签的文献，介绍氮淋失" if explicit_tag else "番茄氮淋失是什么？"
    parsed = understand(ChatRequest(query=query), TaskState(conversation_id="scope"),
                        SimpleNamespace(run_id="scope", turn_id="turn"), library.taxonomy())
    mapping = map_tags(parsed, library.taxonomy())
    hits, _ = library.search_index.search(query, understanding=parsed, mapping=mapping)
    assert len(hits) == 1
    retriever = FakeRetriever(hits if vector_only else [])
    if vector_only:
        # Vector metadata does not carry the title or assigned tag IDs.
        hits[0].metadata.pop("title", None)
        monkeypatch.setattr(library.search_index, "search", lambda *args, **kwargs: ([], []))
    model = FakeLLMClient(json.dumps({"claims": [{"text": "该研究条件下，灌溉可促使硝态氮随水迁移。",
        "citation_index": 1, "supporting_quote": quote}]}, ensure_ascii=False) if mode == "mechanisms" else "材料解释。[1]")
    service = ChatService(retriever, model, top_k=5, max_context_chars=3000, temperature=0,
                          literature_index=library.search_index)
    records = []
    operation = service.answer if mode == "answer" else service.explain_mechanisms
    result = asyncio.run(operation(query, understanding=parsed, tag_mapping=mapping, retrieval_observer=records.append,
                                   **({"crop": "番茄"} if mode == "mechanisms" else {})))
    assert len(result.citations) == 1
    assert paper["id"] in result.citations[0].source
    assert quote in "\n".join(message.content for message in model.last_messages)
    assert records[-1]['status'] == 'supplied'
    if mode == 'answer': assert records[-1]['adopted_chunk_ids']
    if explicit_tag:
        # Preserving the tag filter must not make an untagged record eligible.
        updated = edit(library, paper["id"], tag_ids=[])
        library.search_index.sync(paper["id"], actor="expert")
        # Present a current vector hit, so rejection cannot rely on a stale key.
        from dataclasses import replace
        current_hit = replace(hits[0], metadata={**hits[0].metadata, "content_key": library.search_index.content_key(updated)})
        retriever._results = [current_hit]
        if mode == "mechanisms":
            from src.agent.composition import MechanismEvidenceError
            with pytest.raises(MechanismEvidenceError):
                asyncio.run(operation(query, crop="番茄", understanding=parsed, tag_mapping=mapping))
        else:
            assert not asyncio.run(operation(query, understanding=parsed, tag_mapping=mapping)).citations
