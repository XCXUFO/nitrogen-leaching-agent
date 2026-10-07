from __future__ import annotations

import json
import time
import hashlib
import re
from pathlib import Path

import fitz

import pytest

from src.agent.chat_service import ChatService
from src.agent.curated_evidence import excerpts
from src.agent.composition import MechanismEvidenceError, is_event_mechanism_source, split_composed, validate_claims
from src.rag.retriever import RetrievalResult
from tests.test_agent_runtime import ask, client, upload
from tests.test_chat_service import FakeLLMClient, FakeRetriever

QUOTE = "Drainage can transport nitrate below the maize root zone."
DOCUMENT = "Synthetic maize study: after irrigation, drainage reached a peak. " + QUOTE


def payload(**overrides):
    claim = {"text": "该玉米研究条件下，排水可能促进硝态氮向根区以下迁移。",
             "citation_index": 1, "supporting_quote": QUOTE, **overrides}
    return json.dumps({"claims": [claim]}, ensure_ascii=False)


def service(*, text=None, documents=None, error=None, budget=4000):
    documents = documents if documents is not None else [DOCUMENT]
    retriever = FakeRetriever([RetrievalResult(chunk_id=f"synthetic-{i}", document=doc, score=0.8,
                                              metadata={"source": f"synthetic-{i}.txt"}) for i, doc in enumerate(documents)], error=error)
    llm = FakeLLMClient(payload() if text is None else text)
    return ChatService(retriever, llm, top_k=5, max_context_chars=budget, temperature=0.1), retriever, llm


@pytest.mark.parametrize("query", ["硝态氮最大值是多少，为什么可能这么高？", "硝态氮最大值和原因", "硝态氮最大值，并结合文献解释可能的原因"])
def test_composed_answer_preserves_numeric_facts_and_binds_both_sources(client, tmp_path, query):
    knowledge, retriever, llm = service()
    client.app.state.chat_service = knowledge
    token = upload(client, tmp_path)
    body = ask(client, query, file=token).json()
    assert body["agent_route"] == "COMPOSED"
    assert body["outcome"] == "complete", body
    assert body["attachment"]["status"] == "ready"
    assert body["file_evidence"][0]["value"] == 1.5
    assert body["file_evidence"][0]["cell"] == "Nbal_out!C3"
    assert "无法确认峰值成因" in body["answer"] and "同期天气" in body["answer"]
    assert len(retriever.calls) == 1
    messages = "\n".join(message.content for message in llm.last_messages)
    assert "1.5" not in messages and "Nbal_out" not in messages and token not in messages
    ids = {item["evidence_id"] for item in body["evidence"]}
    assert len(ids) == 2
    facts, limitation, inference = body["sections"][:3]
    assert facts["kind"] == "file_observation" and facts["evidence_ids"]
    assert limitation["kind"] == "limitation" and not limitation["evidence_ids"]
    assert inference["kind"] == "literature_inference" and inference["evidence_ids"]
    assert set(facts["evidence_ids"] + inference["evidence_ids"]) == ids
    trace = client.app.state.agent_runtime.runs.get(body["run_id"])
    assert [call.skill for call in trace.tool_calls] == ["file_inspector", "whcns_analyzer", "knowledge_search"]
    assert trace.outcome == "complete"
    assert trace.sections[2].evidence_ids == inference["evidence_ids"]


@pytest.mark.parametrize("failure", ["unconfigured", "retrieval", "empty", "bad_quote", "invalid_json"])
def test_knowledge_failure_keeps_computed_value_and_reports_partial(client, tmp_path, failure):
    if failure == "unconfigured":
        client.app.state.chat_service = None
    else:
        kwargs = {"error": RuntimeError("private path /secret")} if failure == "retrieval" else {"documents": []} if failure == "empty" else {"text": payload(supporting_quote="invented evidence not in document")} if failure == "bad_quote" else {"text": "not json"}
        client.app.state.chat_service = service(**kwargs)[0]
    token = upload(client, tmp_path)
    body = ask(client, "硝态氮最大值是多少，为什么可能这么高？", file=token).json()
    assert body["route"] == "composed" and body["outcome"] == "partial"
    assert body["file_evidence"][0]["value"] == 1.5
    assert body["citations"] == []
    assert "暂不推断原因" in body["answer"] and "/secret" not in json.dumps(body)
    trace = client.app.state.agent_runtime.runs.get(body["run_id"])
    assert trace.tool_calls[-1].status == "error"
    assert trace.warnings and trace.outcome == "partial"
    # A failed literature step does not erase a verified file metric.
    assert ask(client, "那最小值呢？", file=token).json()["file_evidence"][0]["value"] == 0.5


@pytest.mark.parametrize("file_problem", ["bad_unit", "expired"])
def test_failed_file_only_allows_general_mechanisms_and_never_old_values(client, tmp_path, file_problem):
    client.app.state.chat_service = service()[0]
    good = upload(client, tmp_path)
    ask(client, "leak_NO3 最大值", file=good)
    if file_problem == "bad_unit":
        token = upload(client, tmp_path, name="invalid.xlsx", edit=lambda s: setattr(s["C1"], "value", "leak_NO3(mg L-1)"))
    else:
        token = good
        client.app.state.file_store.entries[token].expires_at = time.monotonic() - 1
    body = ask(client, "硝态氮最大值和原因", file=token).json()
    assert body["outcome"] == "partial"
    assert body["file_evidence"] == [] and body["citations"]
    assert "1.5" not in body["answer"]
    assert body["attachment"]["status"] == ("invalid" if file_problem == "bad_unit" else "expired")
    assert all(item["source_type"] == "literature" for item in body["evidence"])


def test_both_dependencies_failing_is_a_clarification_not_a_success(client, tmp_path):
    client.app.state.chat_service = None
    token = upload(client, tmp_path, edit=lambda s: setattr(s["C3"], "value", "text"))
    body = ask(client, "硝态氮最大值和原因", file=token).json()
    assert body["outcome"] == "clarification"
    assert body["evidence"] == body["citations"] == body["file_evidence"] == []
    assert len(body["warnings"]) == 2


@pytest.mark.parametrize("query", ["前10天硝态氮最大值，为什么这么高？", "硝态氮和磷最大值和原因", "硝态氮浓度最大值和原因", "硝态氮最大值和原因，再给我一个施肥方案"])
def test_composition_does_not_drop_extra_requirements(client, tmp_path, query):
    knowledge, retriever, _ = service()
    client.app.state.chat_service = knowledge
    token = upload(client, tmp_path)
    body = ask(client, query, file=token).json()
    assert body["route"] == "clarification"
    assert body["evidence"] == [] and retriever.calls == []


def test_missing_file_requests_upload_before_composition(client):
    body = ask(client, "硝态氮最大值和原因").json()
    assert body["route"] == "clarification" and "上传" in body["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides,code", [
    ({"citation_index": 9}, "mechanism_citation_invalid"),
    ({"supporting_quote": "This text is not in the retrieved evidence."}, "mechanism_quote_unverified"),
    ({"text": "本次峰值由排水造成。"}, "mechanism_scope_invalid"),
])
async def test_unverifiable_mechanisms_are_rejected(overrides, code):
    knowledge, _, _ = service(text=payload(**overrides))
    with pytest.raises(MechanismEvidenceError) as caught:
        await knowledge.explain_mechanisms("硝态氮淋失", crop="玉米")
    assert caught.value.code == code


@pytest.mark.asyncio
async def test_crop_mismatch_and_missing_context_do_not_call_generator():
    for kwargs in ({"documents": ["Synthetic paddy rice evidence only."]}, {"documents": []}, {"budget": 4}):
        knowledge, _, llm = service(**kwargs)
        with pytest.raises(MechanismEvidenceError):
            await knowledge.explain_mechanisms("硝态氮淋失", crop="玉米")
        assert llm.last_messages is None


@pytest.mark.asyncio
async def test_only_actual_context_can_be_cited_and_repeated_citations_keep_quotes():
    second_quote = "Soil texture also affects transport in this synthetic example."
    text = json.dumps({"claims": [json.loads(payload())["claims"][0],
                                {"text": "所述条件下土壤质地也可能影响迁移。", "citation_index": 1, "supporting_quote": second_quote}]})
    knowledge, _, _ = service(text=text, documents=[DOCUMENT + " " + second_quote])
    result = await knowledge.explain_mechanisms("硝态氮淋失", crop="玉米")
    assert len(result.citations) == 1 and len(result.claims) == 2
    assert QUOTE in result.citations[0].snippet and second_quote in result.citations[0].snippet


def test_splitter_only_accepts_complete_supported_suffix():
    assert split_composed("硝态氮最大值是多少，为什么可能这么高？") == "硝态氮最大值是多少"
    assert split_composed("硝态氮最大值和原因") == "硝态氮最大值"
    assert split_composed("硝态氮最大值和原因并给出施肥方案") is None


def test_pdf_chinese_line_wraps_resolve_to_original_source_span():
    original = "填闲作物 吸氮和阻控硝酸盐淋失的能力还与根\n系生长速率有关。"
    claims = validate_claims(payload(supporting_quote=original.replace(" ", "").replace("\n", "")), [original])
    assert claims[0].supporting_quote == original


@pytest.mark.parametrize("document,quote", [
    ("土壤氮素淋失量未显著增加。", "土壤氮素淋失量显著增加。"),
    ("Loss was 10.5 kg N ha-1 in maize.", "Loss was 105 kg N ha-1 in maize."),
    ("Nitrate does not increase.", "Nitratedoesnotincrease."),
])
def test_quote_normalization_never_changes_words_numbers_or_negation(document, quote):
    with pytest.raises(MechanismEvidenceError, match="mechanism_quote_unverified"):
        validate_claims(payload(supporting_quote=quote), [document])


@pytest.mark.asyncio
async def test_bibliography_titles_are_not_mechanism_evidence():
    references = "12. X. Ju, C. Zhang, Nitrogen cycling in maize, 2017.\n13. Z. Wang, J. Li, Nitrate leaching in maize, 2018."
    knowledge, _, llm = service(documents=[references])
    with pytest.raises(MechanismEvidenceError, match="mechanism_evidence_missing"):
        await knowledge.explain_mechanisms("玉米硝态氮淋失", crop="玉米")
    assert llm.last_messages is None


def test_peak_requires_event_scale_body_and_rejects_annual_or_mitigation_claims():
    event = "绿洲春玉米田中，灌溉或较强降雨后水分渗漏出现峰值，硝酸盐淋洗量也随之增加。"
    assert is_event_mechanism_source(event)
    assert not is_event_mechanism_source("降水量大的年份土壤氮素淋失量高于降水量小的年份。")
    with pytest.raises(MechanismEvidenceError, match="mechanism_scale_invalid"):
        validate_claims(payload(text="降水量大的年份更容易出现单日峰值。", supporting_quote=event), [event], purpose="peak")
    mitigation = "灌水后减少单次灌溉量可阻控硝酸盐淋失峰值。"
    with pytest.raises(MechanismEvidenceError, match="mechanism_scale_invalid"):
        validate_claims(payload(text="填闲甜玉米可阻控硝酸盐淋失。", supporting_quote=mitigation), [mitigation], purpose="peak")


@pytest.mark.asyncio
async def test_curated_maize_factors_and_peak_have_distinct_supported_scopes():
    knowledge, retriever, llm = service(documents=[])
    factors = await knowledge.explain_mechanisms("玉米氮素淋失的因素", crop="玉米", purpose="maize_factors")
    peak = await knowledge.explain_mechanisms("玉米单日峰值", crop="玉米", purpose="peak")
    assert len(factors.claims) == 3 and len(peak.claims) == 2
    assert all("008_shi_2018" in citation.source for citation in peak.citations)
    assert "年份" not in peak.answer and "填闲" not in peak.answer
    assert llm.last_messages is None and retriever.calls == []


def test_curated_quotes_are_present_in_unchanged_source_pdfs():
    root = Path(__file__).resolve().parents[2]
    cards = excerpts()["modes"]["maize_factors"] + excerpts()["modes"]["peak"]
    sources = [(card, root / card["source"].removeprefix("../")) for card in cards]
    if any(not source.is_file() for _, source in sources):
        pytest.skip("Source PDFs are private local verification assets")
    for card, source in sources:
        assert hashlib.sha256(source.read_bytes()).hexdigest() == card["source_sha256"]
        document = "".join(page.get_text() for page in fitz.open(source))
        normalized = lambda value: re.sub(r"\s+", "", value)
        assert normalized(card["supporting_quote"]) in normalized(document)


def test_k01_original_first_question_returns_article_evidence(client):
    knowledge, retriever, llm = service()
    client.app.state.chat_service = knowledge
    body = ask(client, "玉米农田氮素淋失主要受哪些因素影响？").json()
    assert body['agent_route'] == 'KNOWLEDGE' and body['outcome'] == 'complete'
    assert body['model'] == 'curated-excerpts-v1'
    assert len(body['citations']) == 2 and all(c['title'] and c['snippet'] for c in body['citations'])
    assert '灌溉或较强降雨' in body['answer'] and '施氮量' in body['answer']
    assert '不能直接代表所有玉米田' in body['answer']
    trace = client.app.state.agent_runtime.runs.get(body['run_id'])
    assert trace.state_after.crop == '玉米'
    assert all(e.provenance['review_identity'] == 'AI-assisted source checking' for e in trace.evidence)
    assert llm.last_messages is None and retriever.calls == []


@pytest.mark.parametrize('fence', ['json', 'JSON', ''])
def test_json_fences_do_not_discard_verified_claims(fence):
    claims = validate_claims(f'```{fence}\n{payload()}\n```', [DOCUMENT])
    assert claims[0].supporting_quote == QUOTE
    with pytest.raises(MechanismEvidenceError, match='mechanism_quote_unverified'):
        validate_claims(f'```{fence}\n{payload(supporting_quote="not in the original source")}\n```', [DOCUMENT])


@pytest.mark.asyncio
async def test_malformed_mechanism_output_retries_once_and_preserves_quote_checks(monkeypatch):
    knowledge, retriever, llm = service()
    calls = []
    original = llm.chat

    async def answer(messages, **kwargs):
        calls.append(messages)
        llm._content = 'not valid JSON' if len(calls) == 1 else payload()
        return await original(messages, **kwargs)

    monkeypatch.setattr(llm, 'chat', answer)
    result = await knowledge.explain_mechanisms('氮素淋失影响因素')
    assert len(calls) == 2 and len(retriever.calls) == 1
    assert result.claims[0].supporting_quote == QUOTE
    assert result.usage.total_tokens == 30


@pytest.mark.parametrize(('text', 'code', 'expected'), [
    ('invalid JSON', 'mechanism_output_invalid', '格式校验'),
    (payload(supporting_quote='not in the original source'), 'mechanism_quote_unverified', '未通过核对'),
    ('{"claims":[]}', 'mechanism_evidence_missing', '本次检索'),
])
def test_generation_errors_do_not_claim_library_has_no_evidence(client, text, code, expected):
    client.app.state.chat_service = service(text=text)[0]
    body = ask(client, '氮素淋失主要受哪些因素影响？').json()
    assert expected in body['answer']
    assert body['warnings'][0]['code'] == code and body['citations'] == []
    assert '当前没有足以支持' not in body['answer']
