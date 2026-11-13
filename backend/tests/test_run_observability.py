import pytest

from src.agent.chat_service import ChatService
from src.rag.retriever import Retriever, RetrievalResult, describe_hits
from tests.test_chat_service import FakeLLMClient


class Embedder:
    def embed_query(self, query):
        return [1.0]


class Store:
    def query(self, vector, k):
        return {'ids': [['a', 'b', 'c']], 'documents': [['Evidence in A.', 'Evidence in B.', 'Evidence in C.']],
                'distances': [[.1, .2, .3]],
                'metadatas': [[{'paper_id': name, 'title': f'Paper {name}', 'source': f'{name}.pdf'} for name in ('a', 'b', 'c')]]}


class Reranker:
    def rerank(self, query, candidates):
        return list(reversed(candidates))


def test_source_title_fallback_is_readable_and_cannot_block_retrieval(monkeypatch):
    monkeypatch.setattr('src.rag.retriever.article_label', lambda source: ('文献原始标题', None))
    hit = RetrievalResult('legacy', 'body', .9, {'source':'legacy.pdf'})
    assert describe_hits([hit])[0]['title'] == '文献原始标题'

    def missing(source):
        raise FileNotFoundError('display manifest missing')

    monkeypatch.setattr('src.rag.retriever.article_label', missing)
    assert describe_hits([hit])[0]['source'] == 'legacy.pdf'


def test_records_actual_recall_rerank_and_top_k_without_changing_results():
    retriever = Retriever(Embedder(), Store(), reranker=Reranker())
    diagnostics = {}
    result = retriever.retrieve('query', k=2, eligibility_filter=lambda hit: hit.chunk_id != 'b', diagnostics=diagnostics)
    assert [item['chunk_id'] for item in diagnostics['recall']] == ['a', 'b', 'c']
    assert [item['chunk_id'] for item in diagnostics['reranked']] == ['c', 'a']
    assert [item['rank'] for item in diagnostics['reranked']] == [1, 2]
    assert diagnostics['rerank_status'] == 'applied'
    assert [item['chunk_id'] for item in diagnostics['returned']] == [item.chunk_id for item in result] == ['c', 'a']
    assert diagnostics['returned'][0]['title'] == 'Paper c'
    assert all('document' not in item for item in diagnostics['recall'])


def test_disabled_reranker_is_explicit_and_does_not_invent_rerank_results():
    diagnostics = {}
    Retriever(Embedder(), Store()).retrieve('query', k=1, diagnostics=diagnostics)
    assert diagnostics['rerank_status'] == 'disabled'
    assert 'reranked' not in diagnostics
    assert [item['chunk_id'] for item in diagnostics['returned']] == ['a']


@pytest.mark.asyncio
@pytest.mark.parametrize('budget', [1, 2000])
async def test_trace_distinguishes_ranked_supplied_and_final_cited_material(budget):
    service = ChatService(Retriever(Embedder(), Store(), reranker=Reranker()), FakeLLMClient('Only the second passage [2].'),
                          top_k=2, max_context_chars=budget, temperature=0)
    trace = []
    result = await service.answer('query', retrieval_observer=trace.append)
    selection, context = trace
    assert selection['retrieval_id'] == context['retrieval_id']
    assert selection['semantic']['rounds'][0]['rerank_status'] == 'applied'
    assert [item['chunk_id'] for item in selection['ranked_candidates']] == ['c', 'b']
    # The prompt builder retains a truncated first passage at a one-character budget.
    assert context['adopted_chunk_ids'] == (['c', 'b'] if budget > 1 else ['c'])
    assert [item['chunk_id'] for item in context['supplied_candidates']] == context['adopted_chunk_ids']
    assert [citation.chunk_id for citation in result.citations] == (['b'] if budget > 1 else [])
    if budget > 1:
        assert result.citations[0].retrieval_ids == [selection['retrieval_id']]
        assert result.citations[0].chunk_ids == ['b']


@pytest.mark.asyncio
async def test_session_documents_are_included_in_recorded_candidates():
    from tests.test_chat_service import FakeRetriever
    service = ChatService(FakeRetriever([]), FakeLLMClient('Session evidence [1].'), top_k=2, max_context_chars=2000, temperature=0)
    trace = []
    await service.answer('irrigation', session_documents=[{'sha256':'session-hash', 'file':'irrigation.txt', 'text':'Irrigation affects nitrogen leaching.'}], retrieval_observer=trace.append)
    assert trace[0]['candidates'][0]['source'] == 'session://session-hash/irrigation.txt'
    assert trace[0]['candidates'][0]['recall_paths'] == ['session']
    assert trace[0]['candidates'][0]['chunk_id'] in trace[1]['adopted_chunk_ids']


def test_citation_normalization_preserves_only_used_origins_across_document_merges():
    from src.agent.chat_service import Citation, normalize_citations
    from src.agent.runtime import collect_evidence
    from src.api.chat_schema import ChatResponse
    from src.llm.base import ChatUsage

    citations = [Citation(index=index, chunk_id=chunk, document_id='paper', source='paper.pdf',
                          score=1, snippet='same quote', retrieval_ids=[origin], chunk_ids=[chunk])
                 for index, chunk, origin in [(1, 'a', 'round-1'), (2, 'b', 'round-2'), (3, 'c', 'unused-round')]]
    answer, used, mapping = normalize_citations('First [1], second [2], repeated [1].', citations)
    assert mapping == {1: 1, 2: 1}
    assert used[0].retrieval_ids == ['round-1', 'round-2']
    assert used[0].chunk_ids == ['a', 'b']
    assert citations[0].retrieval_ids == ['round-1']  # Do not mutate the input.
    repeated_answer, repeated, _ = normalize_citations(answer, used)
    assert repeated_answer == answer and repeated == used
    response = ChatResponse(answer=answer, citations=used,
                            usage=ChatUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                            retrieved_count=3, model='test')
    evidence = collect_evidence(response, 'test-run')[0]
    assert evidence.retrieval_ids == ['round-1', 'round-2']
    assert evidence.chunk_ids == ['a', 'b']
