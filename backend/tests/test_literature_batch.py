import json

import pytest
from fastapi.testclient import TestClient

from src.llm.base import ChatResult, ChatUsage
from tests.literature_fixture import TOKENS, create_app
from tests.test_literature_extract import pdf_bytes


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.headers['Authorization'] = f"Bearer {TOKENS['tester']}"
        yield client
    app.state.literature.close()


def upload(client, text='Nitrogen leaching in maize fields. Irrigation affected nitrogen losses.'):
    response = client.post('/api/literature/uploads?filename=paper.pdf', content=pdf_bytes(text))
    assert response.status_code == 200
    return response.json()['upload_id']


def batch(client, **kwargs):
    response = client.post('/api/literature/imports', json=kwargs)
    assert response.status_code == 202, response.text
    return client.get('/api/literature/imports').json()['items'][0]


def test_limits_and_ownership_before_consuming_uploads(client):
    identifier = upload(client)
    for ids in ([], [identifier] * 101, [identifier, identifier]):
        assert client.post('/api/literature/imports', json={'upload_ids': ids}).status_code == 422
    assert client.post('/api/literature/imports', json={'upload_ids': [identifier]},
                       headers={'Authorization': f"Bearer {TOKENS['reviewer']}"}).status_code == 404
    assert client.post('/api/literature/imports', json={'upload_ids': [identifier]},
                       headers={'Authorization': ''}).status_code == 401
    result = batch(client, upload_ids=[identifier], ai_extract=False, ai_tag=False)
    assert result['items'][0]['status'] == 'ready'
    paper = client.get('/api/literature/papers/' + result['items'][0]['paper_id']).json()
    assert paper['registration'] == 'draft'
    assert client.get('/api/literature/imports', headers={'Authorization': f"Bearer {TOKENS['reviewer']}"}).json()['items'] == []
    assert client.post(f"/api/literature/imports/{result['id']}/retry",
                       headers={'Authorization': f"Bearer {TOKENS['reviewer']}"}).status_code == 404


def test_default_ai_applies_fields_and_tags(client):
    dim = client.post('/api/literature/dimensions', json={'name': '主题'}).json()['id']
    tag = client.post(f'/api/literature/dimensions/{dim}/tags', json={'name': '氮素淋失'}).json()['id']

    class LLM:
        async def chat(self, messages, **kwargs):
            content = {'tag_ids': [tag]} if 'taxonomy' in messages[1].content else {
                'title': 'AI title', 'conclusion': 'Reduced nitrogen leaching.', 'abstract': 'Study abstract.'}
            return ChatResult(content=json.dumps(content), model='test', usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    client.app.state.llm = LLM()
    result = batch(client, upload_ids=[upload(client), upload(client, 'Second paper on nitrate losses. Field observations of agricultural nitrogen.')])
    assert result['ai_extract'] and result['ai_tag']
    for item in result['items']:
        assert item['status'] == 'ready', item
        paper = client.get('/api/literature/papers/' + item['paper_id']).json()
        assert paper['title'] == 'AI title'
        assert paper['conclusion'] == 'Reduced nitrogen leaching.'
        assert paper['tag_ids'] == [tag]
        assert paper['registration'] == 'draft'


def test_duplicate_and_ai_failure_preserve_other_papers(client):
    raw = pdf_bytes('Same paper content')
    ids = [client.post('/api/literature/uploads?filename=paper.pdf', content=raw).json()['upload_id'] for _ in range(2)]
    ids.append(upload(client, 'Another research paper'))
    result = batch(client, upload_ids=ids)
    assert [item['status'] for item in result['items']] == ['warning', 'duplicate', 'warning']
    assert client.get('/api/literature/papers').json()['total'] == 2
    assert all(item.get('paper_id') for item in result['items'])
    # Human edits after processing must not be overwritten by retry.
    item = result['items'][0]
    path = '/api/literature/papers/' + item['paper_id']
    paper = client.get(path).json()
    assert client.put(path, json={**paper, 'title': 'Human title'}).status_code == 200
    assert client.post(f"/api/literature/imports/{result['id']}/retry").status_code == 202
    assert client.get(path).json()['title'] == 'Human title'
    updated = client.get('/api/literature/imports').json()['items'][0]
    assert updated['items'][0]['status'] == 'failed'


def test_hundred_papers_and_idempotent_submission(client):
    identifiers = [upload(client, f'Paper {index}: Nitrogen leaching in agricultural soils.') for index in range(100)]
    body = {'upload_ids': identifiers, 'ai_extract': False, 'ai_tag': False}
    first = batch(client, **body)
    assert len(first['items']) == 100
    assert all(item['status'] == 'ready' for item in first['items'])
    repeated = client.post('/api/literature/imports', json=body)
    assert repeated.status_code == 202
    assert repeated.json()['id'] == first['id']
    assert client.get('/api/literature/papers').json()['total'] == 100


@pytest.mark.parametrize('ai_extract,ai_tag', [(True, False), (False, True), (True, True)])
@pytest.mark.parametrize('registered', [False, True])
def test_existing_papers_independent_ai_options_and_overwrite(client, monkeypatch, ai_extract, ai_tag, registered):
    from src.api import literature_batch
    dim = client.post('/api/literature/dimensions', json={'name': '作物', 'selection': 'single'}).json()['id']
    old_tag, new_tag = [client.post(f'/api/literature/dimensions/{dim}/tags', json={'name': name}).json()['id']
                        for name in ('小麦', '玉米')]
    paper = client.post('/api/literature/papers', json={
        'upload_id': upload(client), 'title': 'Old title', 'tag_ids': [old_tag],
        'authors_unknown': True, 'publication_type': '期刊论文', 'venue_unknown': True,
        'year_unknown': True, 'language': '英文', 'source_note': 'Archive',
        'action': 'register' if registered else 'draft',
    }).json()
    calls = []

    async def extract(request, target, user):
        calls.append('extract')
        assert target.paper_id == paper['id']
        return {'fields': {'title': 'New title', 'authors': [{'name': 'Li', 'kind': 'person'}],
                           'venue': 'Journal', 'year': 2024, 'conclusion': 'New conclusion'}, 'warning': ''}

    async def tags(request, target, user):
        calls.append('tag')
        assert target.tag_ids == []  # Explicit batch overwrite can change a single-choice dimension.
        assert target.title == ('New title' if ai_extract else 'Old title')
        return {'tag_ids': [new_tag]}

    monkeypatch.setattr(literature_batch, 'extract_paper_fields', extract)
    monkeypatch.setattr(literature_batch, 'suggest_paper_tags', tags)
    response = client.post('/api/literature/batch-ai', json={'paper_ids': [paper['id']], 'ai_extract': ai_extract, 'ai_tag': ai_tag})
    assert response.status_code == 202, response.text
    result = client.get('/api/literature/papers/' + paper['id']).json()
    assert result['title'] == ('New title' if ai_extract else 'Old title')
    assert result['authors_unknown'] == (not ai_extract)
    assert result['tag_ids'] == ([new_tag] if ai_tag else [old_tag])
    assert result['registration'] == paper['registration']
    assert result['registered_at'] == paper['registered_at']
    assert calls == (['extract'] if ai_extract else []) + (['tag'] if ai_tag else [])
    receipt = client.get('/api/literature/imports').json()['items'][0]
    assert receipt['kind'] == 'existing'
    assert receipt['items'][0]['status'] == 'ready'


def test_existing_batch_validation_and_concurrent_edit(client, monkeypatch):
    from src.api import literature_batch
    paper = client.post('/api/literature/papers', json={'upload_id': upload(client), 'title': 'Original'}).json()
    path = '/api/literature/batch-ai'
    for ids in ([], [paper['id']] * 101, [paper['id'], paper['id']]):
        assert client.post(path, json={'paper_ids': ids}).status_code == 422
    assert client.post(path, json={'paper_ids': [paper['id']], 'ai_extract': False, 'ai_tag': False}).status_code == 422
    assert client.post(path, json={'paper_ids': [paper['id'], 'missing']}).status_code == 404
    assert client.post(path, json={'paper_ids': [paper['id']]}, headers={'Authorization': ''}).status_code == 401
    assert client.get('/api/literature/imports').json()['items'] == []

    async def extract(request, target, user):
        from src.api.literature import PaperUpdateInput, update_paper
        update_paper(request, paper['id'], PaperUpdateInput(**{**paper, 'title': 'Human edit'}, expected_revision=paper['revision']), user)
        return {'fields': {'title': 'Late AI output'}, 'warning': ''}

    monkeypatch.setattr(literature_batch, 'extract_paper_fields', extract)
    assert client.post(path, json={'paper_ids': [paper['id']], 'ai_tag': False}).status_code == 202
    assert client.get('/api/literature/papers/' + paper['id']).json()['title'] == 'Human edit'
    assert client.get('/api/literature/imports').json()['items'][0]['items'][0]['status'] == 'failed'


def test_current_batch_and_targeted_retry(client, monkeypatch):
    import src.api.literature_batch as module
    result = batch(client, upload_ids=[upload(client, 'First paper'), upload(client, 'Second paper')], ai_extract=False, ai_tag=False)
    identifier = result['id']
    assert client.get(f'/api/literature/imports/{identifier}').json()['id'] == identifier
    assert client.get(f'/api/literature/imports/{identifier}', headers={'Authorization': f"Bearer {TOKENS['reviewer']}"}).status_code == 404
    db = client.app.state.literature
    with db.write():
        for item in result['items']:
            item['status'] = 'warning'
        module.write_batch(db, result)
    async def no_processing(*args):
        pass
    monkeypatch.setattr(module, 'process_batch', no_processing)
    response = client.post(f'/api/literature/imports/{identifier}/retry', json={'paper_ids': [result['items'][0]['paper_id']]})
    assert response.status_code == 202
    assert [item['status'] for item in response.json()['items']] == ['queued', 'warning']
    assert client.post(f'/api/literature/imports/{identifier}/retry', json={'paper_ids': ['unknown']}).status_code == 422


def test_interrupted_queue_can_resume_without_reprocessing_success(client, monkeypatch):
    import time
    from datetime import datetime, timezone
    from src.api import literature_batch as module
    real_process = module.process_batch
    async def interrupted(*args):
        pass
    monkeypatch.setattr(module, 'process_batch', interrupted)
    result = batch(client, upload_ids=[upload(client, f'Paper {i}') for i in range(4)], ai_extract=False, ai_tag=False)
    assert not any(item['retryable'] for item in result['items'])
    db = client.app.state.literature
    # Simulate a restart with one completed item, one claimed item and two queued.
    result['created_at'] = datetime.fromtimestamp(time.time() - 600, timezone.utc).isoformat()
    result['items'][0]['status'] = 'ready'
    result['items'][1].update(status='processing', started_at=time.time() - 600)
    with db.write():
        module.write_batch(db, result)
    path = f"/api/literature/imports/{result['id']}"
    receipt = client.get(path).json()
    assert [item['retryable'] for item in receipt['items']] == [False, True, True, True]
    monkeypatch.setattr(module, 'process_batch', real_process)
    assert client.post(path + '/retry').status_code == 202
    receipt = client.get(path).json()
    assert all(item['status'] == 'ready' for item in receipt['items'])
    assert receipt['items'][0]['revision'] == 1
    assert all(item['revision'] == 2 for item in receipt['items'][1:])
