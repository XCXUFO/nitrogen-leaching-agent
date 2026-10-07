from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.evaluation.contracts import Principal
from src.evaluation.regression import RegressionService
from tests.test_evaluation import client, headers, start, ask, score, ROOT


@pytest.fixture
def regression_client(client):
    client.app.state.regressions = RegressionService(client.app.state.evaluation)
    yield client
    client.portal.call(client.app.state.regressions.shutdown)


def baseline(c, *, file=False, manual=False):
    eid = start(c, name='dev', case='F05' if file else 'NEW01', version=2)
    if file:
        raw = (ROOT/'data/demo/Nbal_out.xls').read_bytes()
        c.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls', headers=headers('dev'), content=raw)
    ask(c, eid, '硝态氮最大值' if file else '1', name='dev')
    ask(c, eid, '那最小值呢？' if file else '你好', name='dev')
    if manual:
        c.post(f'/api/eval/executions/{eid}/actions', headers=headers('dev'), json={'action': 'manual', 'note': '等待附件过期'})
    result = c.post('/api/eval/regressions', headers=headers('dev'), json={'execution_id': eid, 'title': 'Frozen example'})
    assert result.status_code == 201, result.text
    return result.json()


def replay_and_wait(c, rid):
    response = c.post(f'/api/eval/regressions/{rid}/replays', headers=headers('dev'))
    assert response.status_code == 202, response.text
    rid = response.json()['replay_id']
    async def wait():
        task = c.app.state.regressions.jobs.get(rid)
        if task:
            await asyncio.wait_for(asyncio.shield(task), 10)
    c.portal.call(wait)
    return c.get(f'/api/eval/replays/{rid}', headers=headers('dev')).json()


def test_freezes_baseline_and_compares_multiturn_without_auto_review(regression_client):
    c = regression_client
    saved = baseline(c)
    original = json.dumps(saved, sort_keys=True)
    c.app.state.agent_runtime.config_version = 'new-build:new-config'
    result = replay_and_wait(c, saved['regression_id'])
    assert result['state'] == 'completed', result
    comparison = c.get(f"/api/eval/replays/{result['replay_id']}/comparison", headers=headers('dev')).json()
    assert len(comparison['pairs']) == 2
    assert all(p['changes'] == ['config_version'] for p in comparison['pairs'])
    assert comparison['candidate_review'] is None and comparison['professional_review'] == 'pending'
    assert json.dumps(c.get('/api/eval/regressions/'+saved['regression_id'], headers=headers('dev')).json(), sort_keys=True) == original
    candidate = c.get('/api/eval/executions/'+result['execution_id'], headers=headers('dev')).json()
    assert len(candidate['events']) == 2 and candidate['review'] is None
    assert candidate['events'][0]['run_id'] != saved['baseline']['events'][0]['run_id']


def test_dashboard_flags_only_reviewed_severe_regression_with_independent_scores(regression_client):
    c = regression_client
    task = c.post('/api/eval/tasks', headers=headers('dev'), json={
        'title': 'Frozen regression cohort', 'case_versions': [{'case_id': 'NEW01', 'case_version': 2}],
        'build_version': 'unconfigured', 'knowledge_version': 'test-kb'}).json()
    original = c.post('/api/eval/executions', headers=headers('dev'), json={
        'case_id': 'NEW01', 'case_version': 2, 'task_id': task['task_id']}).json()
    eid = original['execution_id']
    ask(c, eid, '1', name='dev')
    saved_review = c.post(f'/api/eval/executions/{eid}/reviews', headers=headers('dev'), json=score()).json()['review']
    baseline_response = c.post('/api/eval/regressions', headers=headers('dev'), json={
        'execution_id': eid, 'title': 'Baseline from task'})
    assert baseline_response.status_code == 201
    c.app.state.agent_runtime.config_version = 'candidate-build:new-config'
    replay = replay_and_wait(c, baseline_response.json()['regression_id'])
    assert replay['state'] == 'completed'
    before_review = c.get(f'/api/eval/tasks/{task["task_id"]}/dashboard', headers=headers('dev')).json()
    assert before_review['severe_regressions'] == []
    candidate_review = c.post(f'/api/eval/executions/{replay["execution_id"]}/reviews',
                              headers=headers('dev'), json=score(overall='fail', answer_correct='no', notes='回归后答案不正确')).json()['review']
    assert candidate_review['review_id'] != saved_review['review_id']
    dashboard = c.get(f'/api/eval/tasks/{task["task_id"]}/dashboard', headers=headers('dev')).json()
    assert dashboard['summary']['executions'] == 1 and dashboard['summary']['pass'] == 1
    assert len(dashboard['severe_regressions']) == 1
    assert dashboard['severe_regressions'][0]['reasons'] == ['overall_pass_to_fail', 'answer_correct_yes_to_no']


def test_replays_original_file_and_inherits_metric(regression_client):
    c = regression_client
    saved = baseline(c, file=True)
    result = replay_and_wait(c, saved['regression_id'])
    assert result['state'] == 'completed', result
    compared = c.get(f"/api/eval/replays/{result['replay_id']}/comparison", headers=headers('dev')).json()
    assert all(p['changes'] == [] for p in compared['pairs'])
    assert compared['pairs'][1]['candidate']['file_evidence'][0]['occurrences'] == 191


def test_replays_fixture_from_published_case_snapshot(regression_client):
    c = regression_client
    path = 'data/demo/Nbal_out.xls'
    asset = c.post('/api/eval/assets', headers=headers('dev'), json={
        'kind': 'result_fixture', 'path': path, 'source': 'local test fixture'}).json()
    original = next(item['case'] for item in c.get('/api/eval/cases?latest=false',
        headers=headers('dev')).json() if item['case']['case_id'] == 'F05' and item['case']['version'] == 2)
    case = {**original, 'case_id': 'CATREPLAY', 'version': 1, 'title': 'Published fixture replay'}
    draft = c.post('/api/eval/case-drafts', headers=headers('dev'), json={
        'case': case, 'fixture_asset_ids': [asset['asset_id']]}).json()
    published = c.post(f"/api/eval/case-drafts/{draft['draft_id']}/publish",
        headers=headers('dev'), json={'expected_revision': draft['revision']}).json()
    assert published['fixtures'][0]['path'] == path
    eid = start(c, name='dev', case='CATREPLAY', version=1)
    raw = (ROOT / path).read_bytes()
    uploaded = c.post(f'/api/eval/executions/{eid}/files?filename=Nbal_out.xls',
                      headers=headers('dev'), content=raw)
    assert uploaded.json()['events'][-1].get('error') is None
    assert ask(c, eid, '硝态氮最大值', name='dev').status_code == 200
    saved = c.post('/api/eval/regressions', headers=headers('dev'), json={
        'execution_id': eid, 'title': 'Catalog fixture baseline'}).json()
    result = replay_and_wait(c, saved['regression_id'])
    assert result['state'] == 'completed', result
    compared = c.get(f"/api/eval/replays/{result['replay_id']}/comparison",
                     headers=headers('dev')).json()
    assert compared['pairs'][0]['changes'] == []


def test_manual_steps_pause_after_automatic_prefix_without_review(regression_client):
    c = regression_client
    saved = baseline(c, manual=True)
    result = replay_and_wait(c, saved['regression_id'])
    assert result['state'] == 'blocked' and result['execution_id']
    assert result['completed_steps'] == 2 and result['total_steps'] == 3
    assert result['blocked_step']['step'] == 3 and result['blocked_step']['action'] == 'manual'
    assert '人工' in result['message']
    candidate = c.get('/api/eval/executions/'+result['execution_id'], headers=headers('dev')).json()
    assert len(candidate['events']) == 2 and candidate['review'] is None
    assert all(a['run_id'] != b['run_id'] for a, b in zip(candidate['events'], saved['baseline']['events']))


def test_three_runs_are_saved_before_fourth_manual_step(regression_client):
    c = regression_client
    eid = start(c, name='dev', case='NEW01', version=2)
    for query in ('你好', '你能做什么？', '1'):
        ask(c, eid, query, name='dev')
    c.post(f'/api/eval/executions/{eid}/actions', headers=headers('dev'), json={'action': 'manual', 'note': '人工缩小浏览器窗口'})
    saved = c.post('/api/eval/regressions', headers=headers('dev'), json={'execution_id': eid, 'title': '逐步重放'}).json()
    result = replay_and_wait(c, saved['regression_id'])
    assert (result['state'], result['completed_steps'], result['blocked_step']['step']) == ('blocked', 3, 4)
    candidate = c.get('/api/eval/executions/'+result['execution_id'], headers=headers('dev')).json()
    assert len(candidate['events']) == 3 and candidate['review'] is None
    assert len({event['run_id'] for event in candidate['events']}) == 3
    compared = c.get(f"/api/eval/replays/{result['replay_id']}/comparison", headers=headers('dev')).json()
    assert len(compared['pairs']) == 3 and compared['baseline_review'] is None and compared['candidate_review'] is None


def test_changed_fixture_blocks_instead_of_substituting_data(regression_client, tmp_path):
    c = regression_client
    saved = baseline(c, file=True)
    path = tmp_path/'changed.xls'
    path.write_bytes(b'changed')
    # Substitute a registered path in an isolated store, never modify real data.
    c.app.state.evaluation.store.fixtures['Nbal_out.xls']['path'] = str(path)
    result = replay_and_wait(c, saved['regression_id'])
    assert result['state'] == 'blocked' and result['execution_id'] is None
    assert result['blocked_step']['step'] == 1


def test_regression_endpoints_are_developer_only(regression_client):
    c = regression_client
    saved = baseline(c)
    for path in ('/regressions', '/regressions/'+saved['regression_id'], '/replays/unknown/comparison'):
        assert c.get('/api/eval'+path, headers=headers()).status_code == 403
    assert c.post('/api/eval/regressions', headers=headers(), json={'execution_id': saved['baseline']['execution_id'], 'title': 'x'}).status_code == 403
    assert c.post('/api/eval/regressions/'+saved['regression_id']+'/replays', headers=headers()).status_code == 403


def test_replay_differences_keep_errors_separate_from_success(regression_client):
    c = regression_client
    eid = start(c, name='dev', case='X01', version=2)
    ask(c, eid, '氮素淋失受哪些因素影响？', name='dev')
    saved = c.post('/api/eval/regressions', headers=headers('dev'), json={'execution_id': eid, 'title': 'upstream failed'}).json()
    result = replay_and_wait(c, saved['regression_id'])
    compared = c.get(f"/api/eval/replays/{result['replay_id']}/comparison", headers=headers('dev')).json()
    assert result['state'] == 'completed'  # Replaying the steps is not answering successfully.
    assert compared['pairs'][0]['candidate']['error']['code'] == 'rag_not_configured'
    assert compared['candidate_review'] is None


def test_restart_marks_unfinished_replays_interrupted(regression_client):
    c = regression_client
    svc = c.app.state.regressions
    with svc.store.lock, svc.store.db:
        svc.store.db.execute('INSERT INTO eval_replays VALUES (?,?,?,?)', ('orphan', 'baseline', 'time', json.dumps({'state': 'running'})))
    reopened = RegressionService(c.app.state.evaluation)
    assert reopened.replay('orphan')['state'] == 'interrupted'


def test_baseline_requires_a_query_and_nonblank_title(regression_client):
    c = regression_client
    eid = start(c, name='dev')
    assert c.post('/api/eval/regressions', headers=headers('dev'), json={'execution_id': eid, 'title': 'empty'}).status_code == 409
    assert c.post('/api/eval/regressions', headers=headers('dev'), json={'execution_id': eid, 'title': '  '}).status_code == 422


def test_active_replay_is_locked_and_can_be_cancelled(regression_client, monkeypatch):
    from src.api import evaluation
    c = regression_client
    saved = baseline(c)
    original = evaluation.query
    async def slow(*args):
        await asyncio.sleep(30)
        return await original(*args)
    monkeypatch.setattr(evaluation, 'query', slow)
    result = c.post('/api/eval/regressions/'+saved['regression_id']+'/replays', headers=headers('dev')).json()
    eid = result['execution_id']
    assert ask(c, eid, name='dev').status_code == 409
    assert c.post(f'/api/eval/executions/{eid}/reviews', headers=headers('dev'), json=score()).status_code == 409
    assert c.post(f"/api/eval/replays/{result['replay_id']}/cancel", headers=headers('dev')).status_code == 200
    async def wait():
        task = c.app.state.regressions.jobs.get(result['replay_id'])
        if task:
            await asyncio.gather(task, return_exceptions=True)
    c.portal.call(wait)
    assert c.get(f"/api/eval/replays/{result['replay_id']}", headers=headers('dev')).json()['state'] == 'cancelled'
    assert not c.app.state.regressions.jobs and not c.app.state.evaluation.replay_owners
