from __future__ import annotations

import time
from uuid import uuid4

from tests.test_evaluation import client, headers  # noqa: F401
from src.storage.run_store import RunStore


def conversation(client, session='review-chat', query='你好', history=None):
    result = client.post('/api/chat', json={'session_id': session, 'query': query, 'history': history or []})
    assert result.status_code == 200, result.text
    return client.get('/api/eval/sessions/' + session, headers=headers('dev')).json()


def review(client, session, action, person='dev', **fields):
    return client.post('/api/eval/sessions/' + session['session_id'] + '/reviews', headers=headers(person), json={
        'action_id': str(uuid4()), 'action': action, 'expected_revision': session['review']['revision'], **fields})


def test_single_person_can_approve_without_scores_and_later_turns_remain_pending(client):
    session = conversation(client)
    assert session['review_status'] == 'pending'
    saved = review(client, session, 'pass', run_ids=[session['turns'][0]['run_id']])
    assert saved.status_code == 200, saved.text
    assert saved.json()['review_status'] == 'passed'
    assert saved.json()['review']['history'][0]['review_kind'] == 'human'
    assert client.get('/api/eval/sessions?review_status=pending', headers=headers('dev')).json()['total'] == 0
    session = conversation(client, query='你能做什么？', history=[{'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '你好'}])
    assert session['review_status'] == 'pending' and session['reviewed_turn_count'] == 1
    # Approving an older open tab cannot approve the newly appended answer.
    saved = review(client, session, 'pass', run_ids=[session['turns'][0]['run_id']]).json()
    assert saved['review_status'] == 'pending' and saved['reviewed_turn_count'] == 1


def test_shared_issue_comment_manual_resolution_and_reopening_preserve_original(client):
    session = conversation(client)
    original = session['turns'][0]
    saved = review(client, session, 'issue', person='alice', run_id=original['run_id'], note='解释不完整，应补充适用条件。')
    assert saved.status_code == 200, saved.text
    session = saved.json()
    issue = session['review']['issues'][0]
    assert session['review_status'] == 'needs_changes'
    assert client.get('/api/eval/sessions?review_status=needs_changes', headers=headers('expert')).json()['total'] == 1
    assert review(client, session, 'pass', run_ids=[original['run_id']]).status_code == 409
    session = review(client, session, 'comment', person='expert', note='已核对原文，建议采用师兄补充的条件。').json()
    assert session['review']['history'][-1]['recorded_by'] == 'expert'
    assert review(client, session, 'resolve', issue_id=issue['issue_id']).status_code == 422
    session = review(client, session, 'resolve', issue_id=issue['issue_id'], note='已修改案例解释，并在前台用原文件核对。').json()
    session = review(client, session, 'pass', run_ids=[original['run_id']]).json()
    assert session['review_status'] == 'passed' and session['turns'][0] == original
    session = review(client, session, 'reopen', person='expert', issue_id=issue['issue_id'], note='新发现一个条件遗漏。').json()
    assert session['review_status'] == 'needs_changes'
    assert len(session['review']['history']) == 5


def test_conflicts_idempotency_membership_and_authentication(client):
    session = conversation(client)
    payload = {'action_id': str(uuid4()), 'expected_revision': 0, 'action': 'comment', 'note': '人工复核'}
    url = '/api/eval/sessions/review-chat/reviews'
    assert client.post(url, json=payload).status_code == 401
    for _ in range(2):
        assert client.post(url, headers=headers('dev'), json=payload).json()['review']['revision'] == 1
    assert client.post(url, headers=headers('alice'), json=payload).status_code == 409
    assert review(client, session, 'comment', note='过期表单').status_code == 409
    session = client.get('/api/eval/sessions/review-chat', headers=headers('alice')).json()
    assert review(client, session, 'issue', run_id='another-run', note='问题').status_code == 422
    assert review(client, session, 'pass', run_ids=['another-run']).status_code == 409
    assert review(client, session, 'issue', run_id=session['turns'][0]['run_id'], note='   ').status_code == 422
    assert review(client, session, 'comment', note='意见', recorded_by='someone').status_code == 422


def test_retest_uses_original_request_and_keeps_human_confirmation_separate(client):
    session = conversation(client)
    original = session['turns'][0]
    session = review(client, session, 'issue', run_id=original['run_id'], note='修改后检查回答。').json()
    issue_id = session['review']['issues'][0]['issue_id']
    payload = {'submission_id': str(uuid4()), 'source_run_id': original['run_id'], 'issue_id': issue_id}
    for _ in range(2):
        result = client.post('/api/eval/sessions/review-chat/retests', headers=headers('alice'), json=payload)
        assert result.status_code == 202, result.text
    for _ in range(100):
        session = client.get('/api/eval/sessions/review-chat', headers=headers('expert')).json()
        if session['review']['retests'][0]['status'] not in {'accepted', 'running'}:
            break
        time.sleep(.01)
    assert len(session['review']['retests']) == 1
    verification = session['review']['retests'][0]
    assert verification['status'] == 'succeeded' and verification['answer']
    assert session['review_status'] == 'needs_changes'
    assert session['turns'] == [original]
    trace = client.app.state.agent_runtime.runs.get(verification['run_id'])
    assert trace.source == 'test' and trace.replay_of_run_id == original['run_id']
    assert trace.request_snapshot['query'] == original['input']
    assert client.get('/api/eval/sessions', headers=headers('dev')).json()['total'] == 1
    assert review(client, session, 'resolve', issue_id=issue_id, verification_run_id=original['run_id']).status_code == 422
    session = review(client, session, 'resolve', issue_id=issue_id, verification_run_id=verification['run_id']).json()
    assert session['review']['issues'][0]['status'] == 'resolved'


def test_incomplete_or_attachment_requests_require_original_materials(client):
    session = conversation(client)
    store = client.app.state.agent_runtime.runs
    # Do not invent a file capability or silently turn a file question into a text-only replay.
    with store._lock, store._connection:
        store._connection.execute("UPDATE agent_runs SET payload=json_set(payload,'$.request_snapshot.has_attachments',json('true'))")
    response = client.post('/api/eval/sessions/review-chat/retests', headers=headers('dev'), json={
        'submission_id': str(uuid4()), 'source_run_id': session['turns'][0]['run_id']})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'retest_files_required'
    assert store.live.db.execute('SELECT COUNT(*) FROM chat_submissions').fetchone()[0] == 0


def test_review_survives_reopening_database(client, tmp_path):
    session = conversation(client)
    review(client, session, 'pass', run_ids=[session['turns'][0]['run_id']])
    reopened = RunStore(tmp_path / 'runs.sqlite3')
    try:
        assert reopened.session('review-chat')['review_status'] == 'passed'
        assert reopened.sessions(review_status='passed')['total'] == 1
    finally:
        reopened.close()


def test_status_filter_is_applied_before_pagination(client):
    session = conversation(client, session='older')
    review(client, session, 'pass', run_ids=[session['turns'][0]['run_id']])
    conversation(client, session='newer')
    result = client.get('/api/eval/sessions?review_status=passed&limit=1', headers=headers('alice')).json()
    assert result['total'] == 1 and result['items'][0]['session_id'] == 'older'


def test_retest_keeps_original_text_history(client):
    history = [{'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '你好，有什么问题？'}]
    session = conversation(client, query='你能做什么？', history=history)
    source = session['turns'][0]['run_id']
    result = client.post('/api/eval/sessions/review-chat/retests', headers=headers('dev'), json={
        'submission_id': str(uuid4()), 'source_run_id': source})
    assert result.status_code == 202
    for _ in range(100):
        current = client.get('/api/eval/sessions/review-chat', headers=headers('dev')).json()
        if current['review']['retests'][0]['status'] not in {'accepted', 'running'}:
            break
        time.sleep(.01)
    trace = client.app.state.agent_runtime.runs.get(current['review']['retests'][0]['run_id'])
    assert trace.history_count == 2 and trace.request_snapshot['history'] == history


def test_failed_verification_cannot_resolve_a_problem(client):
    assert client.post('/api/chat', json={'session_id': 'review-failed', 'query': '氮素淋失是什么？'}).status_code == 503
    session = client.get('/api/eval/sessions/review-failed', headers=headers('dev')).json()
    session = review(client, session, 'issue', run_id=session['turns'][0]['run_id'], note='需要修复检索配置').json()
    issue_id = session['review']['issues'][0]['issue_id']
    response = client.post('/api/eval/sessions/review-failed/retests', headers=headers('dev'), json={
        'submission_id': str(uuid4()), 'source_run_id': session['turns'][0]['run_id'], 'issue_id': issue_id})
    assert response.status_code == 202
    for _ in range(100):
        session = client.get('/api/eval/sessions/review-failed', headers=headers('dev')).json()
        if session['review']['retests'][0]['status'] not in {'accepted', 'running'}:
            break
        time.sleep(.01)
    verification = session['review']['retests'][0]
    assert verification['status'] == 'failed'
    assert review(client, session, 'resolve', issue_id=issue_id, verification_run_id=verification['run_id']).status_code == 422
    assert session['review_status'] == 'needs_changes'
