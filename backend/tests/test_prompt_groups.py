import asyncio
import json
import sqlite3
import time
from threading import Event, Thread

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.agent.runtime import AgentRuntime
from src.agent.chat_service import ChatService
from src.agent.task_prompts import TaskPromptInput
from src.evaluation.contracts import Principal
from src.evaluation.explanation_trials import ExplanationTrials, TrialInput, TrialGroups, evidence_fingerprint
from src.storage.prompt_groups import PromptGroupInput, PromptGroups
from src.storage.run_store import RunStore
from tests.test_chat_service import FakeLLMClient, FakeRetriever, _result
from tests.test_evaluation import client, headers  # noqa: F401


DEV = Principal(tester_id='dev', role='developer')
EXAMPLE = dict(source_case='verified-case', source_revision='1', review_scope='概念解释方式', confirmed=True,
               query='示范概念是什么？', answer='示范答案，仅作表达示范。')


def save_group(trials, label, task=None, prompt=None):
    tasks = trials.runtime.runs.task_prompts.active()
    if task:
        tasks[task['scope']] = task
    return trials.groups.save(PromptGroupInput(label=label,
        prompt_id=(prompt or trials.runtime.runs.prompts.active())['prompt_id'],
        task_prompt_ids={scope: p['prompt_id'] for scope, p in tasks.items()}), 'dev')


def test_complete_groups_pin_versions_examples_and_survive_restart(tmp_path):
    path = tmp_path / 'runs.sqlite3'
    runtime = AgentRuntime(runs=RunStore(path))
    trials = ExplanationTrials(runtime)
    active = runtime.expression_snapshot()
    task = runtime.runs.task_prompts.save(TaskPromptInput(scope='concept_explanation', label='few-shot',
        text='相同规则', examples=[EXAMPLE]), 'dev')
    group = save_group(trials, '示例组', task)
    assert group['task_prompts']['concept_explanation']['examples'] == [EXAMPLE]
    runtime.runs.task_prompts.activate('concept_explanation', task['prompt_id'], 'dev')
    assert trials.groups.get(group['group_id']) == group
    assert active['communication'] == runtime.runs.prompts.active()
    with pytest.raises(ValidationError):
        PromptGroupInput(label='不完整', prompt_id=group['communication']['prompt_id'], task_prompt_ids={})
    ids = {scope: p['prompt_id'] for scope, p in group['task_prompts'].items()}
    ids['case_assistant'] = task['prompt_id']
    with pytest.raises(HTTPException) as error:
        trials.groups.save(PromptGroupInput(label='错配', prompt_id=group['communication']['prompt_id'], task_prompt_ids=ids), 'dev')
    assert error.value.status_code == 422
    runtime.runs.close()
    reopened = RunStore(path)
    assert PromptGroups(reopened).get(group['group_id']) == group
    reopened.close()


def test_group_activation_switches_all_versions_and_survives_restart(tmp_path):
    path = tmp_path / 'active-group.sqlite3'
    runtime = AgentRuntime(runs=RunStore(path))
    trials = ExplanationTrials(runtime)
    original = trials.groups.active()
    communication = runtime.runs.prompts.save('新的全局', '新的表达', 'dev')
    task = runtime.runs.task_prompts.save(TaskPromptInput(scope='concept_explanation', label='新任务',
        text='新的规则', examples=[EXAMPLE]), 'dev')
    group = save_group(trials, '选中的方案', task, communication)
    assert trials.groups.active() == original
    result = trials.groups.activate(group['group_id'], 'dev')
    assert result['group'] == group
    assert result['activated_by'] == 'dev'
    assert result['activated_at']
    snapshot = runtime.expression_snapshot()
    assert snapshot['communication']['prompt_id'] == communication['prompt_id']
    assert snapshot['task_prompts'] == group['task_prompts']
    # Single-version activation must not leave a misleading current scheme label.
    runtime.runs.prompts.activate(original['communication']['prompt_id'], 'dev')
    assert trials.groups.active()['group'] is None
    result = trials.groups.activate(group['group_id'], 'dev')
    runtime.runs.close()
    reopened = RunStore(path)
    assert PromptGroups(reopened).active() == result
    reopened.close()


def test_request_snapshot_cannot_mix_preferences_and_prompts_during_restore(monkeypatch):
    runtime = AgentRuntime()
    original = runtime.expression_snapshot()
    candidate = runtime.runs.prompts.save('恢复目标', '恢复后的表达规则', 'dev')
    preferences_read, writer_finished = Event(), Event()
    current = runtime.runs.skill_config.current
    prompts = runtime.runs.active_prompt_snapshot
    errors = []

    def read_preferences():
        result = current()
        preferences_read.set()
        return result

    def read_prompts():
        # Give the concurrent restore a chance to commit between the two reads.
        # An atomic snapshot keeps it waiting until both reads have completed.
        writer_finished.wait(.2)
        return prompts()

    def restore():
        try:
            assert preferences_read.wait(2)
            with runtime.runs._lock:
                runtime.runs.skill_config.update(expected_revision=0, values={'style': 'professional'}, actor='dev')
                runtime.runs.prompts.activate(candidate['prompt_id'], 'dev')
        except BaseException as exc:
            errors.append(exc)
        finally:
            writer_finished.set()

    monkeypatch.setattr(runtime.runs.skill_config, 'current', read_preferences)
    monkeypatch.setattr(runtime.runs, 'active_prompt_snapshot', read_prompts)
    thread = Thread(target=restore)
    thread.start()
    try:
        snapshot = runtime.expression_snapshot()
        thread.join(2)
        assert not thread.is_alive() and not errors
        assert snapshot['revision'] == original['revision']
        assert snapshot['communication'] == original['communication']
        assert runtime.expression_snapshot()['communication']['prompt_id'] == candidate['prompt_id']
        assert runtime.expression_snapshot()['revision'] == 1
    finally:
        thread.join(2)
        runtime.runs.close()


def test_failed_group_activation_rolls_back_every_pointer_and_audit():
    runtime = AgentRuntime()
    trials = ExplanationTrials(runtime)
    communication = runtime.runs.prompts.save('新全局', '表达', 'dev')
    task = runtime.runs.task_prompts.save(TaskPromptInput(scope='concept_explanation', label='新任务', text='规则'), 'dev')
    group = save_group(trials, '待启用', task, communication)
    original = trials.groups.active()
    db = runtime.runs._connection
    # Fail after the communication pointer and first task have already changed.
    db.execute("""CREATE TRIGGER reject_group_update BEFORE INSERT ON active_task_prompts
        WHEN NEW.scope='knowledge_search' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        trials.groups.activate(group['group_id'], 'dev')
    assert trials.groups.active() == original
    assert db.execute('SELECT count(*) FROM task_prompt_activations').fetchone()[0] == 0
    db.execute('DROP TRIGGER reject_group_update')
    # An unavailable group version is rejected before changing any pointers.
    corrupted = {**group, 'communication': {**group['communication'], 'prompt_id': 'missing'}}
    with db:
        db.execute('UPDATE prompt_groups SET payload=? WHERE group_id=?', (json.dumps(corrupted), group['group_id']))
    with pytest.raises(HTTPException) as error:
        trials.groups.activate(group['group_id'], 'dev')
    assert error.value.status_code == 404
    assert trials.groups.active() == original
    runtime.runs.close()


def test_group_activation_api_permissions_and_unknown_group(client):
    from src.api import explanation_trials
    client.app.include_router(explanation_trials.router, prefix='/api')
    endpoint = '/api/eval/active-prompt-group'
    assert client.get(endpoint).status_code == 401
    assert client.get(endpoint, headers=headers('alice')).status_code == 200
    groups = client.get('/api/eval/prompt-groups', headers=headers('dev')).json()
    body = {'group_id': groups[0]['group_id']}
    assert client.put(endpoint, json=body).status_code == 401
    for user in ('alice', 'expert'):
        assert client.put(endpoint, headers=headers(user), json=body).status_code == 403
    original = client.get(endpoint, headers=headers('dev')).json()
    assert client.put(endpoint, headers=headers('dev'), json={'group_id': 'missing'}).status_code == 404
    assert client.get(endpoint, headers=headers('dev')).json() == original
    response = client.put(endpoint, headers=headers('dev'), json=body)
    assert response.status_code == 200
    assert response.json()['group'] == groups[0]
    assert client.get('/api/eval/active-prompt', headers=headers('dev')).json()['prompt_id'] == groups[0]['communication']['prompt_id']
    assert client.get('/api/eval/task-prompts', headers=headers('dev')).json()['active'] == groups[0]['task_prompts']


@pytest.mark.asyncio
async def test_zero_and_few_shot_reach_real_tasks_with_isolated_multiturn_history_and_no_activation():
    runtime = AgentRuntime()
    trials = ExplanationTrials(runtime)
    original = runtime.expression_snapshot()
    rule = '只测试示例的变化，任务规则不变。'
    zero = runtime.runs.task_prompts.save(TaskPromptInput(scope='concept_explanation', label='zero', text=rule), 'dev')
    few = runtime.runs.task_prompts.save(TaskPromptInput(scope='concept_explanation', label='few', text=rule, examples=[EXAMPLE]), 'dev')
    left, right = save_group(trials, '零示例组', zero), save_group(trials, '带示例组', few)
    calls = []
    model = FakeLLMClient()

    async def execute(query, record, observer, config):
        model._content = '右侧的新回答' if config['task_prompts']['concept_explanation']['examples'] else '左侧的新回答'
        calls.append((query, config))
        return await runtime.execute(query, service=None, get_report=None, llm=model, run_id=record['run_id'],
            observer=observer, expression_config=config,
            run_context={k: record[k] for k in ('source', 'mode', 'turn_id', 'request_id', 'primary_run_id', 'rerun_of_run_id')})

    body = TrialInput(submission_id='groups', query='硝化作用是什么意思', followups=['解释下光合作用'],
        groups=TrialGroups(baseline=left['group_id'], candidate=right['group_id']))
    first = trials.submit(body, DEV, llm=model, execute=execute)
    assert trials.submit(body, DEV, llm=model, execute=execute)['trial_id'] == first['trial_id']
    # Changing the active pointer after admission must not affect either group.
    runtime.runs.task_prompts.activate('concept_explanation', few['prompt_id'], 'dev')
    await trials.tasks[first['trial_id']]
    result = trials.get(first['trial_id'], DEV)
    assert result['status'] == 'completed', result
    assert len(calls) == 4
    assert [len(q.history) for q, _ in calls] == [0, 2, 0, 2]
    assert '左侧的新回答' in calls[1][0].history[-1].content
    assert '右侧的新回答' in calls[3][0].history[-1].content
    assert calls[0][0].session_id != calls[2][0].session_id
    assert '示范答案' in model.last_messages[0].content
    assert rule in model.last_messages[0].content
    for variant, count in [('baseline', 0), ('candidate', 1)]:
        v = result['variants'][variant]
        assert v['status'] == 'succeeded' and len(v['steps']) == 2
        assert v['unused_task_scopes'] == ['knowledge_search', 'case_assistant']
        for step in v['steps']:
            assert step['task_prompt_usage'][0]['example_count'] == count
            assert step['task_prompt_usage'][0]['shot_mode'] == ('few-shot' if count else 'zero-shot')
            assert runtime.runs.get(step['run_id']).source == 'test'
    assert runtime.runs.prompts.active() == original['communication']
    assert trials.submit(body, DEV, llm=model, execute=execute)['trial_id'] == first['trial_id']
    assert len(calls) == 4
    with pytest.raises(HTTPException) as conflict:
        trials.submit(body.model_copy(update={'material': 'changed'}), DEV, llm=model, execute=execute)
    assert conflict.value.status_code == 409
    await trials.shutdown()
    runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('difference', [None, 'text', 'version'])
async def test_group_evidence_comparison_ignores_retrieval_ids_but_detects_source_changes(difference):
    runtime = AgentRuntime()
    trials = ExplanationTrials(runtime)
    group = trials.groups.list()[0]
    model = FakeLLMClient('文献介绍了氮素迁移。[1]')
    hit = _result(1, '土壤中的硝态氮随水迁移，灌溉和降雨影响其淋失。')
    hit.metadata['content_key'] = 'original-version'
    retriever = FakeRetriever([hit])
    service = ChatService(retriever, model, top_k=5, max_context_chars=4000, temperature=0)
    calls = []

    async def execute(query, record, observer, config):
        if calls:
            if difference == 'text':
                updated = _result(1, '土壤中的氮素迁移还受到土壤性质和作物吸收的影响。')
                updated.metadata.update(hit.metadata)
                retriever._results = [updated]
            elif difference == 'version':
                hit.metadata['content_key'] = 'updated-version'
        calls.append(query)
        return await runtime.execute(query, service=service, get_report=None, llm=model,
            run_id=record['run_id'], observer=observer, expression_config=config,
            run_context={key: record[key] for key in ('source', 'mode', 'turn_id', 'request_id',
                                                    'primary_run_id', 'rerun_of_run_id')})

    try:
        item = trials.submit(TrialInput(submission_id='evidence', query='土壤氮素迁移有哪些文献依据？',
            groups=TrialGroups(baseline=group['group_id'], candidate=group['group_id'])),
            DEV, llm=model, execute=execute)
        await trials.tasks[item['trial_id']]
        result = trials.get(item['trial_id'], DEV)
        assert result['status'] == 'completed'
        left, right = [result['variants'][variant]['steps'][0] for variant in ('baseline', 'candidate')]
        assert left['response']['citations'][0]['retrieval_ids'] != right['response']['citations'][0]['retrieval_ids']
        assert (left['evidence_fingerprint'] == right['evidence_fingerprint']) == (difference is None)
    finally:
        await trials.shutdown()
        runtime.runs.close()


def test_case_evidence_comparison_ignores_execution_ids_and_detects_content_updates():
    from types import SimpleNamespace

    trace = SimpleNamespace(case_context={'displayed_case_ids': ['case-one']}, retrieval=[{
        'source_type': 'case', 'candidates': [{'id': 'case-one', 'selected': True,
            'revision': 1, 'fingerprint': 'original-body'}]}])
    response = {'case_references': [{'id': 'case-one', 'title': '示例案例', 'source': '',
                                    'retrieval_ids': ['first-execution']}]}
    original = evidence_fingerprint(response, trace)
    response['case_references'][0]['retrieval_ids'] = ['second-execution']
    assert evidence_fingerprint(response, trace) == original
    trace.retrieval[0]['candidates'][0].update(revision=2, fingerprint='updated-body')
    assert evidence_fingerprint(response, trace) != original


@pytest.mark.asyncio
async def test_one_group_failure_does_not_hide_other_group_and_interruption_never_replays():
    runtime = AgentRuntime()
    trials = ExplanationTrials(runtime)
    group = trials.groups.list()[0]
    body = TrialInput(submission_id='failure', query='硝化作用是什么意思',
        groups=TrialGroups(baseline=group['group_id'], candidate=group['group_id']))
    calls = 0

    async def execute(query, record, observer, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPException(503, detail={'code': 'llm_unreachable'})
        return await runtime.execute(query, service=None, get_report=None, llm=FakeLLMClient('解释'),
            run_id=record['run_id'], expression_config=config)

    item = trials.submit(body, DEV, llm=True, execute=execute)
    await trials.tasks[item['trial_id']]
    result = trials.get(item['trial_id'], DEV)
    assert result['status'] == 'failed'
    assert result['variants']['baseline']['status'] == 'failed'
    assert result['variants']['candidate']['status'] == 'succeeded'
    started = asyncio.Event()

    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()

    body = body.model_copy(update={'submission_id': 'interrupted'})
    item = trials.submit(body, DEV, llm=True, execute=blocked)
    await started.wait()
    await trials.shutdown()
    assert trials.get(item['trial_id'], DEV)['status'] == 'interrupted'
    assert trials.submit(body, DEV, llm=True, execute=blocked)['status'] == 'interrupted'
    assert not trials.tasks
    runtime.runs.close()


def test_group_api_permissions_validation_and_normal_execution(client):
    from src.api import explanation_trials
    client.app.include_router(explanation_trials.router, prefix='/api')
    endpoint = '/api/eval/prompt-groups'
    assert client.get(endpoint).status_code == 401
    original = client.get(endpoint, headers=headers('dev')).json()[0]
    payload = {'label': 'API组合', 'prompt_id': original['communication']['prompt_id'],
        'task_prompt_ids': {scope: p['prompt_id'] for scope, p in original['task_prompts'].items()}}
    assert client.post(endpoint, headers=headers('alice'), json=payload).status_code == 403
    assert client.get(endpoint, headers=headers('expert')).status_code == 200
    assert client.post(endpoint, headers=headers('dev'), json={**payload, 'task_prompt_ids': {}}).status_code == 422
    group = client.post(endpoint, headers=headers('dev'), json=payload)
    assert group.status_code == 201
    assert client.app.state.agent_runtime.runs.prompts.active()['prompt_id'] == payload['prompt_id']
    client.app.state.llm = FakeLLMClient('这是新回答。')
    request = {'submission_id': 'api-group', 'query': '硝化作用是什么意思',
        'groups': {'baseline': original['group_id'], 'candidate': group.json()['group_id']}}
    result = client.post('/api/eval/explanation-trials', headers=headers('dev'), json=request)
    assert result.status_code == 202, result.text
    for _ in range(100):
        saved = client.get('/api/eval/explanation-trials/' + result.json()['trial_id'], headers=headers('dev')).json()
        if saved['status'] not in {'accepted', 'running'}:
            break
        time.sleep(.01)
    assert saved['status'] == 'completed', saved
    assert saved['variants']['baseline']['steps'][0]['task_prompt_usage'][0]['shot_mode'] == 'zero-shot'
    assert client.post('/api/eval/explanation-trials', headers=headers('dev'), json=request).json()['trial_id'] == saved['trial_id']
