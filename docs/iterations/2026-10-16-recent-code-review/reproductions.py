"""Original review scenarios, now asserting the corrected behavior."""
import json
import time
from datetime import datetime, timezone
import pytest
from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatRequest
from src.storage.case_library import CaseStore, CaseInput
from tests.test_case_library import FakeLLM
import src.api.literature
from src.api.literature_batch import with_retry_status

@pytest.mark.asyncio
async def test_followup_keeps_case_scope(tmp_path):
    store = CaseStore(str(tmp_path / 'cases.db'))
    a = store.create(CaseInput(title='甲地玉米', body='甲地分次施肥', enabled=True), 'tester')
    b = store.create(CaseInput(title='乙地水稻', body='乙地灌溉', enabled=True), 'tester')
    runtime = AgentRuntime()
    async def report(_):
        raise AssertionError('unrelated file access')
    llm = FakeLLM([a['id']])
    try:
        await runtime.execute(ChatRequest(query='找一个玉米案例', session_id='review-scope'), service=None, get_report=report, case_store=store, llm=llm)
        await runtime.execute(ChatRequest(query='这个案例适合什么土壤？', session_id='review-scope'), service=None, get_report=report, case_store=store, llm=llm)
        payload = json.loads(llm.messages[-1].content)
        assert '找一个玉米案例' in payload['previous_user_text']
        assert {c['id'] for c in payload['available_cases']} == {a['id']}
        print('FIXED: followup preserves previous subject and selected case')
    finally:
        runtime.runs.close()
        store.close()


def test_interrupted_queue_is_retryable():
    batch = {'created_at': datetime.fromtimestamp(time.time()-600, timezone.utc).isoformat(), 'items': [{'paper_id': 'P-example', 'revision': 1, 'status': 'queued'}, {'paper_id': 'P-another', 'revision': 1, 'status': 'processing', 'started_at': time.time()-600}]}
    result = with_retry_status(batch)
    assert result['items'][0]['retryable'] is True
    assert result['items'][1]['retryable'] is True
    print('FIXED: interrupted queued items offer retry')
