from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent.runtime import AgentRuntime
from src.api import chat, evaluation
from src.evaluation.contracts import AccessFile, Principal
from src.evaluation.service import EvaluationService
from src.evaluation.store import EvaluationStore
from src.storage.run_store import RunStore

ROOT = Path(__file__).resolve().parents[2]
TOKENS = {'alice': 'a'*40, 'bob': 'b'*40, 'dev': 'd'*40, 'expert': 'e'*40}


def headers(name='alice'):
    return {'Authorization': 'Bearer '+TOKENS[name]}


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.state.eval_access = AccessFile(users=[{'tester_id': name, 'role': 'developer' if name == 'dev' else 'reviewer' if name == 'expert' else 'tester',
      'token_sha256': hashlib.sha256(token.encode()).hexdigest()} for name, token in TOKENS.items()])
    runs = RunStore(tmp_path/'runs.sqlite3')
    app.state.agent_runtime = AgentRuntime(runs=runs)
    app.state.chat_service = None
    store = EvaluationStore(runs)
    store.seed(ROOT/'data/eval')
    app.state.evaluation = EvaluationService(store)
    app.include_router(chat.router, prefix='/api')
    app.include_router(evaluation.router, prefix='/api')
    with TestClient(app) as c:
        yield c
    runs.close()


def start(client, name='alice', case='NEW01', version=2):
    response = client.post('/api/eval/executions', headers=headers(name), json={'case_id': case, 'case_version': version})
    assert response.status_code == 201, response.text
    return response.json()['execution_id']


def ask(client, eid, query='1', name='alice', **extra):
    return client.post(f'/api/eval/executions/{eid}/query', headers=headers(name), json={'query': query, **extra})


def score(**overrides):
    return {'overall': 'pass', 'route_correct': 'yes', 'tool_correct': 'n.a.', 'evidence_correct': 'n.a.',
            'answer_correct': 'yes', 'usability': 4, 'notes': '', **overrides}


def test_disabled_and_missing_credentials_never_expose_records(client):
    assert client.get('/api/eval/cases').status_code == 401
    assert client.get('/api/eval/cases', headers={'Authorization': 'Bearer '+'x'*40}).status_code == 401
    client.app.state.eval_access = None
    assert client.get('/api/eval/cases', headers=headers('dev')).status_code == 404


def test_frontend_conversations_are_grouped_filterable_and_separate_from_executions(client):
    visitor = 'visitor_12345678'
    for query, history in (('你好', []), ('你能做什么？', [
        {'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '你好，我可以帮助分析农业模型。'}])):
        response = client.post('/api/chat', json={
            'query': query, 'session_id': 'front-session-one', 'operator_id': visitor, 'history': history})
        assert response.status_code == 200, response.text
    other = client.post('/api/chat', json={
        'query': '你好', 'session_id': 'front-session-two', 'operator_id': visitor})
    assert other.status_code == 200
    assert client.get('/api/eval/sessions', headers=headers()).status_code == 403
    assert client.get('/api/eval/executions', headers=headers('dev')).json() == []

    listing = client.get('/api/eval/sessions', headers=headers('dev')).json()
    assert listing['total'] == 2
    first = next(item for item in listing['items'] if item['session_id'] == 'front-session-one')
    assert first['turn_count'] == 2 and first['operator_id'] == visitor
    assert first['topic'] == '你能做什么' and first['status'] == '正常'
    detail = client.get('/api/eval/sessions/front-session-one', headers=headers('dev')).json()
    assert [turn['input'] for turn in detail['turns']] == ['你好', '你能做什么？']
    assert [turn['history_count'] for turn in detail['turns']] == [0, 2]
    assert all(turn['answer'] and turn['run_id'] and turn['tool_calls'] for turn in detail['turns'])
    run_id = detail['turns'][1]['run_id']
    assert client.get(f'/api/eval/sessions/{run_id}', headers=headers('dev')).json()['session_id'] == 'front-session-one'

    for params, expected in [
        ({'information': 'front-session-one'}, 1), ({'information': '你能做什么'}, 1),
        ({'operator_id': visitor}, 2), ({'operator_id': 'someone-else'}, 0),
        ({'status': '正常'}, 2), ({'duration_mode': 'gt', 'duration_ms': 999999}, 0),
        ({'duration_mode': 'lt', 'duration_ms': 999999}, 2),
    ]:
        result = client.get('/api/eval/sessions', params=params, headers=headers('dev')).json()
        assert result['total'] == expected
    page = client.get('/api/eval/sessions', params={'limit': 1, 'offset': 1}, headers=headers('dev')).json()
    assert page['total'] == 2 and len(page['items']) == 1
    assert client.get('/api/eval/sessions', params={'duration_mode': 'between', 'duration_ms': 5},
                      headers=headers('dev')).status_code == 422


def test_failed_frontend_answer_is_visible_as_abnormal_session(client):
    response = client.post('/api/chat', json={
        'query': '氮素淋失主要受哪些因素影响？', 'session_id': 'front-failed',
        'operator_id': 'visitor_12345678'})
    assert response.status_code == 503
    result = client.get('/api/eval/sessions', params={'status': '异常'}, headers=headers('dev')).json()
    assert result['total'] == 1 and result['items'][0]['session_id'] == 'front-failed'
    turn = client.get('/api/eval/sessions/front-failed', headers=headers('dev')).json()['turns'][0]
    assert turn['status'] == 'error' and turn['error_code'] == 'rag_not_configured'


def test_identity_and_roles_are_verified_server_side(client):
    assert client.get('/api/eval/me', headers=headers()).json() == {'tester_id': 'alice', 'role': 'tester'}
    for path in ('runs', 'statistics', 'runs/any-id'):
        assert client.get('/api/eval/'+path, headers=headers()).status_code == 403
    eid = start(client)
    for extra in ({'tester_id': 'dev'}, {'run_id': 'stolen'}, {'session_id': 'stolen'}):
        assert ask(client, eid, **extra).status_code == 422
    assert ask(client, eid, '   ').status_code == 422


def test_case_versions_and_pending_review_are_preserved(client):
    latest = client.get('/api/eval/cases', headers=headers()).json()
    all_cases = client.get('/api/eval/cases?latest=false', headers=headers()).json()
    assert len(all_cases) == 34
    assert len({c['case']['case_id'] for c in latest}) == len(latest)
    assert {c['case']['version'] for c in all_cases if c['case']['case_id'] == 'F02'} == {1, 3}
    assert all(c['professional_review'] == 'pending' for c in all_cases)
    store = client.app.state.evaluation.store
    store.seed(ROOT/'data/eval')
    assert len(store.cases(False)) == 34


def test_other_tester_cannot_read_mutate_or_score_execution(client):
    eid = start(client)
    assert client.get(f'/api/eval/executions/{eid}', headers=headers('bob')).status_code == 404
    assert client.get('/api/eval/executions', headers=headers('bob')).json() == []
    assert ask(client, eid, name='bob').status_code == 404
    assert client.post(f'/api/eval/executions/{eid}/reviews', headers=headers('bob'), json=score()).status_code == 404
    assert ask(client, eid, name='dev').status_code == 403
    assert client.get(f'/api/eval/executions/{eid}', headers=headers('dev')).status_code == 200


def test_multirun_review_is_immutable_and_survives_reopening(client):
    eid = start(client)
    first = ask(client, eid).json()
    second = ask(client, eid, '你好').json()
    ids = [event['run_id'] for event in second['events']]
    assert len(ids) == 2 and ids[0] == first['events'][0]['run_id']
    assert all('conversation_id' not in e['response'] for e in second['events'])
    result = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score())
    assert result.status_code == 201, result.text
    review = result.json()['review']
    assert review['run_ids'] == ids and review['tester_id'] == 'alice'
    assert review['professional_review'] == 'pending'
    assert result.json()['status'] == 'reviewed'
    assert ask(client, eid).status_code == 409
    assert client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score()).status_code == 409
    db = client.app.state.evaluation.store.db.execute('PRAGMA database_list').fetchone()[2]
    reopened = RunStore(db)
    try:
        saved = EvaluationStore(reopened).execution(eid, Principal(tester_id='alice', role='tester'))
        assert saved['review'] == review
    finally:
        reopened.close()


def test_failed_run_remains_bound_and_trace_is_developer_only(client):
    eid = start(client, case='X01', version=2)
    event = ask(client, eid, '氮素淋失受哪些因素影响？').json()['events'][0]
    assert event['error']['code'] == 'rag_not_configured'
    assert event['run_id'] and not event['trace_missing']
    trace = client.get('/api/eval/runs/'+event['run_id'], headers=headers('dev')).json()
    assert trace['status'] == 'error' and trace['error_code'] == 'rag_not_configured'
    assert client.get('/api/eval/runs/'+event['run_id'], headers=headers()).status_code == 403


def test_blocked_without_runs_and_statistics_denominators(client):
    blocked = start(client)
    body = score(overall='blocked', route_correct='n.a.', answer_correct='n.a.', usability=None, notes='缺少试验材料')
    assert client.post(f'/api/eval/executions/{blocked}/reviews', headers=headers(), json=body).status_code == 201
    normal = start(client)
    ask(client, normal)
    partial = score(overall='partial', evidence_correct='partial', notes='部分证据需核对')
    assert client.post(f'/api/eval/executions/{normal}/reviews', headers=headers(), json=partial).status_code == 201
    start(client, name='bob')
    stats = client.get('/api/eval/statistics', headers=headers('dev')).json()
    assert stats['executions'] == 3 and stats['pending'] == 1
    assert stats['overall'] == {'pass': 0, 'partial': 1, 'fail': 0, 'blocked': 1}
    assert stats['layers']['evidence_correct'] == {'denominator': 1, 'yes': 0, 'partial': 1, 'no': 0}
    assert stats['layers']['tool_correct']['denominator'] == 0
    assert len(stats['by_case_version']) == 1


@pytest.mark.parametrize('body', [score(overall='blocked'), score(overall='fail'), score(answer_correct='no'), score(tester_id='dev')])
def test_invalid_or_forged_scores_are_rejected(client, body):
    eid = start(client)
    ask(client, eid)
    assert client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=body).status_code == 422


def test_success_score_requires_actual_runs(client):
    eid = start(client)
    assert client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score()).status_code == 409


def test_context_loss_requires_explicit_reset_and_preserves_old_runs(client):
    eid = start(client)
    ask(client, eid)
    ctx = client.app.state.evaluation.contexts[eid]
    old_session = ctx.session_id
    ctx.expires_at = time.monotonic() - 1
    assert ask(client, eid).status_code == 409
    view = client.get(f'/api/eval/executions/{eid}', headers=headers()).json()
    assert view['needs_reset'] and len(view['events']) == 1
    reset = client.post(f'/api/eval/executions/{eid}/actions', headers=headers(), json={'action': 'clear'}).json()
    assert len(reset['events']) == 2 and not reset['needs_reset']
    assert client.app.state.evaluation.contexts[eid].session_id != old_session
    assert len(ask(client, eid).json()['events']) == 3


def test_missing_trace_cannot_be_silently_scored(client, monkeypatch):
    eid = start(client)
    monkeypatch.setattr(client.app.state.agent_runtime.runs, 'append', lambda trace: (_ for _ in ()).throw(OSError('disk full')))
    event = ask(client, eid).json()['events'][0]
    assert event['trace_missing'] and event['run_id'] is None
    assert client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score()).status_code == 409


def test_busy_execution_rejects_competing_query_or_review(client):
    eid = start(client)
    client.app.state.evaluation.busy.add(eid)
    assert ask(client, eid).status_code == 409
    assert client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score()).status_code == 409


def test_upload_fingerprint_is_bound_and_token_never_persisted(client):
    eid = start(client, case='F02', version=3)
    raw = (ROOT/'data/demo/Nbal_out.xls').read_bytes()
    result = client.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls', headers=headers(), content=raw)
    assert result.status_code == 200
    assert result.json()['attachment']['status'] == 'pending'
    ctx = client.app.state.evaluation.contexts[eid]
    assert ctx.file_id and ctx.file_id not in result.text
    original_token = ctx.file_id
    numeric = ask(client, eid, '硝态氮最大值').json()
    assert numeric['events'][-1]['response']['file_evidence'][0]['model_day'] == 283
    assert ctx.file_id not in json.dumps(numeric)
    mismatch = client.post(f'/api/eval/executions/{eid}/files?filename=wrong.xls', headers=headers(), content=raw).json()
    assert mismatch['events'][-1]['error']['code'] == 'evaluation_fixture_mismatch'
    assert mismatch['attachment']['filename'] == 'Nbal_out.xls' and ctx.file_id == original_token
    followup = ask(client, eid, '那最小值呢？').json()
    assert followup['events'][-1]['response']['file_evidence'][0]['value'] == 0


def test_attachment_reused_across_active_session_refresh_and_failed_upload(client, monkeypatch):
    from types import SimpleNamespace
    from src.api import files
    from src.agent import state
    from src.evaluation import service

    tick = [100.0]
    clock = SimpleNamespace(monotonic=lambda: tick[0])
    for module in (files, state, service):
        monkeypatch.setattr(module, 'time', clock)
    eid = start(client, case='F05', version=2)
    raw = (ROOT/'data/demo/Nbal_out.xls').read_bytes()
    uploaded = client.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls', headers=headers(), content=raw)
    assert uploaded.status_code == 200
    ctx = client.app.state.evaluation.contexts[eid]
    token = ctx.file_id
    maximum = ask(client, eid, 'leak_NO3 最大值').json()['events'][-1]['response']
    assert maximum['file_evidence'][0]['model_day'] == 283
    tick[0] += 1700
    assert ask(client, eid, '你好').status_code == 200  # No file tool, still active.
    tick[0] += 1700  # Beyond the original upload's 30-minute deadline.
    view = client.get(f'/api/eval/executions/{eid}', headers=headers()).json()
    assert not view['needs_reset'] and view['attachment']['filename'] == 'Nbal_out.xls'
    minimum = ask(client, eid, 'leak_NO3 最小值').json()['events'][-1]['response']
    assert minimum['file_evidence'][0]['value'] == 0
    assert minimum['file_evidence'][0]['sha256'] == maximum['file_evidence'][0]['sha256']
    failed = client.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls', headers=headers(), content=b'').json()
    assert failed['events'][-1]['error'] and ctx.file_id == token
    assert ask(client, eid, '那最小值呢？').json()['events'][-1]['response']['file_evidence'][0]['occurrences'] == 191
    assert len([event for event in view['events'] if event['action'] == 'upload']) == 1
    removed = client.post(f'/api/eval/executions/{eid}/actions', headers=headers(), json={'action': 'remove_attachment'}).json()
    assert removed['attachment'] is None
    result = ask(client, eid, '那最小值呢？').json()['events'][-1]['response']
    assert result['route'] == 'clarification' and not result['file_evidence']


def test_idle_execution_attachment_is_not_revived(client):
    eid = start(client, case='F05', version=2)
    raw = (ROOT/'data/demo/Nbal_out.xls').read_bytes()
    client.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls', headers=headers(), content=raw)
    ctx = client.app.state.evaluation.contexts[eid]
    client.app.state.file_store.entries[ctx.file_id].expires_at = time.monotonic() - 1
    result = ask(client, eid, 'leak_NO3 最大值').json()
    assert result['events'][-1]['error']['code'] == 'file_not_found'
    assert result['attachment'] is None and ctx.file_id is None


def test_k01_workbench_first_question_preserves_article_evidence_without_auto_review(client):
    from tests.test_composition import service

    client.app.state.chat_service = service()[0]
    eid = start(client, case='K01', version=4)
    result = ask(client, eid, '玉米农田氮素淋失主要受哪些因素影响？').json()
    event = result['events'][-1]
    assert event['run_id'] and result['status'] == 'open' and result['review'] is None
    assert event['response']['agent_route'] == 'KNOWLEDGE'
    assert len(event['response']['citations']) == 2
    assert all(citation['title'] and citation['snippet'] for citation in event['response']['citations'])
    reopened = client.get(f'/api/eval/executions/{eid}', headers=headers()).json()
    assert reopened['events'] == result['events'] and reopened['review'] is None


def test_upload_only_case_can_be_reviewed_without_inventing_chat_run(client):
    eid = start(client, case='F02', version=3)
    raw = (ROOT/'data/demo/Nbal_out.xls').read_bytes()
    client.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls', headers=headers(), content=raw)
    body = score(overall='partial', route_correct='n.a.', answer_correct='partial', notes='只完成上传，尚未检查分析结果')
    result = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=body)
    assert result.status_code == 201
    assert result.json()['review']['run_ids'] == []
    assert result.json()['review']['event_sequences'] == [1]


def test_case_seed_refuses_to_overwrite_frozen_versions(client, tmp_path):
    import shutil
    for name in ('manual_cases.v1.json', 'harness_cases.v2.json', 'harness_cases.v3.json', 'harness_cases.v4.json'):
        shutil.copyfile(ROOT/'data/eval'/name, tmp_path/name)
    path = tmp_path/'harness_cases.v3.json'
    data = json.loads(path.read_text())
    data['cases'][0]['expected'] = ['quietly changed criterion']
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='immutable case changed'):
        client.app.state.evaluation.store.seed(tmp_path)
    assert client.app.state.evaluation.store.case('F02', 3)['case']['expected'] != ['quietly changed criterion']


def test_main_lifespan_initializes_authenticated_evaluation(tmp_path, monkeypatch):
    from src.main import app, settings
    access = AccessFile(users=[{'tester_id': 'alice', 'role': 'tester', 'token_sha256': hashlib.sha256(TOKENS['alice'].encode()).hexdigest()}])
    path = tmp_path/'access.json'
    path.write_text(access.model_dump_json())
    monkeypatch.setattr(settings, 'eval_enabled', True)
    monkeypatch.setattr(settings, 'eval_access_file', str(path))
    monkeypatch.setattr(settings, 'agent_trace_db', str(tmp_path/'main.sqlite3'))
    monkeypatch.setattr(settings, 'rag_enabled', False)
    with TestClient(app) as c:
        result = c.get('/api/eval/cases', headers=headers())
        assert result.status_code == 200, result.text
        assert result.headers['cache-control'] == 'no-store'
        assert c.get('/api/eval/cases').status_code == 401


def test_invalid_access_configuration_fails_closed(tmp_path):
    from src.evaluation.auth import load_access
    path = tmp_path/'access.json'
    path.write_text('{"users":[]}')
    with pytest.raises(ValueError):
        load_access(str(path))
    with pytest.raises(ValueError):
        AccessFile(users=[{'tester_id': 'a', 'role': 'tester', 'token_sha256': 'a'*64},
                          {'tester_id': 'b', 'role': 'developer', 'token_sha256': 'a'*64}])


def test_task_issue_retest_and_review_identity_form_a_preserved_chain(client):
    task_body = {'title': 'P0 regression', 'case_versions': [{'case_id': 'X01', 'case_version': 2}],
                 'build_version': 'unconfigured', 'knowledge_version': 'kb-a', 'notes': 'frozen scope'}
    assert client.get('/api/eval/config', headers=headers()).json()['build_version'] == 'unconfigured'
    assert client.post('/api/eval/tasks', headers=headers('dev'),
                       json={**task_body, 'build_version': 'wrong-build'}).status_code == 422
    task_response = client.post('/api/eval/tasks', headers=headers('dev'), json=task_body)
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()
    assert task['created_by'] == 'dev'
    assert task['runtime_config_version'] == client.app.state.agent_runtime.config_version
    assert 'collection' in task['knowledge_config']
    assert client.post('/api/eval/tasks', headers=headers(), json=task_body).status_code == 403
    assert client.post('/api/eval/executions', headers=headers(),
                       json={'case_id': 'NEW01', 'case_version': 2, 'task_id': task['task_id']}).status_code == 422
    client.app.state.agent_runtime.config_version = 'changed-build:other-config'
    assert client.post('/api/eval/executions', headers=headers(),
                       json={'case_id': 'X01', 'case_version': 2, 'task_id': task['task_id']}).status_code == 422
    client.app.state.agent_runtime.config_version = task['runtime_config_version']
    first = client.post('/api/eval/executions', headers=headers(),
                        json={'case_id': 'X01', 'case_version': 2, 'task_id': task['task_id']}).json()
    eid = first['execution_id']
    assert first['task_id'] == task['task_id']
    event = ask(client, eid, '原始失败问题').json()['events'][0]
    old_run = event['run_id']
    failed = score(overall='fail', route_correct='no', answer_correct='no', notes='路由失败')
    original_review = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=failed).json()['review']
    issue_body = {'execution_id': eid, 'event_sequence': 1, 'title': '错误路由', 'assignee': 'dev',
                  'evidence_note': 'Trace 的 reason_code 与预期不一致'}
    issue_response = client.post('/api/eval/issues', headers=headers('dev'), json=issue_body)
    assert issue_response.status_code == 201, issue_response.text
    issue = issue_response.json()
    assert issue['run_id'] == old_run and issue['original_question'] == '原始失败问题'
    assert issue['review_id'] == original_review['review_id'] and issue['task_id'] == task['task_id']
    assert client.post('/api/eval/issues', headers=headers(), json=issue_body).status_code == 403
    assert client.get(f'/api/eval/tasks/{task["task_id"]}', headers=headers()).json()['execution_ids'] == [eid]
    assert client.post(f'/api/eval/issues/{issue["issue_id"]}/retests', headers=headers('dev'),
                       json={'execution_id': eid, 'fix_version': 'build-b'}).status_code == 422

    second = client.post('/api/eval/executions', headers=headers(),
                         json={'case_id': 'X01', 'case_version': 2, 'task_id': task['task_id']}).json()
    eid2 = second['execution_id']
    assert client.post(f'/api/eval/issues/{issue["issue_id"]}/retests', headers=headers('dev'),
                       json={'execution_id': eid2, 'fix_version': 'build-b'}).status_code == 422
    new_run = ask(client, eid2, '复测问题').json()['events'][0]['run_id']
    second_review = client.post(f'/api/eval/executions/{eid2}/reviews', headers=headers(), json=score()).json()['review']
    assert client.post(f'/api/eval/issues/{issue["issue_id"]}/retests', headers=headers('dev'),
                       json={'execution_id': eid2, 'fix_version': 'build-b'}).status_code == 422
    retest = client.post(f'/api/eval/issues/{issue["issue_id"]}/retests', headers=headers('dev'),
                         json={'execution_id': eid2, 'fix_version': 'unconfigured', 'notes': '人工复测'}).json()
    assert retest['run_ids'] == [new_run] and retest['review_id'] == second_review['review_id']
    assert retest['version_verified'] and retest['runtime_config_versions'] == ['unconfigured']
    assert retest['review_id'] != original_review['review_id']
    dashboard = client.get(f'/api/eval/tasks/{task["task_id"]}/dashboard', headers=headers('dev')).json()
    assert dashboard['summary'] == {'executions': 2, 'pending': 0, 'scored_denominator': 2,
                                    'pass': 1, 'partial': 0, 'fail': 1, 'blocked': 0}
    assert dashboard['issues'] == {'total': 1, 'unresolved': 0}
    assert dashboard['severe_regressions'] == []
    assert client.get(f'/api/eval/tasks/{task["task_id"]}/dashboard', headers=headers()).status_code == 403
    saved_issue = client.get(f'/api/eval/issues/{issue["issue_id"]}', headers=headers('dev')).json()
    assert saved_issue['review_snapshot'] == original_review and saved_issue['retests'] == [retest]
    assert client.post(f'/api/eval/issues/{issue["issue_id"]}/retests', headers=headers('dev'),
                       json={'execution_id': eid2, 'fix_version': 'build-c'}).status_code == 409

    assessment = {'case_id': 'X01', 'case_version': 2, 'overall': 'partial', 'kind': 'ai_assisted',
                  'source_path': 'sources/professional-review-results-reviewed.csv', 'source_sha256': 'a'*64,
                  'notes': 'AI 辅助复核，尚待专家签核', 'execution_id': eid}
    assert client.post('/api/eval/assessments', headers=headers('expert'), json=assessment).status_code == 403
    ai = client.post('/api/eval/assessments', headers=headers('dev'), json=assessment).json()
    assert ai['kind'] == 'ai_assisted' and ai['reviewer_role'] == 'developer'
    assert ai['review_id'] == original_review['review_id']
    dashboard = client.get(f'/api/eval/tasks/{task["task_id"]}/dashboard', headers=headers('dev')).json()
    assert dashboard['assessment_counts'] == {'ai_assisted': 1, 'domain_expert': 0}
    case_after_ai = next(c for c in client.get('/api/eval/cases?latest=false', headers=headers('dev')).json()
                         if c['case']['case_id'] == 'X01' and c['case']['version'] == 2)
    assert case_after_ai['professional_review'] == 'pending' and case_after_ai['ai_assisted_review_count'] == 1
    assessment['kind'] = 'domain_expert'
    assert client.post('/api/eval/assessments', headers=headers('dev'), json=assessment).status_code == 403
    expert = client.post('/api/eval/assessments', headers=headers('expert'), json=assessment).json()
    assert expert['kind'] == 'domain_expert' and expert['recorded_by'] == 'expert'
    case_after_expert = next(c for c in client.get('/api/eval/cases?latest=false', headers=headers('dev')).json()
                             if c['case']['case_id'] == 'X01' and c['case']['version'] == 2)
    assert case_after_expert['professional_review'] == 'domain_expert_reviewed'
    assert case_after_expert['professional_outcome'] == 'partial' and case_after_expert['domain_expert_review_count'] == 1
    all_assessments = client.get('/api/eval/assessments?case_id=X01', headers=headers('dev')).json()
    assert {a['assessment_id'] for a in all_assessments} == {ai['assessment_id'], expert['assessment_id']}
    assert client.get('/api/eval/assessments', headers=headers()).status_code == 403


def test_asset_provenance_candidate_pair_and_versioned_case_publication(client):
    def asset(kind, path):
        response = client.post('/api/eval/assets', headers=headers('dev'), json={
            'kind': kind, 'path': path, 'source': 'isolated catalog contract test', 'source_date': '2026-10-04'})
        assert response.status_code == 201, response.text
        return response.json()

    base = 'data/demo/'
    fixture = asset('result_fixture', base + 'Nbal_out.xls')
    model_input = asset('model_input', base + 'synthetic-model-input.txt')
    model_output = asset('model_output', base + 'Nbal_out.xls')
    evidence = asset('evidence', 'docs/public-demo.md')
    assert fixture['sha256'] == hashlib.sha256((ROOT / (base + 'Nbal_out.xls')).read_bytes()).hexdigest()
    assert client.post('/api/eval/assets', headers=headers('dev'), json={
        'kind': 'evidence', 'path': '/etc/passwd', 'source': 'forged'}).status_code == 422
    assert client.get('/api/eval/assets', headers=headers()).status_code == 403
    pair_body = {'input_asset_id': model_input['asset_id'], 'output_asset_id': model_output['asset_id'],
                 'status': 'candidate', 'notes': '配对尚未证实'}
    candidate = client.post('/api/eval/asset-pairs', headers=headers('dev'), json=pair_body)
    assert candidate.status_code == 201
    verification = {**pair_body, 'status': 'verified', 'evidence_asset_id': evidence['asset_id'],
                    'supersedes_pair_id': candidate.json()['pair_id'], 'notes': 'isolated test attestation only'}
    assert client.post('/api/eval/asset-pairs', headers=headers('dev'), json=verification).status_code == 403
    verified = client.post('/api/eval/asset-pairs', headers=headers('expert'), json=verification)
    assert verified.status_code == 201 and verified.json()['reviewer_role'] == 'reviewer'
    assert verified.json()['input_sha256'] == model_input['sha256']

    original = client.app.state.evaluation.store.case('NEW01', 2)
    new_case = {**original['case'], 'version': 3, 'title': '版本化附件目录试验',
                'attachment_requirements': ['Nbal_out.xls'], 'supersedes': 'NEW01@2'}
    draft_body = {'case': new_case, 'fixture_asset_ids': [fixture['asset_id']], 'notes': 'draft only'}
    created = client.post('/api/eval/case-drafts', headers=headers('dev'), json=draft_body)
    assert created.status_code == 201, created.text
    draft = created.json()
    assert client.app.state.evaluation.store.case('NEW01', 2) == original
    update = client.put(f'/api/eval/case-drafts/{draft["draft_id"]}', headers=headers('dev'), json={
        **draft_body, 'expected_revision': 1, 'notes': 'reviewed draft'}).json()
    assert update['revision'] == 2
    assert client.put(f'/api/eval/case-drafts/{draft["draft_id"]}', headers=headers('dev'), json={
        **draft_body, 'expected_revision': 1}).status_code == 409
    assert client.post(f'/api/eval/case-drafts/{draft["draft_id"]}/publish', headers=headers('dev'),
                       json={'expected_revision': 1}).status_code == 409
    published = client.post(f'/api/eval/case-drafts/{draft["draft_id"]}/publish', headers=headers('dev'),
                            json={'expected_revision': 2})
    assert published.status_code == 201, published.text
    assert published.json()['fixtures'][0]['sha256'] == fixture['sha256']
    assert client.app.state.evaluation.store.case('NEW01', 3) == published.json()
    assert client.app.state.evaluation.store.case('NEW01', 2) == original
    history = client.get(f'/api/eval/case-drafts/{draft["draft_id"]}/history', headers=headers('dev')).json()
    assert [item['revision'] for item in history] == [1, 2, 3]
    assert client.post(f'/api/eval/case-drafts/{draft["draft_id"]}/publish', headers=headers('dev'),
                       json={'expected_revision': 2}).status_code == 409
