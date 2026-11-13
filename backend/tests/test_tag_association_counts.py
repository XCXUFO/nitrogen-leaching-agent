"""Management counts cover descendant tags without double-counting records."""
import json

from tests.test_case_tags import client, create as create_case, dimension, tag
from tests.test_literature_http import create as create_paper


def catalog(client):
    response = client.get('/api/literature/taxonomy')
    assert response.status_code == 200, response.text
    return {item['id']: item for item in response.json()['tags']}


def counts(item):
    return tuple(item[key] for key in ('paper_count', 'indirect_paper_count', 'case_count', 'indirect_case_count'))


def test_descendants_deduplicate_both_libraries_and_exclude_deleted_records(client):
    crop = dimension(client)
    root = tag(client, crop, '粮食作物')
    maize = tag(client, crop, '玉米', parent_id=root)
    wheat = tag(client, crop, '小麦', parent_id=root)
    spring = tag(client, crop, '春玉米', parent_id=maize)
    empty = tag(client, crop, '尚无资料')
    water = dimension(client, '灌溉方式')
    irrigation = tag(client, water, '灌溉')
    drip = tag(client, water, '滴灌', parent_id=irrigation)

    shared_paper, _ = create_paper(client, 'siblings', tag_ids=[maize, wheat, drip])
    disabled_paper, _ = create_paper(client, 'disabled', tag_ids=[spring])
    create_paper(client, 'parent', tag_ids=[root])
    deleted_paper, _ = create_paper(client, 'deleted', tag_ids=[spring])
    create_paper(client, 'untagged')
    assert client.post(f"/api/literature/papers/{disabled_paper['id']}/disable", json={'reason': 'fixture'}).status_code == 200
    assert client.post(f"/api/literature/papers/{deleted_paper['id']}/delete", json={'reason': 'fixture'}).status_code == 200

    shared_case = create_case(client, [maize, wheat, drip]).json()
    create_case(client, [spring], '下级案例')  # Unpublished cases still count in management.
    create_case(client, [root], '直接案例')
    removed_case = create_case(client, [spring], '已删除案例').json()
    create_case(client, title='无标签案例')
    assert client.request('DELETE', '/api/case-library/' + removed_case['id'],
                          json={'expected_revision': removed_case['revision']}).status_code == 200

    result = catalog(client)
    assert counts(result[root]) == (1, 2, 1, 2)
    assert counts(result[maize]) == (1, 1, 1, 1)
    assert counts(result[wheat]) == (1, 0, 1, 0)
    assert counts(result[spring]) == (1, 0, 1, 0)
    assert counts(result[irrigation]) == (0, 1, 0, 1)
    assert counts(result[empty]) == (0, 0, 0, 0)

    # Old assignments can contain both ancestor and descendant. Count these
    # records as direct only, even when they also match multiple descendants.
    library = client.app.state.literature
    with library.write():
        library.db.execute('INSERT INTO paper_tags VALUES (?,?)', (shared_paper['id'], root))
    cases = client.app.state.case_library
    with cases.lock, cases.db:
        cases.db.execute('UPDATE reference_cases SET tag_ids=? WHERE id=?',
                         (json.dumps([root, maize, wheat, drip]), shared_case['id']))
    assert counts(catalog(client)[root]) == (2, 1, 2, 1)


def test_moving_a_branch_recomputes_ancestors_without_reassigning_records(client):
    crop = dimension(client)
    before = tag(client, crop, '原上级')
    after = tag(client, crop, '新上级')
    branch = tag(client, crop, '迁移分支', parent_id=before)
    leaf = tag(client, crop, '叶子', parent_id=branch)
    create_paper(client, 'moving', tag_ids=[leaf])
    create_case(client, [leaf])
    assert counts(catalog(client)[before]) == (0, 1, 0, 1)
    response = client.put('/api/literature/tags/' + branch,
                          json={'name': '迁移分支', 'parent_id': after})
    assert response.status_code == 200, response.text
    result = catalog(client)
    assert counts(result[before]) == (0, 0, 0, 0)
    assert counts(result[after]) == (0, 1, 0, 1)
    assert counts(result[branch]) == (0, 1, 0, 1)
    assert counts(result[leaf]) == (1, 0, 1, 0)


def test_taxonomy_still_reports_paper_counts_without_a_case_library(client, monkeypatch):
    crop = dimension(client)
    parent = tag(client, crop, '父标签')
    child = tag(client, crop, '子标签', parent_id=parent)
    create_paper(client, 'standalone', tag_ids=[child])
    with monkeypatch.context() as context:
        context.setattr(client.app.state, 'case_library', None)
        result = catalog(client)
    assert counts(result[parent]) == (0, 1, 0, 0)
    assert counts(result[child]) == (1, 0, 0, 0)
