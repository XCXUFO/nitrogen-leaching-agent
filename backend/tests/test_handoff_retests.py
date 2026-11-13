import asyncio
import time

import pytest
from fastapi import HTTPException

from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatResponse
from src.evaluation.contracts import Principal
from src.evaluation.handoff import import_package
from src.evaluation.handoff_retests import HandoffRetests, HandoffRetestInput, HandoffJudgment
from tests.test_prd_handoff import SOURCE
from tests.test_evaluation import client, headers  # noqa: F401


@pytest.fixture
def engine(tmp_path):
    source = tmp_path / 'sources.sqlite3'
    import_package(SOURCE, source)
    runtime = AgentRuntime()
    value = HandoffRetests(runtime, source)
    yield value
    runtime.runs.close()


DEV = Principal(tester_id='dev', role='developer')


def save_test_response(engine, query, run_id, config, answer):
    from src.agent.contracts import RunTrace, StateSnapshot
    engine.runtime.runs.append(RunTrace(run_id=run_id, conversation_ref=query.session_id,
        input=query.query, started_at='2026-11-13T00:00:00Z', state_before=StateSnapshot(),
        config_version=engine.runtime.config_version, skill_config={'communication': config['communication']}))
    return ChatResponse(answer=answer, model='simulated', citations=[], retrieved_count=0,
                        usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0})


def body(engine, submission='one', prompt=None):
    return HandoffRetestInput(submission_id=submission, prompt_id=prompt or engine.runtime.runs.prompts.active()['prompt_id'])


def source_id(engine, suffix):
    from src.evaluation.handoff_retests import sources
    return next(r['local_id'] for r in sources(engine.source_database) if r['source']['id'] == suffix)


@pytest.mark.asyncio
async def test_actual_runtime_pins_candidate_without_changing_global(engine):
    active = engine.runtime.runs.prompts.active()
    candidate = engine.runtime.runs.prompts.save('候选', '候选表达规则', 'dev')
    queries = []
    async def execute(query, run_id, config):
        queries.append(query)
        return await engine.runtime.execute(query, service=None, get_report=None, run_id=run_id,
                                            expression_config=config, run_context={'source': 'test', 'mode': 'auto'})
    request = body(engine, prompt=candidate['prompt_id'])
    item = engine.submit(source_id(engine, 'FIX-04'), request, DEV, execute)
    assert engine.submit(source_id(engine, 'FIX-04'), request, DEV, execute)['attempt_id'] == item['attempt_id']
    await engine.tasks[item['attempt_id']]
    result = engine.get(item['attempt_id'])
    assert result['status'] == 'completed' and result['quality'] == 'pending'
    assert len(queries) == 1
    trace = engine.runtime.runs.get(result['steps'][0]['run_id'])
    assert trace.source == 'test'
    assert trace.skill_config['communication']['prompt_id'] == candidate['prompt_id']
    assert engine.runtime.runs.prompts.active() == active
    engine.judge(item['attempt_id'], HandoffJudgment(conclusion='pending', basis='程序文案需另改'), DEV)
    assert engine.get(item['attempt_id'])['source_snapshot']['source']['source_review_status'] == 'needs_changes'
    assert engine.get(item['attempt_id'])['deployment_status'] == 'not_linked'


@pytest.mark.asyncio
async def test_fixed_history_and_multiturn_new_answers(engine):
    # Simulated transport only; these assertions validate execution/context contracts.
    calls = []
    async def execute(query, run_id, config):
        calls.append(query)
        from src.agent.contracts import RunTrace, StateSnapshot
        trace = RunTrace(run_id=run_id, conversation_ref=query.session_id, input=query.query,
            started_at='2026-11-09T00:00:00Z', state_before=StateSnapshot(), config_version=engine.runtime.config_version,
            skill_config={'communication': config['communication']}, status='ok', latency_ms=0)
        engine.runtime.runs.append(trace)
        return ChatResponse(answer=f'本次新回答{len(calls)}', model='simulated', citations=[], retrieved_count=0, usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0})
    fixed = engine.submit(source_id(engine, 'FIX-05'), body(engine), DEV, execute)
    await engine.tasks[fixed['attempt_id']]
    assert len(calls[0].history) == 2
    assert calls[0].query != calls[0].history[0].content
    multi = engine.submit(source_id(engine, 'KEEP-03'), body(engine, 'multi'), DEV, execute)
    await engine.tasks[multi['attempt_id']]
    assert engine.get(multi['attempt_id'])['status'] == 'completed'
    assert [len(q.history) for q in calls[1:]] == [0, 2, 4]
    assert calls[2].history[-1].content == '本次新回答2'
    assert calls[3].history[-1].content == '本次新回答3'
    assert len({s['run_id'] for s in engine.get(multi['attempt_id'])['steps']}) == 3


@pytest.mark.asyncio
async def test_long_multiturn_retests_bound_history_and_retain_full_results(engine, monkeypatch):
    identifier = source_id(engine, 'KEEP-03')
    source = engine.source(identifier)
    source['seed_history'] = [{'role': 'user', 'content': '种' * 4001} for _ in range(14)]
    source['case']['steps'] = [{'action': 'query', 'input': f'第{i}轮农田记录：' + '田' * 4001} for i in range(8)]
    monkeypatch.setattr(engine, 'source', lambda _: source)
    calls = []
    answer = '答' * 4001

    async def execute(query, run_id, config):
        calls.append(query)
        return save_test_response(engine, query, run_id, config, answer)

    item = engine.submit(identifier, body(engine), DEV, execute)
    await engine.tasks[item['attempt_id']]
    result = engine.get(item['attempt_id'])
    assert result['status'] == 'completed' and len(calls) == 8
    assert all(len(query.history) <= 12 and all(len(turn.content) <= 4000 for turn in query.history)
               for query in calls)
    assert calls[1].history[-1].content == answer[:4000]
    assert all(step['response']['answer'] == answer for step in result['steps'])
    assert result['steps'][0]['query'] == source['case']['steps'][0]['input']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['invalid_query', 'build_changed'])
async def test_preparation_failure_preserves_previous_completed_step(engine, monkeypatch, failure):
    identifier = source_id(engine, 'KEEP-03')
    source = engine.source(identifier)
    source['case']['steps'][1]['input'] = '' if failure == 'invalid_query' else '后续问题'
    monkeypatch.setattr(engine, 'source', lambda _: source)
    calls = []

    async def execute(query, run_id, config):
        calls.append(query)
        response = save_test_response(engine, query, run_id, config, '第一轮已完成。')
        if failure == 'build_changed':
            engine.runtime.config_version = 'changed-build'
        return response

    item = engine.submit(identifier, body(engine), DEV, execute)
    await engine.tasks[item['attempt_id']]
    result = engine.get(item['attempt_id'])
    assert result['status'] == 'failed' and len(calls) == 1
    assert result['steps'][0]['status'] == 'completed'
    assert result['steps'][0]['response']['answer'] == '第一轮已完成。'
    if failure == 'invalid_query':
        assert result['steps'][1]['status'] == 'failed'


@pytest.mark.asyncio
async def test_failure_and_interruption_never_qualify_or_replay(engine):
    async def failing(*args):
        raise HTTPException(503, detail={'code': 'rag_not_configured'})
    item = engine.submit(source_id(engine, 'FIX-02'), body(engine), DEV, failing)
    await engine.tasks[item['attempt_id']]
    assert engine.get(item['attempt_id'])['status'] == 'failed'
    with pytest.raises(HTTPException):
        engine.judge(item['attempt_id'], HandoffJudgment(conclusion='pass', basis='test'), DEV)
    started = asyncio.Event()
    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()
    item = engine.submit(source_id(engine, 'FIX-05'), body(engine, 'blocked'), DEV, blocked)
    await started.wait()
    await engine.shutdown()
    assert engine.get(item['attempt_id'])['status'] == 'interrupted'
    same = engine.submit(source_id(engine, 'FIX-05'), body(engine, 'blocked'), DEV, blocked)
    assert same['status'] == 'interrupted'
    assert not engine.tasks


def test_api_developer_permission_and_full_pipeline(client, monkeypatch, tmp_path):
    from src.api.evaluation import settings
    source = tmp_path / 'sources.sqlite3'
    import_package(SOURCE, source)
    monkeypatch.setattr(settings, 'eval_handoff_db', str(source))
    assert client.get('/api/eval/handoff-sources').status_code == 401
    assert client.get('/api/eval/handoff-sources', headers=headers('alice')).status_code == 403
    items = client.get('/api/eval/handoff-sources', headers=headers('dev')).json()
    assert len(items) == 8
    item = next(r for r in items if r['source']['id'] == 'FIX-04')
    url = '/api/eval/handoff-sources/' + item['local_id']
    runtime = client.app.state.agent_runtime
    prompt = runtime.runs.prompts.active()['prompt_id']
    payload = {'submission_id': 'api', 'prompt_id': prompt}
    assert client.post(url + '/retests', headers=headers('alice'), json=payload).status_code == 403
    result = client.post(url + '/retests', headers=headers('dev'), json=payload)
    assert result.status_code == 202, result.text
    for _ in range(100):
        detail = client.get(url, headers=headers('dev')).json()
        if detail['attempts'][0]['status'] not in {'queued', 'running'}:
            break
        time.sleep(.01)
    assert detail['attempts'][0]['status'] == 'completed'
    assert detail['attempts'][0]['quality'] == 'pending'
    assert client.post(url + '/retests', headers=headers('dev'), json=payload).json()['attempt_id'] == result.json()['attempt_id']
    assert len(client.get(url, headers=headers('dev')).json()['attempts']) == 1


@pytest.mark.asyncio
async def test_concurrent_candidates_reach_model_and_normal_requests_keep_active(engine):
    from src.agent.chat_service import ChatService
    from src.api.chat_schema import ChatRequest
    from tests.test_chat_service import FakeRetriever, FakeLLMClient, _result
    class RecordingModel(FakeLLMClient):
        def __init__(self):
            super().__init__('模拟回答 [1]')
            self.systems = []
        async def chat(self, messages, **kwargs):
            await asyncio.sleep(0)
            self.systems.append(messages[0].content)
            return await super().chat(messages, **kwargs)
    llm = RecordingModel()
    service = ChatService(FakeRetriever([_result(1, '菜地N2O排放规律与施肥、土壤水分条件有关，需区分不同研究场景。')]), llm,
                          top_k=5, max_context_chars=3000, temperature=0)
    active = engine.runtime.runs.prompts.active()
    prompts = [engine.runtime.runs.prompts.save(f'候选{i}', f'隔离表达规则{i}', 'dev') for i in range(2)]
    async def execute(query, run_id, config):
        return await engine.runtime.execute(query, service=service, get_report=None, run_id=run_id,
            expression_config=config, run_context={'source': 'test', 'mode': 'auto'})
    items = [engine.submit(source_id(engine, 'FIX-01'), body(engine, f'parallel{i}', p['prompt_id']), DEV, execute) for i, p in enumerate(prompts)]
    await asyncio.gather(*(engine.tasks[item['attempt_id']] for item in items),
                         engine.runtime.execute(ChatRequest(query='菜地N2O排放规律', session_id='normal'), service=service, get_report=None))
    assert len(llm.systems) == 3
    for p in prompts:
        assert sum(p['text'] in system for system in llm.systems) == 1
    assert sum(active['text'] in system for system in llm.systems) == 1
    assert engine.runtime.runs.prompts.active() == active
    assert all(engine.get(item['attempt_id'])['status'] == 'completed' for item in items)


@pytest.mark.asyncio
async def test_cancel_before_start_and_restart_do_not_replay(engine):
    calls = []
    async def execute(*args):
        calls.append(args)
        raise AssertionError('must not execute')
    item = engine.submit(source_id(engine, 'FIX-05'), body(engine, 'cancel-early'), DEV, execute)
    await engine.shutdown()
    assert engine.get(item['attempt_id'])['status'] == 'interrupted'
    reopened = HandoffRetests(engine.runtime, engine.source_database)
    result = reopened.submit(source_id(engine, 'FIX-05'), body(engine, 'cancel-early'), DEV, execute)
    assert result['status'] == 'interrupted' and not reopened.tasks and not calls
