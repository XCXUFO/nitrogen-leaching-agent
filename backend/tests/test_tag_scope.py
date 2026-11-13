"""Labels constrain SQL and vector recall before reranking, without online calls."""
from types import SimpleNamespace
import asyncio

import pytest

from src.agent.chat_service import ChatService
from src.agent.runtime import AgentRuntime
from src.agent.contracts import TaskState
from src.agent.understanding import understand, map_tags
from src.api.chat_schema import ChatRequest
from src.api.literature import DimensionInput, TagInput, create_dimension, create_tag
from src.rag.retriever import Retriever
from src.storage.chroma_store import ChromaStore
from tests.test_literature import FakeRequest
from tests.test_literature_search_sync import library, seed, edit, USER
from tests.test_chat_service import FakeLLMClient, FakeRetriever
from tests.test_retriever import FakeEmbedder


def parse(library,query):
    understanding=understand(ChatRequest(query=query),TaskState(conversation_id='scope'),
        SimpleNamespace(run_id='scope',turn_id='turn'),library.taxonomy())
    return understanding,map_tags(understanding,library.taxonomy())


def tags(library):
    dimension=create_dimension(FakeRequest(library),DimensionInput(name='作物'),USER)
    return {name:create_tag(FakeRequest(library),dimension['id'],TagInput(name=name),USER)['id']
            for name in ('玉米','小麦','水稻')}


def paper(library,name,tag_ids=(),retriever=None):
    value=seed(library,title=name,text='Unique synthetic fixture '+name.encode().hex())
    value=edit(library,value['id'],tag_ids=list(tag_ids))
    library.search_index.sync(value['id'],actor='fixture',loader=lambda _:name+'。本试验采用玉米，记录氮素淋溶与灌溉过程。',retriever=retriever)
    return library.get_paper(value['id'])


def test_sql_scope_excludes_untagged_documents_even_when_they_match_the_query(library):
    ids=tags(library)
    inside=paper(library,'玉米灌溉研究',[ids['玉米']])
    outside=paper(library,'未打标签的玉米灌溉研究')
    u,m=parse(library,'玉米灌溉的氮素淋溶过程')
    scope=library.search_index.tag_scope(m,u)
    assert scope['paper_ids']==[inside['id']] and scope['total_papers']==2
    rows,_=library.search_index.local.candidates('玉米灌溉',m,understanding=u,material_ids=set(scope['paper_ids']))
    assert rows and {r['material_id'] for r in rows}=={inside['id']}
    assert outside['id'] not in {r['material_id'] for r in rows}


@pytest.mark.asyncio
async def test_vector_filter_is_applied_before_reranker(library,tmp_path):
    ids=tags(library)
    store=ChromaStore(tmp_path/'vectors','scope-test')
    class Reranker:
        def __init__(self): self.seen=[]
        def rerank(self,query,results):
            self.seen.extend(results)
            return results
    reranker=Reranker()
    retriever=Retriever(FakeEmbedder(),store,reranker=reranker)
    inside=await asyncio.to_thread(paper,library,'玉米灌溉研究',[ids['玉米']],retriever)
    outside=await asyncio.to_thread(paper,library,'范围外的玉米研究',(),retriever)
    u,m=parse(library,'玉米氮素淋溶过程')
    events=[]
    result=await ChatService(retriever,FakeLLMClient('已有材料说明。[1]'),top_k=5,max_context_chars=4000,
        temperature=0,literature_index=library.search_index).answer(u['raw_query'],understanding=u,tag_mapping=m,retrieval_observer=events.append)
    assert reranker.seen and {r.metadata['paper_id'] for r in reranker.seen}=={inside['id']}
    assert all(r.metadata['paper_id']!=outside['id'] for r in reranker.seen)
    assert result.literature_scope['paper_count']==1
    assert events[0]['pipeline']['tag_scope']['paper_count']==1
    assert result.citations and inside['id'] in result.citations[0].source


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit',[False,True])
async def test_empty_scope_stops_without_embedding_generation_or_expansion(library,explicit):
    tags(library)
    await asyncio.to_thread(paper,library,'未打标签的玉米研究')
    u,m=parse(library,'只查带玉米标签的文献，介绍氮素淋溶' if explicit else '玉米氮素淋溶过程')
    retriever=FakeRetriever([]);model=FakeLLMClient()
    result=await ChatService(retriever,model,top_k=5,max_context_chars=4000,temperature=0,
        literature_index=library.search_index).answer(u['raw_query'],understanding=u,tag_mapping=m)
    assert result.outcome=='clarification' and result.literature_scope['paper_count']==0
    assert not retriever.calls and model.last_messages is None
    assert '正文依据' in result.answer and '标签' not in result.answer and '扩大' not in result.answer


@pytest.mark.asyncio
async def test_only_authorized_automatic_scope_expansion_can_use_untagged_content(library):
    tags(library)
    outside=await asyncio.to_thread(paper,library,'未打标签的玉米研究')
    u,m=parse(library,'玉米氮素淋溶过程')
    result=await ChatService(FakeRetriever([]),FakeLLMClient('已有材料。[1]'),top_k=5,max_context_chars=4000,
        temperature=0,literature_index=library.search_index).answer(u['raw_query'],understanding=u,tag_mapping=m,allow_scope_expansion=True)
    assert result.literature_scope['expanded']
    assert result.literature_scope['expansion_reason']=='no_usable_tagged_content'
    assert result.citations and outside['id'] in result.citations[0].source
    u,m=parse(library,'只查带玉米标签的文献，介绍氮素淋溶')
    result=await ChatService(FakeRetriever([]),FakeLLMClient(),top_k=5,max_context_chars=4000,
        temperature=0,literature_index=library.search_index).answer(u['raw_query'],understanding=u,tag_mapping=m,allow_scope_expansion=True)
    assert not result.literature_scope.get('expanded') and result.outcome=='clarification'


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit',[False,True])
async def test_runtime_manages_local_fallback_without_a_request_switch(library,explicit):
    tags(library)
    outside=await asyncio.to_thread(paper,library,'未打标签的玉米研究')
    runtime=AgentRuntime()
    try:
        response=await runtime.execute(ChatRequest(query='只查带玉米标签的文献，介绍氮素淋溶' if explicit else '玉米氮素淋溶研究中测得的施肥量是多少'),
            service=ChatService(FakeRetriever([]),FakeLLMClient('已有材料。[1]'),top_k=5,max_context_chars=4000,
                temperature=0,literature_index=library.search_index),get_report=None,taxonomy_provider=library.taxonomy)
        trace=runtime.runs.get(response.run_id)
        scopes=[event['pipeline']['tag_scope'] for event in trace.retrieval if event.get('pipeline',{}).get('tag_scope')]
        assert scopes and scopes[0]['paper_count']==0
        if explicit:
            assert not any(scope.get('expanded') for scope in scopes) and not response.citations
        else:
            assert len(scopes)==2 and scopes[1]['expanded']
            assert scopes[1]['eligible_chunks']==1 and scopes[1]['initial_eligible_chunks']==0
            assert response.citations and outside['id'] in response.citations[0].source
        assert 'allow_local_scope_expansion' not in ChatRequest.model_json_schema()['properties']
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_retrieval_failure_preserves_scope_instead_of_expanding(library):
    ids=tags(library)
    await asyncio.to_thread(paper,library,'玉米研究',[ids['玉米']])
    await asyncio.to_thread(paper,library,'未打标签的玉米研究')
    class BrokenRetriever:
        def retrieve(self,*args,**kwargs): raise RuntimeError('offline retrieval failure')
    u,m=parse(library,'玉米氮素淋溶过程')
    result=await ChatService(BrokenRetriever(),FakeLLMClient('已有材料。[1]'),top_k=5,max_context_chars=4000,
        temperature=0,literature_index=library.search_index).answer(u['raw_query'],understanding=u,tag_mapping=m,allow_scope_expansion=True)
    assert result.literature_scope['retrieval_failed'] and not result.literature_scope.get('expanded')


@pytest.mark.asyncio
async def test_basic_explanation_does_not_expand_only_because_tagged_sources_are_missing(library):
    tags(library)
    await asyncio.to_thread(paper,library,'未打标签的玉米研究')
    u,m=parse(library,'解释玉米氮素淋溶的概念')
    retriever=FakeRetriever([])
    result=await ChatService(retriever,FakeLLMClient('氮素淋溶的一般知识说明。'),top_k=5,max_context_chars=4000,
        temperature=0,literature_index=library.search_index).answer(u['raw_query'],understanding=u,tag_mapping=m,
            task_scope='concept_explanation',allow_scope_expansion=True)
    assert not result.literature_scope.get('expanded') and not retriever.calls and not result.citations
    assert result.answer == '氮素淋溶的一般知识说明。'
    assert result.citations == []


def test_unreviewed_aliases_cannot_silently_define_the_corpus(library):
    ids=tags(library)
    paper(library,'玉米研究',[ids['玉米']])
    mapping={'mappings':[{'status':'matched','canonical':'猜测别名','candidates':[
        {'id':ids['玉米'],'path':'玉米','dimension_id':'crop','method':'configured_alias','review_status':'pending'}]}]}
    assert library.search_index.tag_scope(mapping)['mode']=='unrestricted'


def test_same_dimension_or_and_cross_dimension_and(library):
    ids=tags(library)
    region=create_dimension(FakeRequest(library),DimensionInput(name='地区'),USER)
    north=create_tag(FakeRequest(library),region['id'],TagInput(name='河北'),USER)['id']
    target=paper(library,'河北玉米研究',[ids['玉米'],north])
    second=paper(library,'河北小麦研究',[ids['小麦'],north])
    paper(library,'其他玉米研究',[ids['玉米']])
    u,m=parse(library,'只查带玉米或小麦标签，带河北标签的文献')
    assert set(library.search_index.tag_scope(m,u)['paper_ids'])=={target['id'],second['id']}
