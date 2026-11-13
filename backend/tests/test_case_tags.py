"""Cases share the literature taxonomy while retaining their own assignments."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api import case_library
from src.storage.case_library import CaseInput, CaseStore
from tests.literature_fixture import TOKENS, create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    app.state.case_library = CaseStore(str(tmp_path / 'cases.db'))
    app.include_router(case_library.router, prefix='/api')
    with TestClient(app) as client:
        client.headers['Authorization'] = f"Bearer {TOKENS['developer']}"
        yield client
    app.state.case_library.close()
    app.state.literature.close()


def dimension(client, name='作物', **kwargs):
    return client.post('/api/literature/dimensions', json={'name': name, **kwargs}).json()['id']


def tag(client, dimension_id, name, **kwargs):
    return client.post(f'/api/literature/dimensions/{dimension_id}/tags', json={'name': name, **kwargs}).json()['id']


def create(client, ids=(), title='玉米案例'):
    return client.post('/api/case-library', json={'title': title, 'body': '分次施肥', 'tag_ids': list(ids)})


def update(client, item, **kwargs):
    return client.put('/api/case-library/' + item['id'], json={**item, 'expected_revision': item['revision'], **kwargs})


def test_shared_catalog_roundtrip_filter_counts_and_old_clients(client):
    crop = dimension(client, selection='single', required=True)
    parent = tag(client, crop, '粮食作物')
    maize = tag(client, crop, '玉米', parent_id=parent)
    wheat = tag(client, crop, '小麦', parent_id=parent)
    method = dimension(client, '措施')
    irrigation = tag(client, method, '滴灌')
    first = create(client, [maize, irrigation]).json()
    second = create(client, [wheat], '小麦案例').json()
    blank = create(client, title='旧案例').json()  # Literature required dimensions do not apply.
    assert blank['tag_ids'] == []
    assert client.get('/api/case-library/' + first['id']).json()['tag_ids'] == [maize, irrigation]
    shared = client.get('/api/case-library/taxonomy').json()
    assert {item['id'] for item in shared['tags']} == {parent, maize, wheat, irrigation}
    result = client.get('/api/case-library', params={'tags': parent, 'page_size': 1}).json()
    assert result['total'] == 2 and len(result['items']) == 1
    result = client.get('/api/case-library', params={'tags': f'{maize},{wheat},{irrigation}'}).json()
    assert [item['id'] for item in result['items']] == [first['id']]
    assert client.get('/api/case-library?untagged=true').json()['items'][0]['id'] == blank['id']
    assert client.get('/api/case-library?tags=missing').status_code == 422
    # A pre-tag client updating only content must not erase assignments.
    legacy = client.put('/api/case-library/' + first['id'], json={'title': '新标题', 'body': '新正文', 'expected_revision': 1}).json()
    assert legacy['tag_ids'] == [maize, irrigation]
    assert update(client, first, tag_ids=[]).status_code == 409
    removed = update(client, legacy, tag_ids=[]).json()
    assert removed['tag_ids'] == []
    counts = {item['id']: item['case_count'] for item in client.get('/api/literature/taxonomy').json()['tags']}
    assert counts[wheat] == 1 and counts[maize] == 0
    assert client.request('DELETE', '/api/case-library/' + second['id'], json={'expected_revision': 1}).status_code == 200
    counts = {item['id']: item['case_count'] for item in client.get('/api/literature/taxonomy').json()['tags']}
    assert counts[wheat] == 0
    assert client.get('/api/case-library/taxonomy', headers={'Authorization': ''}).status_code == 401


def test_selection_validation_disabled_preservation_and_tag_deletion(client):
    crop = dimension(client, selection='single')
    maize = tag(client, crop, '玉米')
    wheat = tag(client, crop, '小麦')
    assert create(client, ['missing']).status_code == 400
    assert create(client, [maize, wheat]).json()['detail']['code'] == 'single_dimension'
    method = dimension(client, '措施', selection='multiple')
    parent = tag(client, method, '灌溉')
    child = tag(client, method, '滴灌', parent_id=parent)
    assert create(client, [parent, child]).json()['detail']['code'] == 'ancestor_conflict'
    assert create(client, [child, child]).json()['detail']['code'] == 'duplicate_tag'
    item = create(client, [maize]).json()
    assert client.put('/api/literature/tags/' + maize, json={'name': '玉米', 'enabled': False}).status_code == 200
    assert create(client, [maize]).status_code == 400
    item = update(client, item, title='仍保留停用标签').json()
    assert item['tag_ids'] == [maize]
    assert client.put('/api/literature/dimensions/' + crop, json={'name': '作物', 'selection': 'single', 'enabled': False}).status_code == 200
    assert create(client, [wheat]).status_code == 400
    response = client.delete('/api/literature/tags/' + maize)
    assert response.status_code == 200
    assert response.json()['detached_case_count'] == 1
    latest = client.get('/api/case-library/' + item['id']).json()
    assert latest['tag_ids'] == [] and latest['revision'] == item['revision'] + 1
    assert latest['body'] == item['body']
    assert update(client, item, tag_ids=[]).status_code == 409


def test_taxonomy_structure_changes_protect_assigned_cases(client):
    dim = dimension(client, selection='multiple')
    a, b = tag(client, dim, '甲'), tag(client, dim, '乙')
    item = create(client, [a, b]).json()
    assert client.put('/api/literature/dimensions/' + dim, json={'name': '作物', 'selection': 'single'}).status_code == 409
    assert client.put('/api/literature/tags/' + b, json={'name': '乙', 'parent_id': a}).status_code == 409
    assert update(client, item, tag_ids=[b]).status_code == 200
    assert client.put('/api/literature/tags/' + b, json={'name': '乙改名', 'parent_id': a}).status_code == 200
    assert client.put('/api/literature/dimensions/' + dim, json={'name': '作物', 'selection': 'single'}).status_code == 200
    catalog = client.get('/api/case-library/taxonomy').json()
    assert next(t for t in catalog['tags'] if t['id'] == b)['path'] == '甲 / 乙改名'


def test_case_tags_migration_preserves_original_revision_and_content(tmp_path):
    path = str(tmp_path / 'legacy.db')
    db = CaseStore(path)
    item = db.create(CaseInput(title='旧案例', body='原文', enabled=True), 'tester')
    db.close()
    with sqlite3.connect(path) as connection:
        connection.execute('ALTER TABLE reference_cases DROP COLUMN tag_ids')
    for _ in range(2):
        db = CaseStore(path)
        assert db.get(item['id']) == item
        assert db.list()['items'][0]['tag_ids'] == []
        db.close()


def test_full_content_and_tag_status_filters(client):
    crop = dimension(client)
    maize = tag(client, crop, '玉米')
    first = client.post('/api/case-library', json={'title': '案例一', 'body': '正文关键词', 'explanation': '解释关键词', 'supplementary': '补充关键词', 'source': '来源关键词', 'tag_ids': [maize]}).json()
    create(client, title='案例二')
    for keyword in ['正文关键词', '解释关键词', '补充关键词', '来源关键词']:
        assert client.get('/api/case-library', params={'keyword': keyword}).json()['items'][0]['id'] == first['id']
    assert client.get('/api/case-library?tag_status=tagged').json()['total'] == 1
    assert client.get('/api/case-library?tag_status=untagged').json()['total'] == 1
    assert client.get('/api/case-library', params={'tags': maize, 'tag_status': 'untagged'}).json()['total'] == 0
    assert client.get('/api/case-library?tag_status=invalid').status_code == 422


def test_batch_availability_atomic_conflict_and_visibility(client):
    a, b = create(client).json(), create(client, title='第二条').json()
    items = [{'case_id': x['id'], 'expected_revision': x['revision']} for x in [a, b]]
    url = '/api/case-library/batch-availability'
    assert client.patch(url, json={'items': [], 'enabled': True}).status_code == 422
    assert client.patch(url, json={'items': [items[0], items[0]], 'enabled': True}).status_code == 422
    # The first UPDATE must be rolled back if a later row conflicts.
    stale = [items[0], {**items[1], 'expected_revision': 2}]
    assert client.patch(url, json={'items': stale, 'enabled': True}).status_code == 409
    assert client.get('/api/case-library/' + a['id']).json()['revision'] == 1
    assert client.app.state.case_library.available() == []
    assert client.patch(url, json={'items': items, 'enabled': True}).json()['updated'] == 2
    assert len(client.app.state.case_library.available()) == 2
    latest = [{'case_id': x['id'], 'expected_revision': 2} for x in [a, b]]
    assert client.patch(url, json={'items': latest, 'enabled': False}).status_code == 200
    assert client.app.state.case_library.available() == []
    assert client.get('/api/case-library/' + b['id']).json()['updated_by']
    client.headers.pop('Authorization')
    assert client.patch(url, json={'items': latest, 'enabled': True}).status_code == 401
