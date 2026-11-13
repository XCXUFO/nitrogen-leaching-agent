import asyncio
import json
import time

import pytest

from src.api import asset_tagging
from src.llm.base import ChatResult, ChatUsage
from tests.literature_fixture import TOKENS
from tests.test_case_tags import client, create, dimension, tag  # noqa: F401
from tests.test_literature_extract import pdf_bytes

PATH = '/api/literature/asset-tag-jobs'


class LLM:
    def __init__(self, tags):
        self.tags = tags
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(json.loads(messages[1].content))
        return ChatResult(content=json.dumps({'tag_ids': self.tags}), model='test',
                         usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


def setup(client):
    client.headers['Authorization'] = f"Bearer {TOKENS['developer']}"
    dim = dimension(client, name='主题')
    old, new = tag(client, dim, '玉米'), tag(client, dim, '氮素淋失')
    client.app.state.llm = LLM([new, 'invented-tag'])
    return old, new


def paper(client, tags=()):
    uploaded = client.post('/api/literature/uploads?filename=paper.pdf', content=pdf_bytes('Nitrogen leaching in maize fields.')).json()
    response = client.post('/api/literature/papers', json={'upload_id': uploaded['upload_id'], 'tag_ids': list(tags)})
    assert response.status_code == 200, response.text
    return response.json()


def run(client, mode='merge'):
    response = client.post(PATH, json={'mode': mode})
    assert response.status_code == 202, response.text
    return client.get(f"{PATH}/{response.json()['id']}").json()


def test_whole_library_merges_drafts_disabled_cases_and_keeps_content(client):
    old, new = setup(client)
    p = paper(client, [old])
    c = create(client, [old]).json()
    client.post(f"/api/literature/papers/{p['id']}/disable", json={'reason': '停用测试'})
    client.app.state.case_library.change(c['id'], 1, {'enabled': 0}, 'human')
    job = run(client)
    assert job['total'] == 2 and job['counts'] == {'ready': 2}
    assert job['assets'] == {'case': 1, 'literature': 1}
    saved_p = client.app.state.literature.get_paper(p['id'])
    saved_c = client.app.state.case_library.get(c['id'])
    assert set(saved_p['tag_ids']) == set(saved_c['tag_ids']) == {old, new}
    assert saved_p['usage'] == 'disabled' and saved_p['registration'] == 'draft'
    assert saved_c['enabled'] == 0 and saved_c['body'] == c['body']
    assert saved_p['revision'] == 3 and saved_c['revision'] == 3
    assert all(call['selected_tag_ids'] == [old] for call in client.app.state.llm.calls)
    assert any('pdf_text' in call for call in client.app.state.llm.calls)
    assert any('case_text' in call for call in client.app.state.llm.calls)
    assert all(item['before_tags'] == [old] and new in item['after_tags'] for item in job['items'])
    assert client.get(PATH).json()['items'][0]['id'] == job['id']
    assert '全库 AI 打标' in client.app.state.literature.events('paper', p['id'])[0]['reason']


@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_disabled_ancestors_are_excluded_from_batch_suggestions_and_new_saves(client, mode):
    from src.agent.tag_matching import TagIndex
    from tests.test_case_tags import update

    _, active = setup(client)
    dim = dimension(client, name='停用分支')
    root = tag(client, dim, '父标签')
    child = tag(client, dim, '子标签', parent_id=root)
    leaf = tag(client, dim, '孙标签', parent_id=child)
    existing_paper = paper(client, [leaf])
    existing_case = create(client, [leaf]).json()
    assert client.put('/api/literature/tags/' + root, json={'name': '父标签', 'enabled': False}).status_code == 200
    assert create(client, [leaf]).json()['detail']['code'] == 'invalid_tag'
    assert client.put('/api/literature/papers/' + existing_paper['id'],
                      json={**existing_paper, 'tag_ids': [child]}).json()['detail']['code'] == 'invalid_tag'
    # Existing manual associations remain editable after the parent is disabled.
    assert update(client, existing_case, title='保留旧关联').status_code == 200
    existing_case = client.app.state.case_library.get(existing_case['id'])
    client.app.state.llm.tags = [leaf, child, active]
    job = run(client, mode)
    assert job['counts'] == {'ready': 2}
    expected = {leaf, active} if mode == 'merge' else {active}
    assert set(client.app.state.literature.get_paper(existing_paper['id'])['tag_ids']) == expected
    assert set(client.app.state.case_library.get(existing_case['id'])['tag_ids']) == expected
    for call in client.app.state.llm.calls:
        assert not {root, child, leaf} & {item['id'] for item in call['taxonomy']['tags']}
    index = TagIndex(client.app.state.literature.taxonomy(), {'entries': []}, {})
    assert active in index.enabled and not {root, child, leaf} & index.enabled


def test_batch_preflight_rejects_a_catalog_whose_only_enabled_tags_have_disabled_parents(client):
    client.headers['Authorization'] = f"Bearer {TOKENS['developer']}"
    dim = dimension(client)
    parent = tag(client, dim, '停用父节点', enabled=False)
    child = tag(client, dim, '名义启用子节点', parent_id=parent)
    client.app.state.llm = LLM([child])
    create(client)
    response = client.post(PATH, json={'mode': 'merge'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'no_available_tags'


def test_replace_clears_unmatched_tags_and_includes_more_than_one_hundred_assets(client):
    old, new = setup(client)
    p = paper(client, [old])
    cases = [create(client, [old], title=str(i)).json() for i in range(102)]
    client.app.state.llm.tags = []
    job = run(client, 'replace')
    assert job['total'] == 103 and job['counts'] == {'ready': 103}
    assert len(job['items']) == 50
    assert len(client.get(f"{PATH}/{job['id']}?offset=100&limit=100").json()['items']) == 3
    assert client.app.state.literature.get_paper(p['id'])['tag_ids'] == []
    assert all(client.app.state.case_library.get(c['id'])['tag_ids'] == [] for c in cases)
    assert all(call['selected_tag_ids'] == [] for call in client.app.state.llm.calls)


@pytest.mark.parametrize('role', ['tester', 'reviewer', None])
def test_all_endpoints_require_developer(client, role):
    setup(client)
    create(client)
    job = run(client)
    headers = {'Authorization': f'Bearer {TOKENS[role]}' if role else ''}
    for method, path in [('GET', PATH), ('POST', PATH), ('GET', f"{PATH}/{job['id']}"), ('POST', f"{PATH}/{job['id']}/retry")]:
        response = client.request(method, path, headers=headers, json={'mode': 'merge'} if method == 'POST' else None)
        assert response.status_code == (403 if role else 401)


def test_failed_items_retry_without_reprocessing_successes(client):
    old, new = setup(client)
    good = create(client, [old], title='成功').json()
    bad = create(client, [old], title='失败').json()
    original = client.app.state.llm.chat

    async def partial(messages, **kwargs):
        if json.loads(messages[1].content)['fields']['title'] == '失败':
            raise ValueError('invalid model result')
        return await original(messages, **kwargs)

    client.app.state.llm.chat = partial
    job = run(client)
    assert job['counts'] == {'ready': 1, 'failed': 1} and job['retryable']
    assert client.app.state.case_library.get(bad['id'])['tag_ids'] == [old]
    client.app.state.llm.chat = original
    assert client.post(f"{PATH}/{job['id']}/retry").status_code == 202
    assert client.get(f"{PATH}/{job['id']}").json()['counts'] == {'ready': 2}
    assert client.app.state.case_library.get(good['id'])['revision'] == 2
    assert set(client.app.state.case_library.get(bad['id'])['tag_ids']) == {old, new}


def test_edits_and_taxonomy_changes_are_not_overwritten(client):
    old, new = setup(client)
    p = paper(client, [old])
    c = create(client, [old]).json()
    original = client.app.state.llm.chat

    async def changed(messages, **kwargs):
        data = json.loads(messages[1].content)
        if 'case_text' in data:
            client.app.state.case_library.change(c['id'], 1, {'body': '人工新正文'}, 'human')
        else:
            with client.app.state.literature.write():
                client.app.state.literature.db.execute('UPDATE papers SET revision=revision+1 WHERE id=?', (p['id'],))
        return await original(messages, **kwargs)

    client.app.state.llm.chat = changed
    job = run(client)
    assert job['counts'] == {'conflict': 2}
    assert client.app.state.literature.get_paper(p['id'])['tag_ids'] == [old]
    assert client.app.state.case_library.get(c['id'])['body'] == '人工新正文'
    assert client.app.state.case_library.get(c['id'])['tag_ids'] == [old]

    async def retagged(messages, **kwargs):
        with client.app.state.literature.write():
            client.app.state.literature.db.execute("UPDATE tags SET description='新分类规则' WHERE id=?", (new,))
        return await original(messages, **kwargs)

    client.app.state.llm.chat = retagged
    job = run(client)
    assert job['taxonomy_changed'] and job['counts'] == {'conflict': 2}


def test_duplicate_submission_interruption_and_latest_taxonomy_restart(client, monkeypatch):
    setup(client)
    c = create(client).json()
    original = asset_tagging.process_job

    async def stopped(*args):
        pass

    monkeypatch.setattr(asset_tagging, 'process_job', stopped)
    job = run(client)
    assert job['active'] and not job['retryable']
    assert run(client)['id'] == job['id']
    assert client.post(f"{PATH}/{job['id']}/retry").status_code == 409
    db = client.app.state.literature
    with db.write():
        db.db.execute('UPDATE asset_tag_jobs SET updated_at=? WHERE id=?', (time.time() - 600, job['id']))
    monkeypatch.setattr(asset_tagging, 'process_job', original)
    assert client.post(f"{PATH}/{job['id']}/retry").status_code == 202
    assert client.app.state.case_library.get(c['id'])['revision'] == 2

    monkeypatch.setattr(asset_tagging, 'process_job', stopped)
    pending = run(client)
    tag(client, dimension(client, '新维度'), '新标签')
    assert client.post(f"{PATH}/{pending['id']}/retry").status_code == 409
    monkeypatch.setattr(asset_tagging, 'process_job', original)
    latest = run(client)
    assert latest['id'] != pending['id'] and latest['counts'] == {'ready': 1}
    assert client.get(f"{PATH}/{pending['id']}").json()['counts'] == {'conflict': 1}


def test_preflight_and_worker_concurrency(client):
    setup(client)
    assert client.post(PATH, json={}).json()['detail']['code'] == 'no_tagging_assets'
    for i in range(8):
        create(client, title=str(i))
    original = client.app.state.llm.chat
    active = peak = 0

    async def delayed(messages, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        try:
            return await original(messages, **kwargs)
        finally:
            active -= 1

    client.app.state.llm.chat = delayed
    assert run(client)['counts'] == {'ready': 8} and peak == 3
    client.app.state.llm = None
    assert client.post(PATH, json={}).status_code == 503
    assert client.post(PATH, json={'mode': 'invalid'}).status_code == 422
