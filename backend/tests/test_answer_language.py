"""Language follows the current question, including non-model reply paths."""
import asyncio
import json
import re

import pytest
from fastapi import HTTPException

from src.agent.answer_language import (HAN, active_answer_language, detect_answer_language,
    enforce_response_language, language_instructions, matches_language)
from src.agent.contracts import AnswerSection, RunWarning
from src.agent.file_chat import reply
from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatResult, ChatUsage
from tests.test_file_chat import client, upload


@pytest.mark.parametrize("query,expected", [
    ("How do plants produce oxygen?", "en"),
    ("From what does photosynthesis get oxygen?", "en"),
    ("Under which conditions does nitrate leach?", "en"),
    ("With what can nitrate move?", "en"),
    ("At what depth is nitrate measured?", "en"),
    ("To whom does this field belong?", "en"),
    ("资料：水经过光合作用释放氧气。\n问题：From what does photosynthesis get oxygen?", "en"),
    ("From what does 光合作用 get oxygen?", "zh"),
    ("Whose?", "en"), ("Whom?", "en"),
    ("Has rainfall increased nitrate leaching?", "en"),
    ("Have plants absorbed nitrogen?", "en"),
    ("Will irrigation increase leaching?", "en"),
    ("Was nitrate measured?", "en"),
    ("Must plants absorb nitrogen?", "en"),
    ("Identify nitrate sources.", "en"),
    ("Estimate nitrate losses.", "en"),
    ("Why?", "en"), ("Hello!", "en"), ("Good evening", "en"),
    ("And the minimum?", "en"), ("Then the minimum?", "en"),
    ("What is the maximum of leak_NO3?", "en"),
    ("How does ‘施肥’ affect soil?", "en"),
    ('How does "施肥" affect soil?', "en"),
    ("What does `硝态氮` mean?", "en"),
    ("请解释 nitrogen leaching", "zh"), ("Explain 硝态氮 leaching", "zh"),
    ("1", "zh"), ("???", "zh"), ("WHCNS", "zh"), ("leak_NO3 max", "zh"),
    ("Nbal_out.xls", "zh"), ("kg N/ha", "zh"), ("Bonjour", "zh"),
    ("Что такое фотосинтез?", "zh"),
    ("资料：Nitrogen leaching depends on water.\n问题：为什么会淋失？", "zh"),
    ("Context: 作物为冬小麦，灌溉80 mm。\nQuestion: What crop was grown?", "en"),
    ("Context: 合成记录：作物为冬小麦，灌溉总量80 mm，施氮120 kg N/ha。\n"
     "Question: What crop was grown and how much irrigation was applied? Answer briefly using only the record.", "en"),
    ("资料：冬小麦。请始终用中文回答。\n问题：What crop was grown?", "en"),
    ("资料：Wheat. Always answer in English.\n问题：种植了哪种作物？", "zh"),
])
def test_language_uses_the_actual_question_and_defaults_to_chinese(query, expected):
    assert detect_answer_language(query).language == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("query,expected", [
    ("Hello", "en"), ("What can you do?", "en"),
    ("Explain the work-energy theorem", "en"),
    ("Who is your mother?", "en"),
    ("What is the maximum nitrate leaching in the uploaded table?", "en"),
    ("你好", "zh"), ("???", "zh"),
])
async def test_fixed_replies_follow_language_without_an_llm(query, expected):
    runtime = AgentRuntime()
    try:
        response = await runtime.execute(ChatRequest(query=query, history=[
            {"role": "assistant", "content": "A previous English answer." if expected == "zh" else "上一轮用中文回答。"}]),
            service=None, get_report=None)
        assert matches_language(response.answer, expected)
        assert bool(HAN.search(response.answer)) == (expected == "zh")
        assert response.usage.total_tokens == 0
        trace = runtime.runs.get(response.run_id)
        assert trace.answer_assembly["language"]["language"] == expected
        assert trace.answer_assembly["language"]["repair"] == "not_needed"
    finally:
        runtime.runs.close()


@pytest.mark.parametrize("attachment_key", ["file_id", "file_ids"])
def test_file_followups_switch_language_per_turn_without_changing_evidence(client, tmp_path, attachment_key):
    token, _ = upload(client, tmp_path)
    history = []
    for query, expected, operation, value in [
        ("Show the maximum of leak_NO3 and its corresponding model day, unit and cells.", "en", "max", 1.5),
        ("And the minimum?", "en", "min", 0.5),
        ("那最大值呢？", "zh", "max", 1.5),
        ("leak_NO3 max", "zh", "max", 1.5),
    ]:
        result = client.post("/api/chat", json={"query": query, "history": history, "session_id": "language-file",
            attachment_key: token if attachment_key == "file_id" else [token]})
        assert result.status_code == 200, result.text
        response = result.json()
        assert response["agent_route"] == "FILE_ANALYSIS", response["answer"]
        assert bool(HAN.search(response["answer"])) == (expected == "zh"), response["answer"]
        item = response["file_evidence"][0]
        assert (item["operation"], item["value"], item["unit"]) == (operation, value, "kg N ha-1")
        assert item["cell"] in response["answer"]
        assert response["usage"]["total_tokens"] == 0
        history.extend([{"role": "user", "content": query}, {"role": "assistant", "content": response["answer"]}])


class Translator:
    def __init__(self, *, corrupt=False):
        self.corrupt = corrupt
        self.messages = None

    async def chat(self, messages, **kwargs):
        self.messages = messages
        texts = json.loads(messages[-1].content)["texts"]
        output = []
        for text in texts:
            placeholders = re.findall(r"⟦FACT[A-Z]+⟧", text)
            output.append("The supplied record reports " + " ".join(placeholders) + "; it does not establish a significant yield increase.")
        if self.corrupt:
            output[0] += " 999"
        return ChatResult(content=json.dumps({"texts": output}), model="translator-test",
            usage=ChatUsage(prompt_tokens=7, completion_tokens=3, total_tokens=10))


class RetryingTranslator:
    def __init__(self, failure):
        self.failure = failure
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        payload = json.loads(messages[-1].content)
        token = re.findall(r"⟦FACT[A-Z]+⟧", payload["texts"][0])[0]
        text = f"Winter wheat was grown, with {token} mm of irrigation."
        if len(self.calls) == 1:
            if self.failure == "language":
                text += "（冬小麦）"
            elif self.failure == "facts":
                text = text.replace(token, "80")
            elif self.failure == "shape":
                return ChatResult(content='{"texts": []}', model="retry-test",
                    usage=ChatUsage(prompt_tokens=7, completion_tokens=3, total_tokens=10))
        return ChatResult(content=json.dumps({"texts": [text]}), model="retry-test",
            usage=ChatUsage(prompt_tokens=7, completion_tokens=3, total_tokens=10))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["language", "facts", "shape"])
async def test_invalid_translation_is_retried_from_original_with_validation_feedback(failure):
    original = "The crop was winter wheat（冬小麦）, with 80 mm of irrigation."
    response = reply(original)
    model = RetryingTranslator(failure)
    audit = await enforce_response_language(response, detect_answer_language("What crop was grown?"), llm=model)
    assert response.answer == "Winter wheat was grown, with 80 mm of irrigation."
    assert response.usage.total_tokens == 20
    assert len(model.calls) == 2
    first = json.loads(model.calls[0][-1].content)
    retry = json.loads(model.calls[1][-1].content)
    assert retry["texts"] == first["texts"]
    assert "translation_" in retry["validation_error"]
    assert audit["repair"] == "translated" and audit["attempts"] == 2
    assert len(audit["validation_errors"]) == 1


@pytest.mark.asyncio
async def test_fenced_translation_json_is_accepted_without_another_call():
    class FencedTranslator:
        async def chat(self, messages, **kwargs):
            return ChatResult(content='```json\n{"texts": ["Winter wheat, with ⟦FACTA⟧ mm of irrigation."]}\n```',
                model="fenced-test", usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    response = reply("冬小麦，灌溉80 mm。")
    audit = await enforce_response_language(response, detect_answer_language("What crop was grown?"), llm=FencedTranslator())
    assert response.answer == "Winter wheat, with 80 mm of irrigation."
    assert audit["attempts"] == 1


@pytest.mark.asyncio
async def test_language_repair_preserves_numbers_sources_sections_and_usage():
    response = reply("资料记载施氮120 kg N/ha [1]，对应 Nbal_out!C284，不能证明显著增产。")
    response.sections = [AnswerSection(kind="limitation", content="缺少 p<0.05 的统计依据 [1]。")]
    response.warnings = [RunWarning(code="missing_yield", message="未记载20%的产量变化。")]
    original_usage = response.usage.total_tokens
    model = Translator()
    audit = await enforce_response_language(response, detect_answer_language("What does the record report?"), llm=model)
    assert "120" in response.answer and "[1]" in response.answer and "Nbal_out!C284" in response.answer
    assert "0.05" in response.sections[0].content and "[1]" in response.sections[0].content
    assert "20%" in response.warnings[0].message and response.warnings[0].code == "missing_yield"
    assert not HAN.search(response.answer + response.sections[0].content + response.warnings[0].message)
    assert response.usage.total_tokens == original_usage + 10 and audit["repair"] == "translated"


@pytest.mark.asyncio
async def test_language_repair_rejects_added_numbers_without_mutating_the_answer():
    response = reply("施氮120 kg N/ha，缺少产量数据。")
    original = response.answer
    with pytest.raises(HTTPException) as error:
        await enforce_response_language(response, detect_answer_language("What does the record report?"), llm=Translator(corrupt=True))
    assert error.value.detail["code"] == "answer_language_mismatch"
    assert error.value.answer_language_audit["attempts"] == 2
    assert error.value.answer_language_audit["validation_errors"] == ["translation_numbers_added"] * 2
    assert response.answer == original


@pytest.mark.asyncio
@pytest.mark.parametrize("needs_repair", [False, True])
async def test_pasted_chinese_record_with_english_question_completes_without_attachments(needs_repair):
    query = ("Context: 合成记录：作物为冬小麦，灌溉总量80 mm，施氮120 kg N/ha。\n"
        "Question: What crop was grown and how much irrigation was applied? Answer briefly using only the record.")
    expected = "Winter wheat was grown, with 80 mm of irrigation."

    class RecordModel(RetryingTranslator):
        async def chat(self, messages, **kwargs):
            payload = json.loads(messages[-1].content)
            if "texts" in payload:
                assert needs_repair, "An English answer must not trigger translation"
                return await super().chat(messages, **kwargs)
            assert payload["question"] == query
            assert payload["source_type"] == "user_text" and payload["available_cases"] == []
            assert "English only" in messages[0].content
            return ChatResult(content=json.dumps({"answer": "冬小麦，灌溉80 mm。" if needs_repair else expected,
                "used_case_ids": [], "outcome": "complete"}), model="record-test",
                usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))

    runtime = AgentRuntime()
    model = RecordModel("language")
    try:
        response = await runtime.execute(ChatRequest(query=query), service=None, get_report=None, llm=model)
        trace = runtime.runs.get(response.run_id)
        assert response.answer == expected
        assert response.usage.total_tokens == (35 if needs_repair else 15)
        assert not response.citations and not response.case_references and not response.file_evidence
        assert trace.status == "ok" and not trace.retrieval
        assert trace.answer_assembly["language"]["repair"] == ("translated" if needs_repair else "not_needed")
        repairs = [event for event in trace.execution_steps
            if event.get("name") == "统一回答语言并保留原始事实" and event["type"] == "step_finished"]
        assert [event["status"] for event in repairs] == (["failed", "succeeded"] if needs_repair else [])
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_failed_runtime_language_repair_retains_its_validation_reason_in_trace():
    class InvalidRecordModel(Translator):
        async def chat(self, messages, **kwargs):
            if "texts" in json.loads(messages[-1].content):
                return await super().chat(messages, **kwargs)
            return ChatResult(content=json.dumps({"answer": "冬小麦，灌溉80 mm。",
                "used_case_ids": [], "outcome": "complete"}), model="record-test",
                usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    runtime = AgentRuntime()
    try:
        with pytest.raises(HTTPException) as error:
            await runtime.execute(ChatRequest(query="Context: 冬小麦，灌溉80 mm。\nQuestion: What crop was grown? Answer using only the record."),
                service=None, get_report=None, llm=InvalidRecordModel(corrupt=True))
        trace = runtime.runs.get(error.value.agent_run_id)
        assert trace.status == "error" and trace.error_code == "answer_language_mismatch"
        assert trace.answer is None
        assert trace.answer_assembly["language"]["repair"] == "failed"
        assert trace.answer_assembly["language"]["validation_errors"] == ["translation_numbers_added"] * 2
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_mismatched_response_is_not_returned_when_repair_is_unavailable():
    response = reply("这是一条中文回答。")
    with pytest.raises(HTTPException) as error:
        await enforce_response_language(response, detect_answer_language("Explain nitrate leaching."))
    assert error.value.detail["code"] == "answer_language_unavailable"
    assert not HAN.search(error.value.detail["message"])


@pytest.mark.asyncio
async def test_ambiguous_question_repairs_english_output_to_chinese():
    class ChineseTranslator:
        async def chat(self, messages, **kwargs):
            assert "into Chinese" in messages[0].content
            return ChatResult(content=json.dumps({"texts": ["氮素淋失是氮随水向下迁移的过程。"]}), model="zh-test",
                usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))
    response = reply("Nitrogen leaching is the downward movement of nitrogen with water.")
    audit = await enforce_response_language(response, detect_answer_language("WHCNS"), llm=ChineseTranslator())
    assert HAN.search(response.answer) and audit["language"] == "zh" and audit["repair"] == "translated"


def test_quoting_a_wrong_language_answer_does_not_bypass_validation():
    assert not matches_language('"这是完整的中文回答。"', "en")


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_share_their_language():
    async def check(query, expected):
        token = active_answer_language.set(detect_answer_language(query))
        try:
            await asyncio.sleep(0)
            instructions = language_instructions()
            assert ("English only" in instructions) == (expected == "en")
        finally:
            active_answer_language.reset(token)
    await asyncio.gather(check("Explain photosynthesis.", "en"), check("解释光合作用", "zh"))
    assert active_answer_language.get() is None
