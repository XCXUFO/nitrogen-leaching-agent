"""Version changes must not quietly alter frozen tasks or issue resolution."""
import pytest

from tests.test_evaluation import client, headers, ask, score, start


def frozen_execution(c):
    task = c.post('/api/eval/tasks', headers=headers('dev'), json={
        'title': 'version integrity', 'case_versions': [{'case_id': 'NEW01', 'case_version': 2}],
        'build_version': 'unconfigured', 'knowledge_version': 'isolated-test'}).json()
    execution = c.post('/api/eval/executions', headers=headers(), json={
        'case_id': 'NEW01', 'case_version': 2, 'task_id': task['task_id']}).json()
    return task, execution['execution_id']


def test_changed_build_blocks_further_task_actions_but_keeps_old_evidence_reviewable(client):
    _, eid = frozen_execution(client)
    before = ask(client, eid, '你好').json()['events']
    client.app.state.agent_runtime.config_version = 'new-build:new-config'
    responses = [ask(client, eid, '你好'),
        client.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls', headers=headers(), content=b'not read'),
        client.post(f'/api/eval/executions/{eid}/actions', headers=headers(), json={'action': 'clear'}),
        client.post(f'/api/eval/executions/{eid}/actions', headers=headers(), json={'action': 'remove_attachment'})]
    assert all(r.status_code == 409 and r.json()['detail']['code'] == 'task_config_mismatch' for r in responses)
    assert client.get(f'/api/eval/executions/{eid}', headers=headers()).json()['events'] == before
    assert client.post(f'/api/eval/executions/{eid}/actions', headers=headers(),
                       json={'action': 'manual', 'note': '服务已更换版本，记录原执行已完成部分'}).status_code == 200
    result = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score())
    assert result.status_code == 201
    assert result.json()['review']['runtime_config_versions'] == ['unconfigured']


def test_legacy_mixed_task_runs_require_blocked_review(client):
    _, eid = frozen_execution(client)
    ask(client, eid, '你好')
    # Reproduce a mixed execution written before per-operation version guards.
    client.app.state.agent_runtime.config_version = 'other-build:config'
    other = start(client)
    run_id = ask(client, other, '你好').json()['events'][0]['run_id']
    store = client.app.state.evaluation.store
    with store.lock, store.db:
        store.db.execute('DELETE FROM eval_events WHERE execution_id=?', (other,))
    store.event(eid, {'action': 'query', 'input': '历史混入的一轮'}, run_id=run_id)
    response = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score())
    assert response.status_code == 409 and response.json()['detail']['code'] == 'task_run_config_mismatch'
    blocked = score(overall='blocked', route_correct='n.a.', answer_correct='n.a.', notes='历史执行混用版本')
    result = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=blocked)
    assert result.status_code == 201
    assert result.json()['review']['runtime_config_versions'] == ['other-build:config', 'unconfigured']


def issue_from_failed_execution(c):
    task, eid = frozen_execution(c)
    ask(c, eid, '你好')
    c.post(f'/api/eval/executions/{eid}/reviews', headers=headers(),
           json=score(overall='fail', answer_correct='no', notes='synthetic failure'))
    issue = c.post('/api/eval/issues', headers=headers('dev'), json={
        'execution_id': eid, 'event_sequence': 1, 'title': 'synthetic issue',
        'assignee': 'dev', 'evidence_note': 'isolated test only'}).json()
    return task, issue


def test_retest_uses_saved_run_version_and_latest_result_reopens_issue(client):
    task, issue = issue_from_failed_execution(client)
    def retest(overall):
        client.app.state.agent_runtime.config_version = 'candidate:hash'
        eid = start(client)
        ask(client, eid, '你好')
        body = score() if overall == 'pass' else score(overall='fail', answer_correct='no', notes='failure reappeared')
        client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=body)
        # The active server can change before linkage; the saved Run is authoritative.
        client.app.state.agent_runtime.config_version = 'later-server:hash'
        url = f'/api/eval/issues/{issue["issue_id"]}/retests'
        wrong = client.post(url, headers=headers('dev'), json={'execution_id': eid, 'fix_version': 'later-server'})
        assert wrong.status_code == 422
        response = client.post(url, headers=headers('dev'), json={'execution_id': eid, 'fix_version': 'candidate'})
        assert response.status_code == 201, response.text
        assert response.json()['runtime_config_versions'] == ['candidate:hash']
        assert response.json()['version_verified']
        return response.json()
    passed = retest('pass')
    url = f'/api/eval/tasks/{task["task_id"]}/dashboard'
    assert client.get(url, headers=headers('dev')).json()['issues']['unresolved'] == 0
    failed = retest('fail')
    assert client.get(url, headers=headers('dev')).json()['issues']['unresolved'] == 1
    saved = client.get(f'/api/eval/issues/{issue["issue_id"]}', headers=headers('dev')).json()
    assert saved['retests'] == [passed, failed]
    listed = client.get('/api/eval/issues', headers=headers('dev')).json()
    assert listed[0]['retests'] == [passed, failed]


@pytest.mark.parametrize('mixed', [False, True])
def test_retest_without_single_run_version_cannot_resolve_issue(client, mixed):
    _, issue = issue_from_failed_execution(client)
    eid = start(client)
    if mixed:
        ask(client, eid)
        client.app.state.agent_runtime.config_version = 'another:config'
        ask(client, eid)
    else:
        client.post(f'/api/eval/executions/{eid}/files?filename=sample.xls', headers=headers(), content=b'invalid')
    reviewed = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=score())
    assert reviewed.status_code == 201
    result = client.post(f'/api/eval/issues/{issue["issue_id"]}/retests', headers=headers('dev'),
                         json={'execution_id': eid, 'fix_version': 'unconfigured'})
    assert result.status_code == 422 and result.json()['detail']['code'] == 'retest_version_mismatch'


@pytest.mark.parametrize('changed', ['input.xls', 'output.xls', 'proof.txt'])
def test_pair_verification_rechecks_registered_originals(client, tmp_path, monkeypatch, changed):
    from src.evaluation import catalog
    monkeypatch.setattr(catalog, 'ROOT', tmp_path)
    (tmp_path / 'data').mkdir()
    assets = []
    for filename, kind in [('input.xls', 'model_input'), ('output.xls', 'model_output'), ('proof.txt', 'evidence')]:
        (tmp_path / 'data' / filename).write_text('synthetic contract test only')
        response = client.post('/api/eval/assets', headers=headers('dev'), json={
            'kind': kind, 'path': f'data/{filename}', 'source': 'isolated synthetic fixture'})
        assert response.status_code == 201
        assets.append(response.json())
    body = {'input_asset_id': assets[0]['asset_id'], 'output_asset_id': assets[1]['asset_id'], 'status': 'candidate'}
    candidate = client.post('/api/eval/asset-pairs', headers=headers('dev'), json=body).json()
    (tmp_path / 'data' / changed).write_text('changed after registration')
    response = client.post('/api/eval/asset-pairs', headers=headers('expert'), json={
        **body, 'status': 'verified', 'supersedes_pair_id': candidate['pair_id'],
        'evidence_asset_id': assets[2]['asset_id'], 'notes': 'test only, never a real expert attestation'})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'pair_asset_changed'
    assert client.get('/api/eval/asset-pairs', headers=headers('dev')).json() == [candidate]
