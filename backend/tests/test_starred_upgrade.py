"""V0.2 coverage and content import, exercised through the normal runtime/API."""
import copy
import json
from types import SimpleNamespace

import pytest

from src.agent.contracts import TaskState
from src.agent.runtime import AgentRuntime
from src.agent.understanding import understand
from src.agent.starred_match import match_starred
from src.api.chat_schema import ChatRequest
from src.evaluation.starred_content import first_batch,import_first_batch
from src.evaluation.store import EvaluationStore
from src.storage.run_store import RunStore
from tests.test_chat_runs import Service
from tests.test_agent_runtime import client as file_client,upload,ask
from src.storage.case_library import CaseStore,CaseInput
from tests.test_case_library import FakeLLM


@pytest.fixture
def content():
    runs=RunStore()
    store=EvaluationStore(runs)
    result=import_first_batch(store,first_batch(),apply=True)
    assert result['applied']
    yield store
    runs.close()


def row(store,sq):
    return next(item for item in store.starred_questions() if item['source_sq_id']==sq)


def parse(query):
    return understand(ChatRequest(query=query),TaskState(conversation_id='test'),SimpleNamespace(run_id='r',turn_id='t'))


def test_a28_batch_counts_ids_repeat_import_and_human_edits_preserved(content):
    questions=content.starred_questions()
    assert len(questions)==25 and sum(bool(q['answer']) for q in questions)==9
    assert len({q['question_id'] for q in questions})==25
    assert all(q['question_id']!=q['source_sq_id'] for q in questions)
    assert all(q['reuse']['professional_review']=='unknown' for q in questions)
    before=copy.deepcopy(questions)
    assert import_first_batch(content,first_batch(),apply=True)['applied']
    assert content.starred_questions()==before
    first=questions[0]
    content.update_starred_question(first['question_id'],first['question'],'人工补充答复',first['revision'])
    import_first_batch(content,first_batch(),apply=True)
    assert content.starred_questions()[0]['answer']=='人工补充答复'
    assert content.starred_questions()[0]['reuse']==first['reuse']


def test_conflicting_existing_record_blocks_batch_without_partial_writes():
    runs=RunStore();store=EvaluationStore(runs)
    try:
        prepared=first_batch()
        store.create_starred_question(prepared[-1]['question'],'已有人维护的不同答案')
        result=import_first_batch(store,prepared,apply=True)
        assert not result['applied'] and result['conflicts']
        assert len(store.starred_questions())==1
        assert store.db.execute('SELECT count(*) FROM eval_starred_sources').fetchone()[0]==0
    finally: runs.close()


@pytest.mark.asyncio
async def test_a21_full_variant_reuse_precedes_and_skips_tag_mapping(content,monkeypatch):
    import src.agent.runtime as module
    calls=[]
    def forbidden(*args):
        calls.append(True)
        raise AssertionError('full coverage must not map tags')
    monkeypatch.setattr(module,'map_tags',forbidden)
    runtime=AgentRuntime();service=Service()
    try:
        result=await runtime.execute(ChatRequest(query='这个课题的预警模型计划扩展哪些能力？'),service=service,get_report=None,starred_provider=content.starred_questions)
        trace=runtime.runs.get(result.run_id)
        assert trace.starred_match['status']=='full' and service.calls==0 and not calls
        assert trace.tag_mapping['status']=='skipped' and trace.tool_calls==[]
        assert trace.answer_assembly['mode']=='starred_only'
        assert result.evidence[0].provenance['professional_review']=='unknown'
        assert row(content,'SQ-008')['answer'] in result.answer
        services=[e['service'] for e in trace.execution_steps if e['type']=='step_started' and 'service' in e]
        assert services==['understanding','starred_match']
        assert trace.execution_plan['tasks']==[] and trace.execution_plan['actual_calls']==[]
    finally: runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('query',[
    '为什么农田与区域尺度采用不同的氮素淋溶模型，两类模型各自如何构建？',
    '为何分尺度以及两类模型如何构建'])
async def test_a23_requirement_inside_single_subtask_continues(content,query):
    class Capturing(Service):
        async def answer(self,query,**kwargs):
            self.query=query
            return await super().answer(query,**kwargs)
    runtime=AgentRuntime();service=Capturing()
    try:
        result=await runtime.execute(ChatRequest(query=query),service=service,get_report=None,starred_provider=content.starred_questions)
        trace=runtime.runs.get(result.run_id)
        assert len(trace.understanding['subtasks'])==1
        assert trace.starred_match['status']=='partial' and len(trace.starred_match['adopted'])==1
        assert trace.answer_assembly['mode']=='starred_plus_continuation'
        assert '如何构建' in service.query and '为什么' not in service.query
        assert service.calls==1 and '固定回答' in result.answer
        assert row(content,'SQ-024')['answer'] in result.answer
        assert trace.starred_match['tasks'][0]['uncovered_aspects']
        assert trace.execution_plan['tasks'][0]['subtask_id']==trace.understanding['subtasks'][0]['subtask_id']
    finally: runtime.runs.close()


@pytest.mark.asyncio
async def test_partial_failure_keeps_reused_answer_and_truthful_outcome(content):
    class Broken(Service):
        async def answer(self,*args,**kwargs): raise RuntimeError('fixture outage')
    runtime=AgentRuntime()
    try:
        result=await runtime.execute(ChatRequest(query='为什么农田与区域尺度采用不同的氮素淋溶模型，两类模型各自如何构建？'),service=Broken(),get_report=None,starred_provider=content.starred_questions)
        assert result.outcome=='partial' and result.warnings
        assert row(content,'SQ-024')['answer'] in result.answer
        trace=runtime.runs.get(result.run_id)
        assert trace.tool_calls[0].status=='error'
        assert trace.starred_match['continuation']['outcome']=='partial'
    finally: runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('sq,status',[('SQ-002','empty_answer'),('SQ-027','conflict')])
async def test_a22_a24_empty_and_conflicting_answers_continue(content,sq,status):
    runtime=AgentRuntime();service=Service()
    try:
        question=row(content,sq)
        result=await runtime.execute(ChatRequest(query=question['question']),service=service,get_report=None,starred_provider=content.starred_questions)
        trace=runtime.runs.get(result.run_id)
        assert trace.starred_match['status']==status
        assert trace.starred_match['adopted']==[] and service.calls==1
        assert '固定回答' in result.answer
    finally: runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,status',[(lambda:[],'empty_library'),(lambda:'invalid','failed'),(None,'unavailable')])
async def test_a26_empty_unavailable_and_bad_provider_are_distinct(provider,status):
    runtime=AgentRuntime();service=Service()
    try:
        result=await runtime.execute(ChatRequest(query='玉米水分与氮迁移有哪些过程？'),service=service,get_report=None,starred_provider=provider)
        trace=runtime.runs.get(result.run_id)
        assert trace.starred_match['status']==status and service.calls==1
        assert '固定回答' in result.answer
    finally: runtime.runs.close()


@pytest.mark.asyncio
async def test_a25_current_assistant_capability_never_reuses_project_plan(content):
    runtime=AgentRuntime();calls=[]
    try:
        def provider(): calls.append(True);return content.starred_questions()
        result=await runtime.execute(ChatRequest(query='当前农业助手能做什么？'),service=None,get_report=None,starred_provider=provider)
        trace=runtime.runs.get(result.run_id)
        assert not calls and trace.starred_match['status']=='not_applicable'
        assert [c.skill for c in trace.tool_calls]==['capability_guidance']
        assert '拟建设决策平台' not in result.answer
    finally: runtime.runs.close()


@pytest.mark.asyncio
async def test_a28_new_answer_new_trace_original_snapshot_unchanged(content):
    runtime=AgentRuntime();query=row(content,'SQ-008')['question']
    try:
        first=await runtime.execute(ChatRequest(query=query),service=None,get_report=None,starred_provider=content.starred_questions)
        original=runtime.runs.get(first.run_id).model_dump()
        question=row(content,'SQ-008')
        updated=content.update_starred_question(question['question_id'],question['question'],'明确更新的有限范围答复。',question['revision'])
        second=await runtime.execute(ChatRequest(query=query),service=None,get_report=None,starred_provider=content.starred_questions)
        assert updated['answer'] in second.answer and updated['answer'] not in first.answer
        assert runtime.runs.get(first.run_id).model_dump()==original
        assert runtime.runs.get(second.run_id).starred_match['adopted'][0]['fingerprint']!=original['starred_match']['adopted'][0]['fingerprint']
    finally: runtime.runs.close()


@pytest.mark.parametrize('query',['WHCNS能模拟地下水全剖面吗？','WHCNS几百米深度可以运行吗？','WHCNS V2.0能模拟哪些过程？','排除玉米，WHCNS主要模拟哪些过程？'])
def test_background_reference_does_not_cover_scope_changes(content,query):
    assert not match_starred(parse(query),content.starred_questions())['adopted']


def test_pending_nonempty_or_placeholder_text_never_counts_as_an_answer():
    parsed=parse('什么是折氮量？')
    for answer,reuse in [('待审核',{}),('有，待审核',{}),('有材料但未核实',{'reuse_status':'pending'}),('两种相反说法',{'reuse_status':'conflict'})]:
        assert match_starred(parsed,[{'question_id':'q','question':'什么是折氮量？','answer':answer,'reuse':reuse}])['adopted']==[]


@pytest.mark.parametrize('query', [
    '怎样通过“数据—模型—应用”实现氮素淋溶智慧管控',
    '如何通过数据—模型—应用实现氮素淋溶智慧管控？',
    '怎么通过"数据-模型-应用"实现氮素淋溶智慧管控？',
    '根据课题材料，怎样通过“数据—模型—应用”实现氮素淋溶智慧管控？',
])
@pytest.mark.asyncio
async def test_project_question_framing_and_typography_reuse_without_retrieval_or_web(content, query):
    class ForbiddenWeb:
        ready = True

        async def search(self, *args, **kwargs):
            raise AssertionError('A fully covered starred question must not search the web')

    runtime = AgentRuntime(web=ForbiddenWeb())
    service = Service()
    try:
        result = await runtime.execute(ChatRequest(query=query), service=service, get_report=None,
            starred_provider=content.starred_questions)
        trace = runtime.runs.get(result.run_id)
        assert trace.starred_match['status'] == 'full'
        assert trace.decision.reason_code == 'starred_full_coverage'
        assert trace.tag_mapping['status'] == 'skipped'
        assert not trace.tool_calls and not trace.web_retrieval and service.calls == 0
        assert result.model == 'maintained-qa-v2'
        assert '材料提出的工作路径' in result.answer
        assert '不表示已有具体方案完成了效果验证' in result.answer
        assert trace.starred_match['tasks'][0]['candidates'][0]['match_method'] == 'normalized_question'
    finally:
        runtime.runs.close()


@pytest.mark.parametrize('query', [
    '当前助手怎样通过“数据—模型—应用”实现氮素淋溶智慧管控？',
    '怎样通过“数据—模型—应用”实现氮素淋溶智慧管控，实际效果如何？',
    '怎样通过“数据—模型—应用”实现玉米氮素淋溶智慧管控？',
    '怎样通过“数据—模型—应用”实现氮素淋溶智慧管控？请联网查找最新论文。',
])
def test_project_framing_normalization_does_not_cover_extra_requirements(content, query):
    match = match_starred(parse(query), content.starred_questions())
    assert match['status'] != 'full'
    assert match['remaining_tasks']


def test_context_prefix_removal_requires_maintained_project_scope():
    question = {'question_id': 'generic', 'question': '课题材料提出怎样组织工作？',
        'answer': '只适用于特定材料的答复。', 'reuse': {'profile': 'general'}}
    assert not match_starred(parse('怎样组织工作？'), [question])['adopted']


def test_different_maintained_answers_are_not_arbitrarily_selected():
    match=match_starred(parse('什么是折氮量？'),[
        {'question_id':'a','question':'什么是折氮量？','answer':'答复甲'},
        {'question_id':'b','question':'什么是折氮量？','answer':'答复乙'}])
    assert match['status']=='conflict' and not match['adopted']


def test_a27_current_file_calculation_uses_cells_not_cached_values(file_client,tmp_path):
    runtime=file_client.app.state.agent_runtime
    store=EvaluationStore(runtime.runs)
    file_client.app.state.evaluation=SimpleNamespace(store=store)
    store.create_starred_question('硝态氮最大值','历史文件最大值为999。')
    token=upload(file_client,tmp_path)
    result=ask(file_client,'硝态氮最大值',file=token).json()
    trace=runtime.runs.get(result['run_id'])
    assert trace.starred_match['status']=='not_applicable'
    assert result['file_evidence'] and all(value['value']!=999 for value in result['file_evidence'])
    assert '历史文件最大值' not in result['answer']
    assert [c.skill for c in trace.tool_calls]==['file_inspector','whcns_analyzer']


def test_a27_compound_query_reuses_only_knowledge_and_still_calculates(file_client,tmp_path):
    runtime=file_client.app.state.agent_runtime
    store=EvaluationStore(runtime.runs)
    file_client.app.state.evaluation=SimpleNamespace(store=store)
    store.create_starred_question('什么是折氮量？','折氮量是把肥料养分换算为氮元素的量。')
    token=upload(file_client,tmp_path)
    response=ask(file_client,'硝态氮最大值；折氮量是什么意思？',file=token)
    assert response.status_code==200,response.text
    result=response.json();trace=runtime.runs.get(result['run_id'])
    assert trace.starred_match['status']=='partial' and result['file_evidence']
    assert '换算为氮元素' in result['answer']
    assert [c.skill for c in trace.tool_calls]==['file_inspector','whcns_analyzer']


@pytest.mark.asyncio
async def test_covered_task_conditions_do_not_leak_into_remaining_work():
    from src.agent.chat_service import ChatService
    from tests.test_chat_service import FakeRetriever,FakeLLMClient
    retriever=FakeRetriever([])
    service=ChatService(retriever,FakeLLMClient('本次只处理小麦。'),top_k=5,max_context_chars=2000,temperature=0)
    questions=[{'question_id':'q','question':'玉米有哪些迁移过程？','answer':'玉米相关维护答复。'}]
    runtime=AgentRuntime()
    try:
        result=await runtime.execute(ChatRequest(query='玉米有哪些迁移过程？；小麦有哪些迁移过程？'),service=service,get_report=None,starred_provider=lambda:questions)
        trace=runtime.runs.get(result.run_id)
        assert trace.starred_match['status']=='partial'
        assert {c['value'] for c in trace.execution_context['conditions']}=={'小麦'}
        assert all(c['canonical']!='玉米' for c in trace.execution_context['concepts'])
        assert '玉米' not in retriever.calls[0][0]
    finally: runtime.runs.close()


@pytest.mark.asyncio
async def test_case_request_still_executes_after_knowledge_reuse(tmp_path):
    runtime=AgentRuntime();cases=CaseStore(str(tmp_path/'cases.sqlite3'))
    item=cases.create(CaseInput(title='玉米滴灌案例',body='本试验采用玉米，记载滴灌措施。',enabled=True),'fixture')
    questions=[{'question_id':'q','question':'什么是折氮量？','answer':'折氮量的维护答复。'}]
    try:
        result=await runtime.execute(ChatRequest(query='折氮量是什么意思？；找玉米案例'),service=None,get_report=None,
            starred_provider=lambda:questions,case_store=cases,llm=FakeLLM([item['id']]))
        trace=runtime.runs.get(result.run_id)
        assert trace.starred_match['status']=='partial'
        assert [call.skill for call in trace.tool_calls]==['case_assistant']
        assert result.case_references[0].id==item['id'] and '折氮量的维护答复' in result.answer
    finally: runtime.runs.close();cases.close()


@pytest.mark.asyncio
async def test_same_qa_covering_two_requirements_has_one_evidence_with_both_tasks(content):
    runtime=AgentRuntime()
    try:
        result=await runtime.execute(ChatRequest(query='WHCNS主要有哪些过程模块？；课题材料为什么选WHCNS作为基础模型？'),
            service=None,get_report=None,starred_provider=content.starred_questions)
        trace=runtime.runs.get(result.run_id)
        assert trace.starred_match['status']=='full' and len(trace.starred_match['adopted'])==2
        assert len(result.evidence)==1 and len(result.evidence[0].subtask_ids)==2
        assert result.answer.count(row(content,'SQ-026')['answer'])==1
    finally: runtime.runs.close()
