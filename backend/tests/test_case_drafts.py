import hashlib

import pytest

from src.evaluation import catalog
from tests.test_evaluation import client, headers


@pytest.mark.parametrize('user', ['alice', 'dev', 'expert'])
def test_asset_management_routes_are_removed(client, user):
    for method, path in [('GET', '/assets'), ('POST', '/assets'),
                         ('POST', '/assets/upload'), ('GET', '/asset-pairs'), ('POST', '/asset-pairs')]:
        assert client.request(method, '/api/eval' + path, headers=headers(user)).status_code == 404
    tables = {row[0] for row in client.app.state.evaluation.store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables.intersection({'eval_assets', 'eval_asset_pairs'})


def test_draft_import_rejects_unknown_fixtures_without_partial_writes(client):
    template = client.app.state.evaluation.store.case('NEW01', 2)['case']
    response = client.post('/api/eval/case-drafts/import', headers=headers('dev'), json={'drafts': [
        {'case': {**template, 'case_id': 'KNOWN'}},
        {'case': {**template, 'case_id': 'UNKNOWN', 'attachment_requirements': ['new-output.xls']}}]})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'draft_fixture_mismatch'
    assert client.get('/api/eval/case-drafts', headers=headers('dev')).json() == []


def test_publish_rechecks_evaluation_fixture_fingerprint(client, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, 'ROOT', tmp_path)
    (tmp_path / 'data').mkdir()
    path = tmp_path / 'data/sample.xls'
    path.write_bytes(b'original evaluation fixture')
    store = client.app.state.evaluation.store
    store.fixtures['sample.xls'] = {'filename': path.name, 'path': 'data/sample.xls',
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    template = store.case('NEW01', 2)['case']
    response = client.post('/api/eval/case-drafts', headers=headers('dev'), json={
        'case': {**template, 'case_id': 'FIXTURE', 'version': 1, 'attachment_requirements': [path.name]}})
    assert response.status_code == 201
    draft = response.json()
    path.write_bytes(b'changed evaluation fixture')
    published = client.post(f'/api/eval/case-drafts/{draft["draft_id"]}/publish',
                            headers=headers('dev'), json={'expected_revision': 1})
    assert published.status_code == 422
    assert published.json()['detail']['code'] == 'fixture_changed'
    assert client.get(f'/api/eval/case-drafts/{draft["draft_id"]}', headers=headers('dev')).json()['status'] == 'draft'


def test_existing_draft_keeps_frozen_fixture_when_seed_changes(client):
    store = client.app.state.evaluation.store
    template = store.case('F05', 2)['case']
    created = client.post('/api/eval/case-drafts', headers=headers('dev'), json={
        'case': {**template, 'case_id': 'EXISTING', 'version': 1}})
    assert created.status_code == 201
    draft = created.json()
    store.fixtures['Nbal_out.xls'] = {**store.fixtures['Nbal_out.xls'], 'sha256': '0' * 64}
    saved = client.put(f'/api/eval/case-drafts/{draft["draft_id"]}', headers=headers('dev'), json={
        'case': draft['case'], 'notes': 'Keep existing fixture snapshot', 'expected_revision': 1})
    assert saved.status_code == 200
    assert saved.json()['fixtures'] == draft['fixtures']


def test_batch_draft_import_is_atomic_and_never_publishes(client):
    existing = client.get('/api/eval/cases?latest=false', headers=headers('dev')).json()
    template = next(item['case'] for item in existing if item['case']['case_id'] == 'NEW01' and item['case']['version'] == 2)
    def copy(cid): return {**template, 'case_id': cid, 'version': 1, 'attachment_requirements': []}
    path = '/api/eval/case-drafts/import'
    invalid = client.post(path, headers=headers('dev'), json={'drafts': [
        {'case': copy('BATCHA')}, {'case': {**copy('BATCHB'), 'steps': []}}]})
    assert invalid.status_code == 422
    assert client.get('/api/eval/case-drafts', headers=headers('dev')).json() == []
    valid = client.post(path, headers=headers('dev'), json={'drafts': [
        {'case': copy('BATCHA')}, {'case': copy('BATCHB')}]})
    assert valid.status_code == 201
    records = valid.json()
    assert len(records) == 2 and all(record['status'] == 'draft' and record['revision'] == 1 for record in records)
    for record in records:
        history = client.get(f'/api/eval/case-drafts/{record["draft_id"]}/history', headers=headers('dev')).json()
        assert history == [record]
    assert client.get('/api/eval/cases?latest=false', headers=headers('dev')).json() == existing
    duplicate = client.post(path, headers=headers('dev'), json={'drafts': [
        {'case': copy('BATCHC')}, {'case': copy('BATCHC')}]})
    assert duplicate.status_code == 422
    assert len(client.get('/api/eval/case-drafts', headers=headers('dev')).json()) == 2
