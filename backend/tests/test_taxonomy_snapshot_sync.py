import json
from pathlib import Path

import pytest

from scripts.sync_taxonomy_snapshot import REDIRECTS, synchronize
from src.api.literature import now
from tests.test_case_tags import client, create as create_case, dimension  # noqa: F401
from tests.test_literature_http import create as create_paper


SOURCE = Path(__file__).resolve().parents[2] / 'docs/iterations/2026-11-11-retrieval-skills-v02/source/标签与Skill本地迭代包/taxonomy.json'


def seed(client):
    library = client.app.state.literature
    crop = dimension(client, '作物')
    region = dimension(client, '地区')
    at = now()
    rows = [('T-067d23c4868a', crop, None, '玉米'), ('T-0d6db06e5bda', region, None, '广西'),
        ('T-5b378fb3c304', region, 'T-0d6db06e5bda', '桂平'), ('T-67271849b5bc', region, 'T-0d6db06e5bda', '南宁')]
    with library.write():
        library.db.executemany('INSERT INTO tags VALUES (?,?,?,?,?,1,0,?,?)', [(*row, '', at, at) for row in rows])
    return library, client.app.state.case_library, crop, region


def test_sync_keeps_ids_migrates_both_libraries_removes_only_two_nodes_and_is_idempotent(client):
    library, cases, crop, region = seed(client)
    paper, original = create_paper(client, tag_ids=list(REDIRECTS))
    case = create_case(client, list(REDIRECTS)).json()
    snapshot = json.loads(SOURCE.read_text())
    with library.write():
        library.db.execute('INSERT INTO asset_tag_jobs VALUES (?,?,?,?,?,?)', ('old-job', 'dev', 'merge', '{}', at := now(), 0))
        library.db.execute("INSERT INTO asset_tag_items(job_id,kind,asset_id,title,revision,status,attempt) VALUES ('old-job','case',?,'旧任务',1,'processing','attempt')", (case['id'],))
    with library.write_with_cases(cases):
        result = synchronize(library.db, snapshot)
    assert result['dimension_count'] == 5 and result['tag_count'] == 99
    assert result['dimension_ids']['crop'] == crop and result['dimension_ids']['region'] == region
    assert set(result['removed_local_ids']) == set(REDIRECTS)
    catalog = library.taxonomy()
    assert not any(t['name'] == '已废弃' for t in catalog['tags'])
    tags = {t['id']: t for t in catalog['tags']}
    assert tags['T-5b378fb3c304']['path'] == '华南 / 广西 / 桂平'
    assert tags['T-67271849b5bc']['path'] == '华南 / 广西 / 南宁'
    assert set(tags) == {t['id'] for t in snapshot['tags']} - set(REDIRECTS)
    after = library.get_paper(paper['id'])
    assert set(after['tag_ids']) == set(REDIRECTS.values())
    assert after['revision'] == paper['revision'] + 1
    assert after['title'] == paper['title'] and after['sha256'] == paper['sha256']
    assert client.get(f"/api/literature/papers/{paper['id']}/file").content == original
    current_case = cases.get(case['id'])
    assert current_case['tag_ids'] == list(REDIRECTS.values())
    assert current_case['revision'] == case['revision'] + 1
    assert current_case['body'] == case['body'] and current_case['enabled'] == case['enabled']
    task = library.db.execute("SELECT status,attempt FROM asset_tag_items WHERE job_id='old-job'").fetchone()
    assert task['status'] == 'conflict' and task['attempt'] is None
    assert result['interrupted_tagging_jobs'] == [{'job_id': 'old-job', 'count': 1}]
    with library.write_with_cases(cases):
        repeated = synchronize(library.db, snapshot)
    assert not repeated['changed'] and not repeated['migrated_papers'] and not repeated['migrated_cases']
    assert cases.get(case['id']) == current_case


def test_late_invalid_assignment_rolls_back_taxonomy_and_paper_changes(client):
    library, cases, _, _ = seed(client)
    paper, _ = create_paper(client, tag_ids=['T-0d6db06e5bda'])
    case = create_case(client).json()
    cases.db.execute('UPDATE reference_cases SET tag_ids=? WHERE id=?', (json.dumps(['unknown-tag']), case['id']))
    cases.db.commit()
    before = library.taxonomy()
    with pytest.raises(ValueError, match='unknown tag'):
        with library.write_with_cases(cases):
            synchronize(library.db, json.loads(SOURCE.read_text()))
    assert library.taxonomy() == before
    assert library.get_paper(paper['id'])['tag_ids'] == ['T-0d6db06e5bda']
    assert library.get_paper(paper['id'])['revision'] == paper['revision']


def test_parent_and_descendant_assignments_merge_without_duplicates(client):
    library, cases, _, _ = seed(client)
    case = create_case(client).json()
    cases.db.execute('UPDATE reference_cases SET tag_ids=? WHERE id=?',
        (json.dumps(['T-0d6db06e5bda', 'T-5b378fb3c304', 'T-0d6db06e5bda']), case['id']))
    cases.db.commit()
    with library.write_with_cases(cases):
        synchronize(library.db, json.loads(SOURCE.read_text()))
    assert cases.get(case['id'])['tag_ids'] == ['T-5b378fb3c304']
