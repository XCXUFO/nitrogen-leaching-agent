from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest

from tests.test_evaluation import client, headers
from src.evaluation.conversation_cases import ConversationCases


def post(client, path, body, user='expert', status=201):
    response = client.post('/api/eval' + path, headers=headers(user), json=body)
    assert response.status_code == status, response.text
    return response.json()


def conversation(client, *, attached=False):
    identifier = 'source_' + uuid4().hex
    history = []
    for question in ['你好', '你能做什么？']:
        response = client.post('/api/chat', headers=headers('alice'), json={'query': question, 'session_id': identifier, 'history': history})
        assert response.status_code == 200, response.text
        result = response.json()
        history += [{'role': 'user', 'content': question}, {'role': 'assistant', 'content': result['answer']}]
    return client.app.state.agent_runtime.runs.session(result['run_id'])


def setup_case(client, expected='两轮均完整回答，不丢失上下文。'):
    session = conversation(client)
    group = post(client, '/case-groups', {'title': '固定回归组'})
    case = post(client, f"/case-groups/{group['group_id']}/cases", {'session_id': session['session_id'], 'expected': expected})
    return session, group, case


def start(client, group, **overrides):
    return post(client, '/conversation-batches', {'submission_id': uuid4().hex, 'group_ids': [group['group_id']], 'version_name': 'v0.4.1', **overrides}, status=202)


def wait(client, batch):
    for _ in range(100):
        result = client.get('/api/eval/conversation-batches/' + batch['batch_id'], headers=headers()).json()
        if result['status'] not in {'queued', 'running'}:
            return result
        time.sleep(.02)
    pytest.fail('batch did not finish')


def judge(client, batch, case, conclusion='pass'):
    return post(client, f"/conversation-batches/{batch['batch_id']}/cases/{case['case_id']}/judgments", {'conclusion': conclusion, 'note': '核对两轮回答及预期，符合要求。'}, status=200)


def test_capture_whole_conversation_deduplicates_and_freezes(client):
    session, group, case = setup_case(client)
    assert len(case['turns']) == 2
    assert case['turns'][1]['baseline_answer'] == session['turns'][1]['answer']
    other = post(client, '/case-groups', {'title': '另一个组'})
    duplicate = post(client, f"/case-groups/{other['group_id']}/cases", {'session_id': session['turns'][0]['run_id']})
    assert duplicate['case_id'] == case['case_id']
    assert len(client.app.state.agent_runtime.runs.conversation_cases.memberships(session['session_id'])) == 2
    snapshot = json.dumps(case['turns'], sort_keys=True)
    # Editing standards does not mutate conversation input or baseline answers.
    response = client.put('/api/eval/conversation-cases/' + case['case_id'], headers=headers('expert'), json={
        'title': '新的标题', 'expected': '新的标准', 'notes': '说明', 'expected_revision': 1})
    assert response.status_code == 200
    assert json.dumps(response.json()['turns'], sort_keys=True) == snapshot
    assert client.put('/api/eval/conversation-cases/' + case['case_id'], headers=headers('expert'), json={
        'title': '覆盖', 'expected': '', 'expected_revision': 1}).status_code == 409


def test_replay_uses_fresh_answers_isolates_session_and_needs_human_acceptance(client, monkeypatch):
    session, group, case = setup_case(client)
    import src.api.conversation_evaluation as api
    original = api.execute_chat
    requests = []
    async def execute(request, body, runtime, **options):
        requests.append(body.model_dump())
        return await original(request, body, runtime, **options)
    monkeypatch.setattr(api, 'execute_chat', execute)
    batch = wait(client, start(client, group))
    assert batch['status'] == 'completed' and batch['acceptance'] == 'pending'
    assert batch['case_count'] == batch['completed_cases'] == 1
    assert batch['results'][0]['status'] == 'succeeded'
    assert len(requests) == 2 and requests[0]['history'] == []
    assert requests[1]['history'][-1]['content'] == batch['results'][0]['turns'][0]['response']['answer'][:4000]
    assert requests[0]['session_id'] != session['session_id']
    assert len(client.app.state.agent_runtime.runs.session(session['session_id'])['turns']) == 2
    assert judge(client, batch, case)['acceptance'] == 'pass'
    second = wait(client, start(client, group))
    versions = client.get('/api/eval/conversation-cases/' + case['case_id'], headers=headers()).json()['versions']
    assert {v['batch_id'] for v in versions} == {batch['batch_id'], second['batch_id']}


def test_frozen_standard_memberships_and_idempotent_submission(client):
    _, group, case = setup_case(client)
    batch = wait(client, start(client, group, submission_id='stable'))
    assert start(client, group, submission_id='stable')['batch_id'] == batch['batch_id']
    response = client.put('/api/eval/conversation-cases/' + case['case_id'], headers=headers('expert'), json={
        'title': case['title'], 'expected': '后来修改的标准', 'expected_revision': 1})
    assert response.status_code == 200
    assert client.delete(f"/api/eval/case-groups/{group['group_id']}/cases/{case['case_id']}", headers=headers('expert')).status_code == 200
    frozen = client.get('/api/eval/conversation-batches/' + batch['batch_id'], headers=headers()).json()
    assert frozen['cases'][0]['expected'] == case['expected']
    assert len(frozen['cases'][0]['turns']) == 2
    assert client.post('/api/eval/conversation-batches', headers=headers('expert'), json={
        'submission_id': 'stable', 'group_ids': [group['group_id']], 'version_name': 'another'}).status_code == 409


def test_no_standard_cannot_be_accepted_and_interrupted_batches_are_durable(client):
    _, group, case = setup_case(client, expected='')
    batch = wait(client, start(client, group))
    response = client.post(f"/api/eval/conversation-batches/{batch['batch_id']}/cases/{case['case_id']}/judgments", headers=headers('expert'), json={'conclusion': 'pass', 'note': '完成'})
    assert response.status_code == 422
    store = client.app.state.agent_runtime.runs.conversation_cases
    frozen = store.batch(batch['batch_id'])
    frozen['status'] = 'running'
    frozen['results'][0]['status'] = 'running'
    frozen['results'][0]['turns'][-1]['status'] = 'running'
    store._save_batch(frozen)
    restored = ConversationCases(store.runs).batch(batch['batch_id'])
    assert restored['status'] == 'interrupted' and restored['acceptance'] == 'blocked'
    assert restored['results'][0]['status'] == 'interrupted'
    assert [turn['status'] for turn in restored['results'][0]['turns']] == ['succeeded', 'interrupted']


def test_missing_attachment_blocks_instead_of_silently_omitting(client):
    _, group, case = setup_case(client)
    store = client.app.state.agent_runtime.runs.conversation_cases
    case['turns'][0].update(has_attachments=True, attachments=[{'filename': 'missing.txt', 'sha256': '0'*64}])
    with store.lock, store.db:
        store._write('conversation_cases', case['case_id'], case)
    batch = wait(client, start(client, group))
    assert batch['results'][0]['status'] == 'blocked' and batch['acceptance'] == 'blocked'
    assert batch['results'][0]['turns'] == []


@pytest.mark.parametrize('mode', ['single', 'multiple'])
def test_replay_restores_archived_attachments_and_releases_new_leases(client, mode):
    raw = '作物：玉米\n测试记录：灌溉100 mm'.encode()
    receipt = client.post('/api/files', params={'filename': '田间记录.txt', 'session_id': 'file-source'}, content=raw).json()
    attached = {'file_id': receipt['file_id']} if mode == 'single' else {'file_ids': [receipt['file_id']]}
    history = []
    for _ in range(2):
        response = client.post('/api/chat', json={'query': '你能做什么？', 'session_id': 'file-source', 'history': history, **attached})
        assert response.status_code == 200, response.text
        history += [{'role': 'user', 'content': '你能做什么？'}, {'role': 'assistant', 'content': response.json()['answer']}]
    group = post(client, '/case-groups', {'title': '附件组'})
    case = post(client, f"/case-groups/{group['group_id']}/cases", {'session_id': 'file-source', 'expected': '两轮附件均恢复。'})
    assert all(t['file_mode'] == mode for t in case['turns'])
    client.post('/api/files/release', json={'session_id': 'file-source', 'file_ids': [receipt['file_id']]})
    assert not client.app.state.file_store.entries
    batch = wait(client, start(client, group))
    assert batch['results'][0]['status'] == 'succeeded', batch
    runs = client.app.state.agent_runtime.runs
    replay = runs.session(batch['results'][0]['session_id'])
    assert all(t['request_snapshot']['attachments'][0]['sha256'] == receipt['sha256'] for t in replay['turns'])
    assert all(t['request_snapshot']['file_mode'] == mode for t in replay['turns'])
    assert not client.app.state.file_store.entries
    assert runs.attachments.get(receipt['sha256']) == raw


def test_multiple_groups_deduplicate_conversations(client):
    session, group, case = setup_case(client)
    other = post(client, '/case-groups', {'title': '第二个组'})
    post(client, f"/case-groups/{other['group_id']}/cases", {'session_id': session['session_id']})
    batch = wait(client, start(client, group, group_ids=[group['group_id'], other['group_id']]))
    assert batch['case_count'] == 1 and len(batch['results'][0]['turns']) == 2
    single = post(client, '/conversation-batches', {'submission_id': uuid4().hex, 'case_ids': [case['case_id']], 'version_name': '单会话复测'}, status=202)
    assert len(wait(client, single)['results'][0]['turns']) == 2


def test_cancel_never_approves_or_restarts_automatically(client, monkeypatch):
    import asyncio
    import src.api.conversation_evaluation as api
    _, group, case = setup_case(client)
    async def slow(*args, **kwargs):
        await asyncio.sleep(30)
    monkeypatch.setattr(api, 'execute_chat', slow)
    batch = start(client, group)
    for _ in range(100):
        current = client.get('/api/eval/conversation-batches/' + batch['batch_id'], headers=headers()).json()
        if current['results'] and current['results'][0]['turns']:
            break
        time.sleep(.01)
    else:
        pytest.fail('replay did not reach its first turn')
    assert client.post('/api/eval/conversation-batches/' + batch['batch_id'] + '/cancel', headers=headers('expert')).status_code == 200
    cancelled = wait(client, batch)
    assert cancelled['status'] == 'cancelled' and cancelled['acceptance'] == 'blocked'
    assert cancelled['results'][0]['turns'][0]['status'] == 'interrupted'


def test_feedback_ownership_deduplication_and_shared_issue_lifecycle(client):
    session, group, case = setup_case(client)
    payload = {'run_id': session['turns'][0]['run_id'], 'note': '这里希望补充边界条件。', 'submission_id': 'feedback-1'}
    wrong = client.post('/api/chat/feedback', headers=headers('bob'), json=payload)
    assert wrong.status_code == 404
    assert client.post('/api/chat/feedback', json=payload).status_code == 401
    response = client.post('/api/chat/feedback', headers=headers('alice'), json=payload)
    assert response.status_code == 201, response.text
    issue_id = response.json()['issue_id']
    assert client.post('/api/chat/feedback', headers=headers('alice'), json=payload).json()['issue_id'] == issue_id
    queue = client.get('/api/eval/conversation-issues', headers=headers()).json()
    assert len(queue) == 1 and queue[0]['source'] == 'feedback' and queue[0]['cases'][0]['case_id'] == case['case_id']
    update = {'status': 'closed', 'category': '边界', 'assignee': 'dev', 'note': '已核对', 'expected_revision': 1}
    assert client.put('/api/eval/conversation-issues/' + issue_id, headers=headers('expert'), json=update).status_code == 422
    batch = wait(client, start(client, group))
    update['verification_batch_id'] = batch['batch_id']
    assert client.put('/api/eval/conversation-issues/' + issue_id, headers=headers('expert'), json=update).status_code == 422
    judge(client, batch, case)
    response = client.put('/api/eval/conversation-issues/' + issue_id, headers=headers('expert'), json=update)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'closed'
    assert client.app.state.agent_runtime.runs.session(session['session_id'])['review']['issues'][0]['status'] == 'resolved'


@pytest.mark.parametrize('user', ['alice', 'bob'])
def test_ordinary_accounts_only_read_workbench_but_can_chat_and_feedback(client, user):
    _, group, case = setup_case(client)
    for path in ['/case-groups', '/conversation-batches', '/conversation-issues', '/skills/case_explanation/configuration/reset', '/executions', '/starred-questions']:
        assert client.post('/api/eval' + path, headers=headers(user), json={}).status_code == 403, path
    assert client.delete(f"/api/eval/case-groups/{group['group_id']}/cases/{case['case_id']}", headers=headers(user)).status_code == 403
    assert client.get('/api/eval/case-groups', headers=headers(user)).status_code == 200
    assert client.get('/api/eval/conversation-cases/' + case['case_id'], headers=headers(user)).status_code == 200


def test_only_developer_confirms_and_restores_accepted_configuration(client):
    _, group, case = setup_case(client)
    batch = wait(client, start(client, group))
    root = '/conversation-batches/' + batch['batch_id']
    assert client.post('/api/eval' + root + '/confirm', headers=headers('expert'), json={'note': '发布'}).status_code == 403
    assert client.post('/api/eval' + root + '/restore', headers=headers('expert'), json={'note': '回退'}).status_code == 403
    assert client.post('/api/eval' + root + '/confirm', headers=headers('dev'), json={'note': '发布'}).status_code == 409
    judge(client, batch, case)
    confirmation = post(client, root + '/confirm', {'note': '所有会话已核对，确认版本。'}, user='dev', status=200)
    assert confirmation['judgments'][-1]['conclusion'] == 'pass'
    runs = client.app.state.agent_runtime.runs
    runs.skill_config.update(expected_revision=0, values={'style': 'professional'}, actor='dev')
    assert client.post('/api/eval' + root + '/confirm', headers=headers('dev'), json={'note': '变更后不能沿用旧验证'}).status_code == 409
    restored = post(client, root + '/restore', {'note': '恢复已确认的表达配置。'}, user='dev', status=200)
    assert restored['after']['values'] == confirmation['snapshot']['values']
    assert len(runs.conversation_cases.version_events()) == 2


@pytest.mark.parametrize('user', ['alice', 'expert'])
def test_configuration_and_material_mutations_remain_developer_only(client, user):
    from src.api import explanation_trials, case_library, literature
    for router in [explanation_trials.router, case_library.router, literature.router]:
        client.app.include_router(router, prefix='/api')
    for method, path in [('POST', '/api/eval/prompt-versions'), ('PUT', '/api/eval/active-prompt'),
        ('PUT', '/api/eval/active-prompt-group'), ('POST', '/api/eval/task-prompts'),
        ('POST', '/api/case-library'), ('POST', '/api/literature/papers')]:
        response = client.request(method, path, headers=headers(user), json={})
        assert response.status_code == 403, (path, response.text)


def test_expert_can_start_daily_prompt_evaluation_but_ordinary_account_cannot(client):
    from src.api import explanation_trials
    client.app.include_router(explanation_trials.router, prefix='/api')
    body = {'submission_id': 'expert-trial', 'query': '你能做什么？'}
    # No model in this fixture: reaching model availability proves permission
    # was accepted, without creating a live model run in a permission test.
    response = client.post('/api/eval/explanation-trials', headers=headers('expert'), json=body)
    assert response.status_code == 503 and response.json()['detail']['code'] == 'trial_model_unavailable'
    assert client.post('/api/eval/explanation-trials', headers=headers('alice'), json=body).status_code == 403


def test_expert_cannot_create_prompt_versions_through_legacy_trial_input(client):
    from src.api import explanation_trials
    from src.evaluation.contracts import Principal
    from src.evaluation.explanation_trials import default_prompts
    client.app.include_router(explanation_trials.router, prefix='/api')
    client.app.state.llm = object()  # Pass availability; rejection must precede model execution.
    store = client.app.state.agent_runtime.runs.prompts
    before = store.list()
    prompts = default_prompts().model_dump()
    prompts['candidate'] = {'label': '未经授权的新版本', 'text': '由专家提交的新 Prompt。'}
    response = client.post('/api/eval/explanation-trials', headers=headers('expert'), json={
        'submission_id': 'expert-custom-prompt', 'query': '解释氮淋失。', 'prompts': prompts})
    assert response.status_code == 403, response.text
    assert store.list() == before
    assert client.app.state.explanation_trials.list(Principal(tester_id='dev', role='developer')) == []
    assert not client.app.state.explanation_trials.tasks
