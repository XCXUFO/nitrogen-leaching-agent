import hashlib
import json
import time

from tests.test_evaluation import client, headers, ask, score


def create_task(client):
    result = client.post('/api/eval/tasks', headers=headers('dev'), json={
        'title': 'two frozen cases', 'case_versions': [
            {'case_id': 'NEW01', 'case_version': 2}, {'case_id': 'F05', 'case_version': 2}],
        'build_version': 'unconfigured', 'knowledge_version': 'test'})
    assert result.status_code == 201
    return '/api/eval/tasks/' + result.json()['task_id']


def test_prepare_is_idempotent_private_and_preserves_reviews(client):
    path = create_task(client)
    prepared = client.post(path + '/prepare', headers=headers()).json()
    assert prepared['summary'] == {'total_cases': 2, 'prepared_cases': 2, 'started_cases': 0, 'reviewed_cases': 0, 'executions': 2}
    assert client.post(path + '/prepare', headers=headers()).json() == prepared
    alice_ids = prepared['task']['execution_ids']
    eid = alice_ids[0]
    assert not client.get(f'/api/eval/executions/{eid}', headers=headers()).json()['needs_reset']
    reviewed = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json={
        'overall': 'blocked', 'route_correct': 'n.a.', 'tool_correct': 'n.a.', 'evidence_correct': 'n.a.',
        'answer_correct': 'n.a.', 'notes': 'synthetic blocked record'})
    assert reviewed.status_code == 201
    after = client.post(path + '/prepare', headers=headers()).json()
    assert after['summary']['executions'] == 2 and after['summary']['reviewed_cases'] == 1
    bob = client.post(path + '/prepare', headers=headers('bob')).json()
    assert set(bob['task']['execution_ids']).isdisjoint(alice_ids)
    assert client.get(path, headers=headers('bob')).json()['execution_ids'] == bob['task']['execution_ids']
    assert client.get(path + '/progress', headers=headers('dev')).json()['summary']['executions'] == 4
    assert client.get(f'/api/eval/executions/{eid}', headers=headers()).json()['review'] == reviewed.json()['review']


def test_prepare_config_change_is_atomic_and_never_runs_queries(client):
    path = create_task(client)
    client.app.state.agent_runtime.config_version = 'changed:config'
    result = client.post(path + '/prepare', headers=headers())
    assert result.status_code == 422
    assert result.json()['detail']['code'] == 'task_config_mismatch'
    assert client.get(path + '/progress', headers=headers('dev')).json()['summary']['executions'] == 0
    assert client.get('/api/eval/runs', headers=headers('dev')).json() == []


def test_task_evidence_export_preserves_run_and_scoring_identity(client):
    path = create_task(client)
    eid = client.post(path + '/prepare', headers=headers()).json()['task']['execution_ids'][0]
    response = ask(client, eid, '你好')
    assert response.status_code == 200
    run_id = response.json()['events'][-1]['run_id']
    assert client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score()).status_code == 201
    assert client.get(path + '/evidence', headers=headers()).status_code == 403
    exported = client.get(path + '/evidence', headers=headers('dev')).json()
    payload = exported['payload']
    assert payload['task']['task_id'] == path.split('/')[-1]
    assert payload['traces'][run_id]['run_id'] == run_id
    assert payload['missing_run_ids'] == []
    assert next(item for item in payload['executions'] if item['execution_id'] == eid)['review']['review_kind'] == 'development_trial'
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    assert exported['payload_sha256'] == hashlib.sha256(canonical).hexdigest()
    assert 'access_key' not in json.dumps(exported) and 'token_sha256' not in json.dumps(exported)


def test_prepared_executions_start_empty_without_clear_and_remain_isolated(client):
    path = create_task(client)
    prepared = client.post(path + '/prepare', headers=headers()).json()
    first, second = prepared['task']['execution_ids']
    svc = client.app.state.evaluation
    assert not svc.contexts  # Batch preparation does not consume active capacity.
    assert client.get(f'/api/eval/executions/{first}', headers=headers('dev')).status_code == 200
    assert not svc.contexts  # Read-only observers cannot initialize another tester's context.
    opened = client.get(f'/api/eval/executions/{first}', headers=headers()).json()
    assert not opened['needs_reset'] and opened['events'] == [] and opened['attachment'] is None
    session = svc.contexts[first].session_id
    assert ask(client, first, '你好').status_code == 200
    assert client.post(path + '/prepare', headers=headers()).json()['summary']['executions'] == 2
    assert svc.contexts[first].session_id == session and svc.contexts[first].history
    assert client.get(f'/api/eval/executions/{second}', headers=headers()).json()['events'] == []
    assert svc.contexts[second].session_id != session
    assert svc.contexts[second].history == [] and svc.contexts[second].file_id is None
    assert client.get(f'/api/eval/executions/{first}', headers=headers()).json()['events'][0]['action'] == 'query'


def test_new_task_upload_needs_no_clear_but_started_context_loss_requires_recovery(client):
    from tests.test_evaluation import ROOT
    path = create_task(client)
    prepared = client.post(path + '/prepare', headers=headers()).json()
    eid = next(item['executions'][0]['execution_id'] for item in prepared['cases'] if item['case_id'] == 'F05')
    raw = (ROOT/'data/demo/Nbal_out.xls').read_bytes()
    response = client.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls', headers=headers(), content=raw)
    assert response.status_code == 200 and response.json()['events'][0]['action'] == 'upload'
    svc = client.app.state.evaluation
    svc.contexts[eid].expires_at = time.monotonic() - 1
    view = client.get(f'/api/eval/executions/{eid}', headers=headers()).json()
    assert view['needs_reset'] and len(view['events']) == 1
    lost = ask(client, eid, '硝态氮最大值')
    assert lost.status_code == 409 and lost.json()['detail']['code'] == 'evaluation_context_lost'
    assert client.get(f'/api/eval/executions/{eid}', headers=headers()).json()['events'] == view['events']
    reset = client.post(f'/api/eval/executions/{eid}/actions', headers=headers(), json={'action': 'clear'}).json()
    assert not reset['needs_reset'] and reset['events'][-1]['action'] == 'clear'
    assert reset['attachment'] is None


def test_unstarted_execution_can_initialize_after_restart_but_reviewed_one_cannot(client):
    path = create_task(client)
    first, second = client.post(path + '/prepare', headers=headers()).json()['task']['execution_ids']
    svc = client.app.state.evaluation
    client.get(f'/api/eval/executions/{first}', headers=headers())
    svc.contexts.clear()
    assert ask(client, first, '你好').status_code == 200
    reviewed = client.post(f'/api/eval/executions/{second}/reviews', headers=headers(), json={
        'overall': 'blocked', 'route_correct': 'n.a.', 'tool_correct': 'n.a.', 'evidence_correct': 'n.a.',
        'answer_correct': 'n.a.', 'notes': 'synthetic blocked record'})
    assert reviewed.status_code == 201
    assert client.get(f'/api/eval/executions/{second}', headers=headers()).json()['status'] == 'reviewed'
    assert second not in svc.contexts
