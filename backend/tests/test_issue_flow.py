from tests.test_evaluation import client, headers, ask, score, start
from tests.test_evaluation_integrity import issue_from_failed_execution


def test_issue_flow_history_filters_and_concurrent_edits(client):
    _, issue = issue_from_failed_execution(client)
    url = f'/api/eval/issues/{issue["issue_id"]}'
    saved = client.get(url, headers=headers('dev')).json()
    assert saved['status'] == 'open' and saved['revision'] == 1
    assert len(saved['history']) == 1
    body = {'expected_revision': 1, 'status': 'closed', 'assignee': 'dev', 'note': 'want to close'}
    assert client.patch(url, headers=headers(), json=body).status_code == 403
    wrong = client.patch(url, headers=headers('dev'), json=body)
    assert wrong.status_code == 422 and wrong.json()['detail']['code'] == 'issue_transition_invalid'
    body['status'] = 'in_progress'
    progress = client.patch(url, headers=headers('dev'), json=body).json()
    assert progress['revision'] == 2 and progress['status'] == 'in_progress'
    assert len(progress['history']) == 2
    stale = client.patch(url, headers=headers('dev'), json=body)
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'issue_revision_conflict'
    body.update(expected_revision=2, status='ready_for_retest', assignee='another-dev', note='ready')
    ready = client.patch(url, headers=headers('dev'), json=body).json()
    assert ready['assignee'] == 'another-dev'
    body.update(expected_revision=3, status='closed', note='no retest')
    assert client.patch(url, headers=headers('dev'), json=body).json()['detail']['code'] == 'issue_pass_retest_required'
    assert client.get('/api/eval/issues?status=ready_for_retest&assignee=another-dev', headers=headers('dev')).json()[0]['issue_id'] == issue['issue_id']
    assert client.get('/api/eval/issues?status=closed', headers=headers('dev')).json() == []
    assert client.get('/api/eval/issues?status=made-up', headers=headers('dev')).status_code == 422
    assert len(client.get(url, headers=headers('dev')).json()['history']) == 3


def test_retest_auto_closes_and_later_failure_reopens_with_history(client):
    _, issue = issue_from_failed_execution(client)
    url = f'/api/eval/issues/{issue["issue_id"]}'
    for overall, expected in [('pass', 'closed'), ('fail', 'in_progress')]:
        eid = start(client)
        ask(client, eid, '你好')
        result = client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json=(
            score() if overall == 'pass' else score(overall='fail', answer_correct='no', notes='synthetic relapse')))
        assert result.status_code == 201
        linked = client.post(url + '/retests', headers=headers('dev'), json={
            'execution_id': eid, 'fix_version': 'unconfigured'})
        assert linked.status_code == 201
        latest = client.get(url, headers=headers('dev')).json()
        assert latest['status'] == expected
        assert latest['history'][-1]['action'] == 'retest_linked'
        assert latest['history'][-1]['retest_id'] == linked.json()['retest_id']
    assert len(client.get(url, headers=headers('dev')).json()['retests']) == 2
