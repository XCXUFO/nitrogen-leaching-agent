import asyncio
import json
import time

import pytest

from src.api import case_tagging
from src.llm.base import ChatResult, ChatUsage
from tests.test_case_tags import client, create, dimension, tag  # noqa: F401
from tests.literature_fixture import TOKENS


class LLM:
    def __init__(self, tags):
        self.tags = tags
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(json.loads(messages[1].content))
        assert '农业案例与措施分类助手' in messages[0].content
        return ChatResult(content=json.dumps({'tag_ids': self.tags}), model='test', usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


def setup(client):
    dim = dimension(client, selection='single')
    a, b = tag(client, dim, '玉米'), tag(client, dim, '小麦')
    client.app.state.llm = LLM([b])
    return a, b


def run(client, ids):
    response = client.post('/api/case-library/tag-jobs', json={'case_ids': ids})
    assert response.status_code == 202, response.text
    return client.get('/api/case-library/tag-jobs/' + response.json()['id']).json()


def test_batch_replaces_tags_and_preserves_content_and_availability(client):
    a, b = setup(client)
    first, second = create(client, [a]).json(), create(client, title='另一案例').json()
    job = run(client, [first['id'], second['id']])
    assert all(item['status'] == 'ready' for item in job['items'])
    for original in (first, second):
        saved = client.get('/api/case-library/' + original['id']).json()
        assert saved['tag_ids'] == [b] and saved['revision'] == 2
        for key in ('title', 'body', 'body_format', 'explanation', 'source', 'supplementary', 'enabled'):
            assert saved[key] == original[key]
    assert client.app.state.llm.calls[0]['selected_tag_ids'] == []
    assert client.app.state.llm.calls[0]['case_text'] == first['body']
    assert client.get('/api/case-library/tag-jobs').json()['items'][0]['id'] == job['id']
    for path in ('', '/' + job['id']):
        response = client.get('/api/case-library/tag-jobs' + path, headers={'Authorization': f"Bearer {TOKENS['reviewer']}"})
        assert response.json() == {'items': []} if not path else response.status_code == 404
    assert client.post('/api/case-library/tag-jobs/' + job['id'] + '/retry', headers={'Authorization': f"Bearer {TOKENS['reviewer']}"}).status_code == 403


def test_partial_failure_retry_never_reprocesses_success(client):
    a, b = setup(client)
    first, second = create(client, [a], title='成功').json(), create(client, [a], title='失败').json()
    original = client.app.state.llm.chat
    async def partial(messages, **kwargs):
        if json.loads(messages[1].content)['fields']['title'] == '失败':
            raise ValueError('bad model response')
        return await original(messages, **kwargs)
    client.app.state.llm.chat = partial
    job = run(client, [first['id'], second['id']])
    assert [item['status'] for item in job['items']] == ['ready', 'failed']
    assert client.get('/api/case-library/' + second['id']).json()['tag_ids'] == [a]
    client.app.state.llm.chat = original
    assert client.post('/api/case-library/tag-jobs/' + job['id'] + '/retry').status_code == 202
    assert client.get('/api/case-library/' + first['id']).json()['revision'] == 2
    assert client.get('/api/case-library/' + second['id']).json()['tag_ids'] == [b]


@pytest.mark.parametrize('deleted', [False, True])
def test_edit_or_delete_during_ai_is_not_overwritten(client, deleted):
    a, _ = setup(client)
    item = create(client, [a]).json()
    original = client.app.state.llm.chat
    async def modified(messages, **kwargs):
        client.app.state.case_library.change(item['id'], 1, {'deleted': 1} if deleted else {'title': '人工修改'}, 'human')
        return await original(messages, **kwargs)
    client.app.state.llm.chat = modified
    job = run(client, [item['id']])
    assert job['items'][0]['status'] == 'conflict' and not job['items'][0]['retryable']
    response = client.get('/api/case-library/' + item['id'])
    if deleted:
        assert response.status_code == 404
    else:
        assert response.json()['title'] == '人工修改' and response.json()['tag_ids'] == [a]


def test_validation_and_ai_preflight(client):
    a, _ = setup(client)
    item = create(client, [a]).json()
    for ids in ([], [item['id']] * 101, [item['id'], item['id'].lower()], ['invalid']):
        assert client.post('/api/case-library/tag-jobs', json={'case_ids': ids}).status_code == 422
    assert client.post('/api/case-library/tag-jobs', json={'case_ids': [item['id']]}, headers={'Authorization': ''}).status_code == 401
    assert client.post('/api/case-library/tag-jobs', json={'case_ids': [item['id'], 'C-0000000000000000']}).status_code == 404
    client.app.state.llm = None
    assert client.post('/api/case-library/tag-jobs', json={'case_ids': [item['id']]}).status_code == 503
    assert client.get('/api/case-library/tag-jobs').json()['items'] == []


def test_interrupted_jobs_resume_after_timeout(client, monkeypatch):
    a, _ = setup(client)
    item = create(client, [a]).json()
    real_process = case_tagging.process_job
    async def stopped(*args):
        pass
    monkeypatch.setattr(case_tagging, 'process_job', stopped)
    job = run(client, [item['id']])
    assert job['items'][0]['status'] == 'queued' and not job['items'][0]['retryable']
    db = client.app.state.case_library
    with case_tagging.transaction(db):
        job['items'][0]['updated_at'] = time.time() - 600
        case_tagging.write_job(db, job)
    assert client.get('/api/case-library/tag-jobs/' + job['id']).json()['items'][0]['retryable']
    monkeypatch.setattr(case_tagging, 'process_job', real_process)
    assert client.post('/api/case-library/tag-jobs/' + job['id'] + '/retry').status_code == 202
    assert client.get('/api/case-library/tag-jobs/' + job['id']).json()['items'][0]['status'] == 'ready'


def test_parallelism_is_bounded_and_invalid_labels_are_filtered(client):
    a, b = setup(client)
    client.app.state.llm.tags = ['unknown', b, a]
    active = peak = 0
    original = client.app.state.llm.chat
    async def delayed(messages, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        result = await original(messages, **kwargs)
        active -= 1
        return result
    client.app.state.llm.chat = delayed
    cases = [create(client, [a], title=str(i)).json() for i in range(8)]
    job = run(client, [case['id'] for case in cases])
    assert peak == 3 and all(item['status'] == 'ready' for item in job['items'])
    assert all(client.get('/api/case-library/' + case['id']).json()['tag_ids'] == [b] for case in cases)


def test_stale_worker_cannot_save_after_attempt_is_replaced(client):
    a, _ = setup(client)
    item = create(client, [a]).json()
    original = client.app.state.llm.chat
    async def superseded(messages, **kwargs):
        db = client.app.state.case_library
        with case_tagging.transaction(db):
            row = db.db.execute('SELECT data FROM case_tag_jobs').fetchone()
            job = json.loads(row[0])
            job['items'][0].update(attempt='replacement-worker', status='processing')
            case_tagging.write_job(db, job)
        return await original(messages, **kwargs)
    client.app.state.llm.chat = superseded
    job = run(client, [item['id']])
    assert job['items'][0]['attempt'] == 'replacement-worker'
    assert job['items'][0]['status'] == 'processing'
    saved = client.get('/api/case-library/' + item['id']).json()
    assert saved['revision'] == 1 and saved['tag_ids'] == [a]
