"""Real orchestration with synthetic material and a non-network model fixture."""
import hashlib
import json

import pytest

from src.evaluation.material_replay import prepare_fixture, replay
from src.agent.prompt import expand_retrieval_query
from tests.test_case_library import FakeLLM
from tests.test_literature import pdf_bytes
from src.llm.base import ChatResult, ChatUsage


class ReplayLLM(FakeLLM):
    async def chat(self, messages, **kwargs):
        if 'used_case_ids' in messages[0].content:
            return await super().chat(messages, **kwargs)
        return ChatResult(content=self.answer, model='fixture',
                          usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    paper, case = 'P-1111111111111111', 'C-2222222222222222'
    pdf = pdf_bytes('synthetic')
    sha = hashlib.sha256(pdf).hexdigest()
    raw = {
        'index.json': {'materials': [
            {'id': paper, 'kind': 'literature', 'title': '合成水氮材料', 'url': 'https://example.org/paper',
             'full_text': None, 'original_pdf': f'originals/{paper}.pdf'},
            {'id': case, 'kind': 'case', 'page_metadata': f'cases/{case}.json'}],
            'rounds': [{'case_id': key, 'turn': turn, 'raw_path': f'runs/{key}.json'}
                       for key, turn in [('FIX-05', 2), ('KEEP-03', 1)]]},
        f'literature/{paper}.pdf-info.json': {'sha256': sha},
        f'cases/{case}.json': {'title': '合成水氮案例', 'bodyHtml': '<div><p>分次施肥；无效果数据。</p></div>', 'url': 'https://example.org/case'},
        f'cases/historical/{case}@fixture.json': {'candidate': {'snippet': '<p>分次施肥；无效果数据。</p>', 'revision': 4}},
        'runs/FIX-05.json': {'request_snapshot': {'history': [{'role': 'user', 'content': '旧问题'}, {'role': 'assistant', 'content': '旧固定回答'}]}},
        'runs/KEEP-03.json': {'request_snapshot': {'history': []}},
        'conversations/reviewed-cases.json': {'records': [
            {'id': 'FIX-05', 'evaluation_mode': 'fixed_history_target_turn', 'target_turn': 2,
             'source_review_status': 'needs_changes', 'user_turns': ['WHCNS模型是什么？']},
            {'id': 'KEEP-03', 'evaluation_mode': 'multi_turn_trajectory', 'target_turn': None,
             'source_review_status': 'passed', 'user_turns': ['有哪些水氮管理案例可以参考？', '上面案例中的关键措施是什么，为什么这样做？', '案例中的效果有哪些证据，还不能得出哪些结论？']}]} }
    for name, value in raw.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    (root / 'originals').mkdir()
    (root / f'originals/{paper}.pdf').write_bytes(pdf)
    (root / f'literature/{paper}.txt').write_text('Synthetic greenhouse vegetable field study: nitrous oxide emissions were observed after fertilization and irrigation. 合成水氮材料用于测试，不作为专业参考答案。', encoding='utf-8')
    files = [{'path': str(p.relative_to(root)), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in root.rglob('*') if p.is_file()]
    (root / 'manifest.json').write_text(json.dumps({'files': files}), encoding='utf-8')
    return root


def test_fixture_handles_null_index_pointer_and_preserves_pdf_and_case_ids(source, tmp_path):
    output = tmp_path / 'experiment'
    library, cases = prepare_fixture(source, output)
    try:
        assert library.db.execute('SELECT count(*) FROM papers').fetchone()[0] == 1
        assert library.search_index.search('水氮')[0]
        assert cases.get('C-2222222222222222')['body'] == '<p>分次施肥；无效果数据。</p>'
        assert cases.get('C-2222222222222222')['revision'] == 4
        assert next((output / 'files').glob('blob-*.pdf')).read_bytes() == (source / 'originals/P-1111111111111111.pdf').read_bytes()
        with pytest.raises(FileExistsError):
            prepare_fixture(source, output)
    finally:
        library.close()
        cases.close()


@pytest.mark.parametrize('query', ['菜地 N2O 排放规律', '菜地 n2o 排放规律', '设施蔬菜 N₂O 排放变化'])
def test_short_chinese_emissions_query_reaches_english_body_without_named_paper_rules(source, tmp_path, query):
    library, cases = prepare_fixture(source, tmp_path / 'experiment')
    try:
        # Shared chemical normalization can now also retrieve the raw variant.
        hits, _ = library.search_index.search(expand_retrieval_query(query))
        assert hits and hits[0].metadata['paper_id'] == 'P-1111111111111111'
        assert 'nitrous oxide emissions' in hits[0].document
    finally:
        library.close()
        cases.close()


@pytest.mark.asyncio
async def test_fixed_history_and_three_round_new_answers_are_persisted(source, tmp_path):
    result = await replay(source, tmp_path / 'experiment', ReplayLLM(['C-2222222222222222'], answer='本次新回答，未提供效果证据。'),
                          config_manifest={'manifest_sha256': 'synthetic'})
    fixed, trajectory = result['attempts']
    assert fixed['status'] == trajectory['status'] == 'completed', result['attempts']
    assert fixed['steps'][0]['history'][1]['content'] == '旧固定回答'
    assert [len(step['history']) for step in trajectory['steps']] == [0, 2, 4]
    assert trajectory['steps'][1]['history'][1]['content'] == trajectory['steps'][0]['response']['answer']
    assert trajectory['steps'][2]['history'][3]['content'] == trajectory['steps'][1]['response']['answer']
    assert len({step['run_id'] for attempt in result['attempts'] for step in attempt['steps']}) == 4
    assert trajectory['steps'][1]['case_context']['displayed_case_ids'] == ['C-2222222222222222']
    assert result['professional_review'] == 'pending' and not result['full_online_retrieval_reproduced']


@pytest.mark.asyncio
async def test_targeted_retry_keeps_whole_trajectory_and_rejects_unknown_target(source, tmp_path):
    result = await replay(source, tmp_path / 'selected', FakeLLM(['C-2222222222222222']),
                          config_manifest={'manifest_sha256': 'synthetic'}, case_ids={'KEEP-03'})
    assert [a['case_id'] for a in result['attempts']] == ['KEEP-03']
    assert len(result['attempts'][0]['steps']) == 3
    with pytest.raises(ValueError, match='unknown'):
        await replay(source, tmp_path / 'invalid', None,
                     config_manifest={'manifest_sha256': 'synthetic'}, case_ids={'missing'})
    assert not (tmp_path / 'invalid').exists()


@pytest.mark.asyncio
async def test_empty_body_is_failed_with_usage_preserved(source, tmp_path):
    from src.llm.base import ChatResult, ChatUsage
    class EmptyLLM:
        async def chat(self, *args, **kwargs):
            return ChatResult(content='', model='fixture', usage=ChatUsage(prompt_tokens=2, completion_tokens=3000, total_tokens=3002))
    result = await replay(source, tmp_path / 'empty', EmptyLLM(),
                          config_manifest={'manifest_sha256': 'synthetic'}, case_ids={'FIX-05'})
    attempt = result['attempts'][0]
    assert attempt['status'] == 'failed'
    assert attempt['steps'][0]['error_code'] == 'empty_model_answer'
    assert attempt['steps'][0]['response']['usage']['completion_tokens'] == 3000
