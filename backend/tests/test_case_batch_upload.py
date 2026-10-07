import hashlib

from src.evaluation import catalog
from tests.test_evaluation import client, headers


def test_uploaded_asset_is_private_unique_and_bound_to_digest(client, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, 'ROOT', tmp_path)
    source = b'original evidence only'
    url = '/api/eval/assets/upload?filename=proof.txt&kind=evidence&source=isolated-test'
    assert client.post(url, headers=headers(), content=source).status_code == 403
    first = client.post(url, headers=headers('dev'), content=source)
    second = client.post(url, headers=headers('dev'), content=b'different bytes')
    assert first.status_code == second.status_code == 201
    one, two = first.json(), second.json()
    assert one['sha256'] == hashlib.sha256(source).hexdigest()
    assert one['path'] != two['path'] and one['filename'] == two['filename'] == 'proof.txt'
    assert (tmp_path / one['path']).read_bytes() == source
    assert (tmp_path / one['path']).stat().st_mode & 0o777 == 0o600
    assert client.post(url.replace('proof.txt', '..%2Fbad.txt'), headers=headers('dev'), content=b'bad').status_code == 422
    assert client.post(url.replace('proof.txt', 'empty.txt'), headers=headers('dev'), content=b'').status_code == 422
    assert len(client.get('/api/eval/assets', headers=headers('dev')).json()) == 2


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
