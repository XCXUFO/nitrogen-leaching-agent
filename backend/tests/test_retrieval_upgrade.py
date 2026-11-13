"""V0.1 acceptance boundaries, using exported IDs without importing its dimensions."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.contracts import TaskState
from src.agent.understanding import understand, map_tags, assess_conditions, canonical
from src.agent.tag_matching import tag_index
from src.agent.case_retrieval import select_materials
from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatRequest
from src.storage.case_library import CaseStore, CaseInput
from src.retrieval.local_index import fuse, retrieval_requests

PACKAGE = Path(__file__).resolve().parents[2] / 'docs/iterations/2026-11-11-retrieval-skills/source/标签与Skill本地迭代包'


@pytest.fixture
def taxonomy():
    exported = json.loads((PACKAGE / 'taxonomy.json').read_text())
    # Local test adapter only: the package explicitly has no online dimension IDs.
    return {'dimensions':[dict(d,id='fixture:'+d['key']) for d in exported['dimensions']],
            'tags':[dict(t,dimension_id='fixture:'+t['dimension_key']) for t in exported['tags']]}


def parse(query, taxonomy=None, state=None):
    return understand(ChatRequest(query=query),state or TaskState(conversation_id='fixture'),
                      SimpleNamespace(run_id='r',turn_id='t'),taxonomy)


def test_a02_chemical_and_longest_phrase_normalization():
    assert canonical('N₂O n2o N2O nitrous oxide') == '氧化亚氮 '*3+'氧化亚氮'
    assert canonical('drip irrigation') == '滴灌'
    assert canonical('NO3 NH3') != canonical('N2O')


def test_a09_a10_duplicate_names_paths_and_explicit_membership(taxonomy):
    interpreted=parse('找陕西案例',taxonomy)
    mapping=map_tags(interpreted,taxonomy)
    region=next(m for m in mapping['mappings'] if m['canonical']=='陕西')
    assert {c['id'] for c in region['candidates']}=={'T-24799bce23b7','T-cafd9629e04b'}
    assert region['status']=='ambiguous' and not region['requires_resolution']
    assert assess_conditions('试验地点为陕西，记录分次施肥。',[],interpreted,mapping)[1]
    interpreted=parse('只查“西北 / 陕西”标签记录',taxonomy)
    mapping=map_tags(interpreted,taxonomy)
    assert mapping['unresolved_filters']==[]
    assert len(mapping['mappings'])==1
    assert mapping['mappings'][0]['usage']=='explicit_tag_filter'
    assert assess_conditions('试验地点为陕西。',['T-cafd9629e04b'],interpreted,mapping)[1]
    assert not assess_conditions('试验地点为陕西。',['T-24799bce23b7'],interpreted,mapping)[1]
    assert not assess_conditions('试验地点为陕西。',[],interpreted,mapping)[1]


def test_explicit_same_dimension_or_cross_dimension_and(taxonomy):
    understood=parse('只查带玉米或小麦标签，带西北 / 陕西标签的记录',taxonomy)
    mapping=map_tags(understood,taxonomy)
    assert assess_conditions('本试验采用小麦。',['T-9daff4a90de4','T-cafd9629e04b'],understood,mapping)[1]
    assert not assess_conditions('本试验采用小麦。',['T-9daff4a90de4'],understood,mapping)[1]
    assert not assess_conditions('本试验采用小麦。',['T-cafd9629e04b'],understood,mapping)[1]


def test_pending_related_aliases_never_become_membership_filters(taxonomy):
    parsed=parse('硝态氮淋失的影响因素',taxonomy)
    mapping=map_tags(parsed,taxonomy)
    proposed=[m for m in mapping['mappings'] if m['method']=='configured_alias']
    assert proposed and all(m['usage']=='ranking_signal' for m in proposed)
    assert all(c['review_status']=='pending' for m in proposed for c in m['candidates'])
    explicit=parse('只查带硝态氮淋失标签的文献',taxonomy)
    assert any(m['requires_resolution'] for m in map_tags(explicit,taxonomy)['mappings'])


def test_a14_effective_status_cache_refresh_and_run_snapshot(taxonomy):
    first=parse('找玉米案例',taxonomy)
    original=copy.deepcopy(map_tags(first,taxonomy))
    maize=next(t for t in taxonomy['tags'] if t['name']=='玉米')
    next(t for t in taxonomy['tags'] if t['id']==maize['parent_id'])['enabled']=False
    assert map_tags(first,taxonomy)==original
    newer=parse('找玉米案例',taxonomy)
    assert map_tags(newer,taxonomy)['mappings']==[]
    index,_=tag_index(taxonomy,{})
    assert index.candidates('桂平','桂平')==[]


def test_a07_a08_correction_negation_and_no_negative_recall(taxonomy):
    original=parse('找陕西玉米案例',taxonomy)
    state=TaskState(conversation_id='fixture',understanding_context=original)
    corrected=parse('刚才从玉米更正为番茄',taxonomy,state)
    assert {c['value'] for c in corrected['conditions'] if c['category']=='crop'}=={'番茄'}
    assert any(c['value']=='陕西' and c['source']=='historical_user' for c in corrected['conditions'])
    excluded=parse('排除玉米，找小麦研究',taxonomy)
    assert next(c for c in excluded['concepts'] if c['canonical']=='玉米')['polarity']=='exclude'
    assert all('玉米' not in q for q in retrieval_requests(excluded['raw_query'],excluded).values())
    assert assess_conditions('本试验采用小麦。',[],excluded,map_tags(excluded,taxonomy))[1]
    assert not assess_conditions('本试验采用玉米。',[],excluded,map_tags(excluded,taxonomy))[1]


@pytest.mark.parametrize('query,matching,rejected',[
    ('比较河北与陕西的玉米文献',['河北玉米试验','陕西玉米试验'],['陕西小麦试验']),
    ('比较河北玉米与陕西小麦文献',['河北玉米试验','陕西小麦试验'],['河北小麦试验','陕西玉米试验'])])
def test_a11_per_object_scope_and_recall(taxonomy,query,matching,rejected):
    parsed=parse(query,taxonomy)
    mapping=map_tags(parsed,taxonomy)
    assert len([key for key in retrieval_requests(query,parsed) if key.startswith('object:')])==2
    for text in matching: assert assess_conditions(text,[],parsed,mapping)[1]
    for text in rejected: assert not assess_conditions(text,[],parsed,mapping)[1]


def test_a12_a13_no_tag_evidence_conflicts_and_unknown(taxonomy):
    parsed=parse('找玉米案例',taxonomy)
    mapping=map_tags(parsed,taxonomy)
    assert assess_conditions('本试验采用玉米。',[],parsed,mapping)[1]
    checks,eligible=assess_conditions('玉米案例标题\n本试验采用小麦。',['T-74ce41cce69c'],parsed,mapping)
    assert not eligible and checks[0]['conflict'] and checks[0]['state']=='not_satisfied'
    checks,eligible=assess_conditions('只提供施肥次数，未记载作物。',[],parsed,mapping)
    assert not eligible and checks[0]['state']=='unknown'


@pytest.fixture
def store(tmp_path):
    value=CaseStore(str(tmp_path/'cases.sqlite3'))
    yield value
    value.close()


def test_a17_warm_index_only_refreshes_changed_material_and_immediate_closure(store,monkeypatch):
    items=[store.create(CaseInput(title=f'玉米案例{i}',body=f'本试验采用玉米。分组{i}',enabled=True),'fixture') for i in range(4)]
    selected,trace=select_materials(store,'玉米')
    assert len(selected)==4 and trace['pipeline']['rebuilt_materials']==4
    def no_full_scan(ids=None):
        assert ids is not None
        return original(ids)
    original=store.candidates
    monkeypatch.setattr(store,'candidates',no_full_scan)
    assert select_materials(store,'玉米')[1]['pipeline']['rebuilt_materials']==0
    current=store.change(items[0]['id'],1,{'body':'本试验采用小麦。','tag_ids':['changed']},'fixture')
    assert select_materials(store,'小麦')[1]['pipeline']['rebuilt_materials']==1
    store.change(current['id'],current['revision'],{'enabled':False},'fixture')
    rows,trace=select_materials(store,'小麦')
    assert items[0]['id'] not in {r['id'] for r in rows}
    assert trace['pipeline']['rebuilt_materials']==1


def test_a18_atomic_rebuild_rollback_and_legacy_fallback(store,monkeypatch):
    item=store.create(CaseInput(title='玉米试验',body='初始正文',enabled=True),'fixture')
    select_materials(store,'玉米')
    store.change(item['id'],1,{'body':'最新小麦正文'},'fixture')
    monkeypatch.setattr(store.search_index,'_read',lambda _: (_ for _ in ()).throw(RuntimeError('injected failure')))
    rows,trace=select_materials(store,'小麦')
    assert rows[0]['body']=='最新小麦正文'
    assert trace['pipeline']['status']=='degraded' and trace['pipeline']['fallback']=='scan'
    assert store.db.execute('SELECT text FROM local_case_fts').fetchone()[0].startswith('初始正文')
    assert store.db.execute('SELECT count(*) FROM local_case_dirty').fetchone()[0]==1


def test_candidate_budget_and_rank_fusion_ignore_score_scales(store):
    for i in range(170):
        store.create(CaseInput(title=f'玉米{i}',body=f'玉米分组{i}',enabled=True),'fixture')
    rows,trace=store.search_index.candidates('玉米',budget=12)
    assert len(rows)==12 and trace['coverage']=='bounded'
    a=SimpleNamespace(chunk_id='a',score=.01)
    b=SimpleNamespace(chunk_id='b',score=100000)
    merged=fuse({'one':[a,b],'two':[a]})
    assert merged[0][0] is a and {r['route'] for r in merged[0][2]}=={'one','two'}


@pytest.mark.asyncio
@pytest.mark.parametrize('query',['只查带陕西标签的案例','只查带玉米和不存在甲标签的案例','只查带硝态氮淋失标签的文献'])
async def test_unresolved_explicit_filter_clarifies_without_execution(taxonomy,query):
    runtime=AgentRuntime()
    try:
        result=await runtime.execute(ChatRequest(query=query),service=None,get_report=None,taxonomy_provider=lambda:taxonomy)
        trace=runtime.runs.get(result.run_id)
        assert result.outcome=='clarification'
        assert [c.skill for c in trace.tool_calls]==['clarification']
        assert trace.execution_plan['actual_calls']==[c.model_dump(mode='json') for c in trace.tool_calls]
    finally: runtime.runs.close()


@pytest.mark.asyncio
async def test_a20_capability_skips_taxonomy_and_plan_is_not_a_call():
    runtime=AgentRuntime()
    try:
        calls=[]
        def forbidden():
            calls.append(True)
            raise AssertionError('capability must not query taxonomy')
        result=await runtime.execute(ChatRequest(query='你能做什么？'),service=None,get_report=None,taxonomy_provider=forbidden)
        trace=runtime.runs.get(result.run_id)
        assert trace.execution_plan['initial_selected_skills']==['capability_guidance']
        assert [t.skill for t in trace.tool_calls]==['capability_guidance']
        assert not calls and trace.retrieval==[] and trace.execution_plan['mode']=='auto'
    finally: runtime.runs.close()


def test_a11_both_objects_survive_material_budget(store,taxonomy):
    for i in range(4): store.create(CaseInput(title=f'河北玉米案例{i}',body='河北玉米施肥试验。',enabled=True),'fixture')
    other=store.create(CaseInput(title='陕西玉米案例',body='陕西玉米施肥试验。',enabled=True),'fixture')
    query='找河北与陕西玉米案例并比较'
    parsed=parse(query,taxonomy)
    selected,trace=select_materials(store,query,understanding=parsed,mapping=map_tags(parsed,taxonomy),max_cases=2)
    assert len(selected)==2 and other['id'] in {r['id'] for r in selected}
    assert trace['object_coverage']['missing']==[]
    original_ids={r['id'] for r in selected}
    assert store.search_index.ensure(rebuild=True)==5
    assert {r['id'] for r in select_materials(store,query,understanding=parsed,mapping=map_tags(parsed,taxonomy),max_cases=2)[0]}==original_ids


def test_switches_have_distinct_non_secret_versions():
    from src.config import Settings
    from src.evaluation.versioning import build_manifest
    settings=Settings(rag_enabled=False)
    original=build_manifest(settings)
    for key,value in [('unified_routing_enabled',False),('retrieval_strategy','scan'),('retrieval_fusion','legacy')]:
        altered=build_manifest(settings.model_copy(update={key:value}))
        assert altered['manifest_sha256']!=original['manifest_sha256']
        assert altered['answer_config'][key]==value


@pytest.mark.asyncio
@pytest.mark.parametrize('both',[True,False])
async def test_semantic_object_routes_and_missing_coverage_are_visible(taxonomy,both):
    from src.agent.chat_service import ChatService
    from src.rag.retriever import RetrievalResult
    from tests.test_chat_service import FakeRetriever,FakeLLMClient
    query='比较河北与陕西的玉米文献'
    parsed=parse(query,taxonomy)
    hits=[RetrievalResult('hebei','河北玉米试验记录分次施肥。',.9,{'source':'hebei.txt'})]
    if both: hits.append(RetrievalResult('shaanxi','陕西玉米试验记录随水施肥。',.8,{'source':'shaanxi.txt'}))
    retriever=FakeRetriever(hits)
    model=FakeLLMClient('已提供的试验记载了施肥措施。[1]')
    service=ChatService(retriever,model,top_k=2,max_context_chars=2000,temperature=0)
    trace=[]
    result=await service.answer(query,understanding=parsed,tag_mapping=map_tags(parsed,taxonomy),retrieval_observer=trace.append)
    assert len(retriever.calls)==3  # full query and two separately scoped objects
    assert len(trace[0]['semantic']['routes'])==3
    assert result.outcome==('complete' if both else 'partial')
    assert trace[-1]['object_coverage']['missing']==([] if both else ['陕西'])
    if not both: assert '尚缺陕西' in result.answer


def test_a18_alias_failure_keeps_exact_names_and_marks_degradation(taxonomy,monkeypatch,tmp_path):
    import src.agent.tag_matching as matching
    monkeypatch.setattr(matching,'DEFAULT_ALIASES',tmp_path/'missing.json')
    parsed=parse('找玉米案例',taxonomy)
    mapped=map_tags(parsed,taxonomy)
    assert mapped['status']=='degraded' and mapped['fallback_reason']=='aliases_unavailable'
    assert mapped['mappings'][0]['candidates'][0]['id']=='T-74ce41cce69c'


def test_index_version_change_rebuilds_atomically_and_row_lookup_is_indexed(store):
    item=store.create(CaseInput(title='玉米案例',body='完整正文',enabled=True),'fixture')
    store.search_index.ensure()
    with store.lock,store.db: store.db.execute("UPDATE local_case_meta SET value='older' WHERE key='version'")
    assert store.search_index.ensure()==1
    assert store.db.execute('SELECT count(*) FROM local_case_chunks').fetchone()[0]==1
    plan=list(store.db.execute('EXPLAIN QUERY PLAN SELECT * FROM local_case_fts WHERE rowid IN (SELECT row_id FROM local_case_chunks WHERE material_id=?)',(item['id'],)))
    assert any('local_case_chunks_material' in row[3] for row in plan)
    assert any('VIRTUAL TABLE INDEX' in row[3] and '=' in row[3] for row in plan)
