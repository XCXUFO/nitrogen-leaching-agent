"""Deleting a shared tag detaches records without deleting their content."""
import json
import sqlite3

import pytest

from src.storage.case_library import CaseInput
from tests.test_case_tags import client, create as create_case, dimension, tag, update
from tests.test_literature_http import create as create_paper


def test_detaches_both_libraries_preserves_other_tags_content_and_revisions(client):
    dim = dimension(client, required=True)
    removed, kept = tag(client, dim, '待删除'), tag(client, dim, '保留')
    paper, original = create_paper(client, tag_ids=[removed, kept])
    case = create_case(client, [removed, kept]).json()
    case = update(client, case, enabled=True).json()
    untouched = create_case(client, [kept], '不受影响').json()
    library = client.app.state.literature
    key = library.search_index.content_key(paper)
    with library.write():
        library.db.execute("INSERT INTO literature_search_sync VALUES (?,?,?,'ready',?,NULL,'text','[]')",
                           (paper['id'], key, 'fixture', '2026-11-09'))
    cases = client.app.state.case_library
    library.search_index.local.ensure()
    cases.search_index.ensure()
    assert library.db.execute('SELECT id FROM local_literature_members WHERE tag_id=?',(removed,)).fetchone()
    assert cases.db.execute('SELECT id FROM local_case_members WHERE tag_id=?',(removed,)).fetchone()

    response = client.delete('/api/literature/tags/' + removed)
    assert response.status_code == 200, response.text
    assert response.json() == {'deleted': True, 'detached_paper_count': 1, 'detached_case_count': 1}
    latest = client.get('/api/literature/papers/' + paper['id']).json()
    assert latest['tag_ids'] == [kept]
    assert latest['revision'] == paper['revision'] + 1
    for field in ('title', 'abstract', 'conclusion', 'registration', 'usage', 'sha256', 'filename'):
        assert latest[field] == paper[field]
    assert latest['search_sync']['status'] == 'ready'  # Tag-only changes reuse the immutable text index.
    assert latest['search_sync']['version'] == key
    assert library.search_index.local.ensure() == 1
    assert cases.search_index.ensure() == 1
    assert not library.db.execute('SELECT id FROM local_literature_members WHERE tag_id=?',(removed,)).fetchone()
    assert not cases.db.execute('SELECT id FROM local_case_members WHERE tag_id=?',(removed,)).fetchone()
    assert client.get(f"/api/literature/papers/{paper['id']}/file").content == original
    latest_case = client.get('/api/case-library/' + case['id']).json()
    assert latest_case['tag_ids'] == [kept] and latest_case['revision'] == case['revision'] + 1
    assert latest_case['body'] == case['body'] and latest_case['enabled'] == case['enabled']
    assert client.get('/api/case-library/' + untouched['id']).json() == untouched
    assert update(client, case, tag_ids=[kept]).status_code == 409
    assert client.put('/api/literature/papers/' + paper['id'], json={**paper, 'action': 'draft', 'tag_ids': [kept]}).status_code == 409
    catalog = client.get('/api/literature/taxonomy').json()
    assert {item['id'] for item in catalog['tags']} == {kept}
    assert catalog['tags'][0]['paper_count'] == 1 and catalog['tags'][0]['case_count'] == 2
    assert client.get('/api/case-library', params={'tags': kept}).json()['total'] == 2
    event = client.get('/api/literature/events/tag/' + removed).json()[0]
    assert event['summary'] == '删除标签并解除关联'
    assert event['after']['detached_case_ids'] == [case['id']]
    assert latest['events'][0]['after']['tag_ids'] == [kept]
    assert json.loads(library.db.execute('SELECT data FROM papers WHERE id=?', (paper['id'],)).fetchone()[0])['tag_ids'] == [kept]
    assert not library.db.execute('PRAGMA foreign_key_check').fetchall()


def test_cleans_disabled_and_deleted_records_and_shows_missing_required_dimension(client):
    removed = tag(client, dimension(client, required=True), '待删除')
    papers = [create_paper(client, f'paper-{i}', tag_ids=[removed])[0] for i in range(3)]
    cases = [create_case(client, [removed], f'case-{i}').json() for i in range(2)]
    client.post(f"/api/literature/papers/{papers[1]['id']}/disable", json={'reason': 'fixture'})
    client.post(f"/api/literature/papers/{papers[2]['id']}/delete", json={'reason': 'fixture'})
    client.request('DELETE', '/api/case-library/' + cases[1]['id'], json={'expected_revision': 1})
    result = client.delete('/api/literature/tags/' + removed).json()
    assert result['detached_paper_count'] == 3 and result['detached_case_count'] == 2
    library, case_store = client.app.state.literature, client.app.state.case_library
    assert library.db.execute('SELECT count(*) FROM papers').fetchone()[0] == 3
    assert library.db.execute('SELECT count(*) FROM paper_tags').fetchone()[0] == 0
    assert all(json.loads(row[0]) == [] for row in case_store.db.execute('SELECT tag_ids FROM reference_cases'))
    latest = client.get('/api/literature/papers/' + papers[0]['id']).json()
    assert latest['tag_ids'] == [] and any('必填维度' in warning for warning in latest['warnings'])
    assert client.get('/api/literature/papers?untagged=true').json()['total'] == 1
    assert client.get('/api/case-library?tag_status=untagged').json()['total'] == 1


def test_parent_protection_auth_and_missing_tag_make_no_changes(client):
    parent = tag(client, dimension(client), '父标签')
    child = tag(client, client.get('/api/literature/taxonomy').json()['dimensions'][0]['id'], '子标签', parent_id=parent)
    case = create_case(client, [parent]).json()
    assert client.delete('/api/literature/tags/' + parent, headers={'Authorization': ''}).status_code == 401
    response = client.delete('/api/literature/tags/' + parent)
    assert response.status_code == 409 and '子标签' in response.json()['detail']['message']
    assert client.get('/api/case-library/' + case['id']).json() == case
    assert client.delete('/api/literature/tags/missing').status_code == 404
    assert client.delete('/api/literature/tags/' + child).json()['deleted'] is True
    assert client.delete('/api/literature/tags/' + parent).json()['detached_case_count'] == 1
    assert client.delete('/api/literature/tags/' + parent).status_code == 404


def test_late_failure_rolls_back_both_databases_and_audits(client, monkeypatch):
    removed = tag(client, dimension(client), '待删除')
    paper, _ = create_paper(client, tag_ids=[removed])
    case = create_case(client, [removed]).json()
    library = client.app.state.literature
    original_event = library.event
    def fail_delete(entity, identifier, action, *args, **kwargs):
        if entity == 'tag' and action == 'delete':
            raise sqlite3.IntegrityError('injected audit failure after both library updates')
        return original_event(entity, identifier, action, *args, **kwargs)
    monkeypatch.setattr(library, 'event', fail_delete)
    with pytest.raises(sqlite3.IntegrityError):
        client.delete('/api/literature/tags/' + removed)
    assert library.get_paper(paper['id'])['revision'] == paper['revision']
    assert library.get_paper(paper['id'])['tag_ids'] == [removed]
    assert client.get('/api/case-library/' + case['id']).json() == case
    assert not any(event['reason'] for event in library.events('paper', paper['id']))
    assert removed in {item['id'] for item in library.taxonomy()['tags']}
    assert [row[1] for row in library.db.execute('PRAGMA database_list')] == ['main']
    monkeypatch.setattr(library, 'event', original_event)
    assert client.delete('/api/literature/tags/' + removed).status_code == 200


def test_more_than_a_thousand_assignments_are_not_limited_by_sql_parameter_count(client):
    removed = tag(client, dimension(client), '批量标签')
    paper, _ = create_paper(client, tag_ids=[removed])
    library = client.app.state.literature
    with library.write():
        for index in range(1100):
            identifier = f'P-BULK-{index}'
            library.db.execute('''INSERT INTO papers
                (id,data,filename,sha256,registration,usage,deleted,created_by,created_at,updated_by,updated_at,revision)
                SELECT ?,data,filename,?,'draft','normal',0,created_by,created_at,updated_by,updated_at,1 FROM papers WHERE id=?''',
                (identifier, f'bulk-hash-{index}', paper['id']))
            library.db.execute('INSERT INTO paper_tags VALUES (?,?)', (identifier, removed))
    for index in range(30):
        client.app.state.case_library.create(CaseInput(title=f'案例{index}', body='原文', tag_ids=[removed]), 'tester')
    result = client.delete('/api/literature/tags/' + removed)
    assert result.status_code == 200, result.text
    assert result.json() == {'deleted': True, 'detached_paper_count': 1101, 'detached_case_count': 30}
    assert library.db.execute('SELECT count(*) FROM papers WHERE revision=2').fetchone()[0] == 1101
    assert library.db.execute('SELECT count(*) FROM paper_tags').fetchone()[0] == 0
