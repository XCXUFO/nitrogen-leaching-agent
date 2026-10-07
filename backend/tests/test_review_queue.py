import hashlib

from src.evaluation.contracts import AccessFile
from tests.test_evaluation import client, headers, score, start


def test_expert_assignment_disagreement_and_versioned_resolution(client):
    second_key = 'f' * 40
    users = [u.model_dump() for u in client.app.state.eval_access.users]
    users.append({'tester_id': 'expert2', 'role': 'reviewer', 'token_sha256': hashlib.sha256(second_key.encode()).hexdigest()})
    client.app.state.eval_access = AccessFile(users=users)
    eid = start(client)
    path = f'/api/eval/review-queue/{eid}'
    queue = client.get('/api/eval/review-queue', headers=headers('dev')).json()
    assert next(item for item in queue if item['execution_id'] == eid)['status'] == 'pending_development'
    assert client.post(path + '/assignments', headers=headers('dev'), json={'reviewer_id': 'expert'}).status_code == 422
    assert client.post(f'/api/eval/executions/{eid}/reviews', headers=headers(), json={
        **score(), 'overall': 'blocked', 'route_correct': 'n.a.', 'answer_correct': 'n.a.',
        'notes': 'synthetic blocked review'}).status_code == 201
    assert client.get('/api/eval/review-queue', headers=headers()).status_code == 403
    assert client.post(path + '/assignments', headers=headers('dev'), json={'reviewer_id': 'alice'}).status_code == 422
    for name in ('expert', 'expert2'):
        assert client.post(path + '/assignments', headers=headers('dev'), json={'reviewer_id': name}).status_code == 201
    assert client.post(path + '/assignments', headers=headers('dev'), json={'reviewer_id': 'expert'}).status_code == 409
    def stage():
        return next(item for item in client.get('/api/eval/review-queue', headers=headers('expert')).json()
                    if item['execution_id'] == eid)
    assert stage()['status'] == 'pending_expert' and len(stage()['pending_reviewers']) == 2
    def assess(key, overall):
        return client.post('/api/eval/assessments', headers={'Authorization': 'Bearer '+key}, json={
            'case_id': 'NEW01', 'case_version': 2, 'kind': 'domain_expert', 'overall': overall,
            'source_path': 'isolated evidence', 'source_sha256': 'a' * 64,
            'notes': 'synthetic expert judgment only', 'execution_id': eid})
    assert assess('e'*40, 'pass').status_code == 201
    assert stage()['status'] == 'pending_expert' and stage()['pending_reviewers'] == ['expert2']
    assert assess(second_key, 'fail').status_code == 201
    disputed = stage()
    assert disputed['status'] == 'expert_disagreement'
    ids = [item['assessment_id'] for item in disputed['expert_assessments']]
    assert client.post(path + '/resolutions', headers=headers('dev'), json={
        'assessment_ids': ids, 'conclusion': 'unresolved', 'rationale': 'two views'}).status_code == 403
    assert client.post(path + '/resolutions', headers=headers('expert'), json={
        'assessment_ids': [ids[0], 'stale'], 'conclusion': 'unresolved', 'rationale': 'two views'}).status_code == 409
    resolved = client.post(path + '/resolutions', headers=headers('expert'), json={
        'assessment_ids': ids, 'conclusion': 'unresolved', 'rationale': 'Need another source before deciding'})
    assert resolved.status_code == 201
    assert stage()['status'] == 'resolved_disagreement'
    assert stage()['resolution']['conclusion'] == 'unresolved'
    assert client.get('/api/eval/review-queue?status=expert_disagreement', headers=headers('dev')).json() == []
    assert assess(second_key, 'partial').status_code == 201
    assert stage()['status'] == 'expert_disagreement' and stage()['resolution'] is None
