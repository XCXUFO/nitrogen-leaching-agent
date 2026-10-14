"""Table fidelity through persistence, draft generation and both Skills."""
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from src.agent.case_skills import CaseSkillInput, answer_cases
from src.api import case_library
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal
from src.storage.case_library import CaseInput, CaseStore
from tests.test_case_library import FakeLLM, DraftLLM, store  # noqa: F401

TABLE = '<h2>第二次追肥：13-14展叶</h2><table><tbody><tr><th>名称</th><th>规格</th><th>亩用量（公斤）</th></tr><tr><td>尿素</td><td>N:46%</td><td><p></p></td></tr><tr><td>工业一胺</td><td>N:12%,P:61%</td><td>3</td></tr></tbody></table>'


@pytest.mark.parametrize('body', ['<p> </p>', '<table><tbody><tr><td></td></tr></tbody></table>', '<script>alert(1)</script>', '<svg/onload=alert(1)>', '<table><p>错位数据</p></table>', '<table><tr>无单元格文字</tr></table>', '<td>无对应行</td>', '<p>内容', '<table><tr><td colspan="-1">值</td></tr></table>'])
def test_invalid_or_empty_rich_text_rejected(body):
    with pytest.raises(ValidationError):
        CaseInput(title='测试', body=body, body_format='html')


def test_html_attributes_cannot_execute_and_entities_remain_text(store):
    value = CaseInput(title='测试', body='<p onclick="alert(1)" style="background:url(x)">&lt;script&gt; &amp; ℃ m³/亩</p><table><tbody><tr><th colspan="2">表头</th></tr><tr><td rowspan="2">名称</td><td></td></tr><tr><td>5</td></tr></tbody></table>', body_format='html')
    record = store.create(value, 'tester')
    assert 'onclick' not in record['body'] and 'style=' not in record['body']
    assert '&lt;script&gt; &amp; ℃ m³/亩' in record['body']
    assert 'colspan="2"' in record['body'] and 'rowspan="2"' in record['body']
    assert '<table>' not in store.list()['items'][0]['summary']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['reference', 'explain'])
async def test_saved_table_reaches_model_without_flattening(store, mode):
    record = store.create(CaseInput(title='清徐玉米', body=TABLE, body_format='html', explanation='第二次尿素原文未填写。', enabled=True), 'tester')
    llm = FakeLLM([record['id']], answer='该用量未填写。')
    await answer_cases(CaseSkillInput(query='第二次尿素用量？', case_ids=[record['id']]), mode=mode, store=store, llm=llm)
    actual = json.loads(llm.messages[-1].content)['available_cases'][0]
    assert actual['body'] == TABLE
    assert actual['body_format'] == 'html'
    assert actual['explanation'] == record['explanation']
    store.change(record['id'], 1, {'enabled': False}, 'tester')
    assert store.available() == []


@pytest.mark.asyncio
async def test_unsaved_table_draft_and_http_roundtrip(store):
    app = FastAPI()
    app.include_router(case_library.router, prefix='/api')
    app.dependency_overrides[current_user] = lambda: Principal(tester_id='tester', role='tester')
    app.state.case_library = store
    app.state.llm = llm = DraftLLM()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        payload = {'body': TABLE, 'body_format': 'html'}
        draft = await client.post('/api/case-library/explanation-draft', json=payload)
        assert draft.status_code == 200 and TABLE in llm.messages[-1].content
        assert store.list()['total'] == 0
        created = await client.post('/api/case-library', json={'title': '清徐玉米', **payload})
        assert created.status_code == 201
        item = created.json()
        assert item['body'] == TABLE
        got = await client.get('/api/case-library/' + item['id'])
        assert got.json()['body'] == TABLE
        assert (await client.post('/api/case-library/explanation-draft', json={'body': '<p></p>', 'body_format': 'html'})).status_code == 422
        updated = await client.put('/api/case-library/' + item['id'], json={'title': item['title'], 'expected_revision': 1, **payload, 'explanation': '人工解释'})
        assert updated.status_code == 200 and updated.json()['body'] == TABLE


def test_legacy_database_migration_is_repeatable_and_lossless(tmp_path):
    path = str(tmp_path / 'old.sqlite3')
    original = CaseStore(path)
    item = original.create(CaseInput(title='旧案例', body='浓度 < 5 & 温度 > 20℃', supplementary='原有背景'), 'tester')
    original.close()
    with sqlite3.connect(path) as connection:
        connection.execute('ALTER TABLE reference_cases DROP COLUMN body_format')
    for _ in range(2):
        migrated = CaseStore(path)
        actual = migrated.get(item['id'])
        assert actual['body_format'] == 'plain' and actual['body'] == item['body']
        assert actual['supplementary'] == '原有背景' and actual['revision'] == 1
        migrated.close()


def test_prepared_source_cases_keep_critical_records(store):
    path = Path(__file__).resolve().parents[2] / 'docs/iterations/2026-10-14-case-library-v1/source-cases.json'
    records = [store.create(CaseInput(**item), '素材整理') for item in json.loads(path.read_text())]
    assert len(records) == 6 and store.available() == []
    qingxu = next(item for item in records if '清徐' in item['title'] and '玉米' in item['title'])
    assert qingxu['body'].count('<table>') == 7
    second = qingxu['body'].split('第二次追肥：13-14展叶')[1].split('</table>')[0]
    assert '<td><p>尿素</p></td><td><p>N:46%</p></td><td><p></p></td>' in second
    assert '收青贮地块不进行本次滴灌' in qingxu['body']
    assert '3次合计追施' in records[-1]['body']
    assert '如降水频繁则不灌溉' in records[0]['body']
    assert '基肥折氮52.5kg/亩' in records[1]['body']
    assert '鸡粪251.18kg/亩' in records[4]['body']


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "{}", '{"draft": 7}', '{"draft": " "}', "unstructured text"])
async def test_bad_draft_output_never_becomes_saved_content(store, content):
    from fastapi import HTTPException
    from starlette.requests import Request
    class BadDraft(DraftLLM):
        async def chat_json(self, messages, **kwargs):
            result = await super().chat_json(messages, **kwargs)
            return result.model_copy(update={"content": content})
    app = FastAPI()
    app.state.llm = BadDraft()
    request = Request({"type": "http", "app": app})
    with pytest.raises(HTTPException) as exc:
        await case_library.draft(case_library.DraftInput(body=TABLE, body_format="html"), request)
    assert exc.value.status_code == 502
    assert store.list()["total"] == 0
