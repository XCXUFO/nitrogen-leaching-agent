from __future__ import annotations

import pytest

from src.agent.prompt import build_messages
from tests.test_agent_runtime import ask, client, upload
from tests.test_composition import DOCUMENT, service


QUESTION = "氮素淋失主要受哪些因素影响？"
EXPLANATION = "氮素淋失受水分下渗、土壤中可迁移氮的供应和作物吸收共同影响。\n\n降雨与灌溉影响下渗过程，施肥与作物吸收影响可供迁移的氮。"


@pytest.mark.parametrize("documents", [[], ["12. X. Ju, C. Zhang, Nitrogen cycling in maize, 2017.\n13. Z. Wang, J. Li, Nitrate leaching in maize, 2018."]])
def test_general_factors_without_body_evidence_still_generate_an_explanation(client, documents):
    knowledge, retriever, llm = service(text=EXPLANATION + " [99]", documents=documents)
    client.app.state.chat_service = knowledge

    response = ask(client, QUESTION)

    assert response.status_code == 200
    result = response.json()
    assert result["agent_route"] == "KNOWLEDGE" and result["outcome"] == "complete"
    assert result["model"] == "fake-model" and result["warnings"] == []
    assert result["answer"].strip() == EXPLANATION
    assert result["citations"] == result["evidence"] == []
    assert len(retriever.calls) == 1
    assert "当前任务是解释一般影响因素" in llm.last_messages[0].content
    assert "supporting_quote" not in llm.last_messages[0].content
    trace = client.app.state.agent_runtime.runs.get(result["run_id"])
    assert [call.skill for call in trace.tool_calls] == ["knowledge_search"]
    assert trace.retrieval[0]["status"] == "no_match"
    assert trace.retrieval[-1]["stage"] == "model_context"
    assert trace.retrieval[-1]["adopted_chunk_ids"] == []


def test_general_factors_can_combine_body_evidence_and_general_knowledge(client):
    answer = "该玉米研究条件下，排水可使硝态氮向根区以下迁移。[1]\n\n通常，作物吸收也影响剩余氮量。"
    knowledge, _, llm = service(text=answer, documents=[DOCUMENT])
    client.app.state.chat_service = knowledge

    result = ask(client, QUESTION).json()

    assert result["answer"] == answer and result["outcome"] == "complete"
    assert len(result["citations"]) == len(result["evidence"]) == 1
    assert result["citations"][0]["chunk_id"] == "synthetic-0"
    assert "面向用户的表达规则" in llm.last_messages[0].content
    assert "【参考资料】" in llm.last_messages[0].content
    assert DOCUMENT in llm.last_messages[0].content


@pytest.mark.parametrize("question", [
    "哪些因素对这个问题影响最大，为什么？",
    "哪些因素对这个问题的影响是最大的，为什么？",
    "哪些因素影响最大，为什么？",
    "哪个因素最重要，为什么？",
    "这些因素中哪个作用最大？",
    "其中哪些因素贡献最高，为什么？",
])
@pytest.mark.parametrize("attachment", ["none", "legacy", "session"])
def test_factor_ranking_followup_keeps_explanation_and_subject(client, question, attachment):
    knowledge, retriever, llm = service(text=EXPLANATION, documents=[])
    client.app.state.chat_service = knowledge
    history = [{"role": "user", "content": QUESTION}, {"role": "assistant", "content": EXPLANATION}]

    payload = {"query": question, "session_id": "test-session", "history": history}
    if attachment == "legacy":
        payload["file_id"] = "expired-token"
    else:
        payload["file_ids"] = ["expired-token"] if attachment == "session" else []
    response = client.post("/api/chat", json=payload)

    assert response.status_code == 200
    result = response.json()
    assert result["agent_route"] == "KNOWLEDGE" and result["outcome"] == "complete"
    assert EXPLANATION in result["answer"] and result["file_evidence"] == []
    assert "请先上传" not in result["answer"]
    assert QUESTION in retriever.calls[-1][0] and question in retriever.calls[-1][0]
    assert "当前任务是解释一般影响因素" in llm.last_messages[0].content
    trace = client.app.state.agent_runtime.runs.get(result["run_id"])
    assert trace.understanding["context_relation"] == "followup"
    assert trace.understanding["intents"] == ["knowledge"]
    assert [call.skill for call in trace.tool_calls] == ["knowledge_search"]


def test_long_previous_answer_does_not_hide_factor_subject(client):
    knowledge, retriever, llm = service(text=EXPLANATION, documents=[])
    client.app.state.chat_service = knowledge
    result = ask(client, "哪些因素对这个问题影响最大，为什么？", history=[
        {"role": "user", "content": QUESTION},
        {"role": "assistant", "content": EXPLANATION * 30},
    ]).json()

    assert result["agent_route"] == "KNOWLEDGE" and result["outcome"] == "complete"
    assert QUESTION in retriever.calls[-1][0]
    assert QUESTION in llm.last_messages[-1].content


@pytest.mark.parametrize("question", [
    "氮素淋失的哪些因素影响最大，为什么？",
    "降水和灌溉对硝态氮淋失的影响，哪个作用最大？",
])
def test_standalone_factor_importance_is_not_a_table_statistic(client, question):
    result = ask(client, question, file="expired-token").json()

    assert result["agent_route"] == "KNOWLEDGE" and result["file_evidence"] == []
    trace = client.app.state.agent_runtime.runs.get(result["run_id"])
    assert trace.understanding["intents"] == ["knowledge"]


def test_factor_ranking_keeps_source_scope_across_followup_chain(client):
    knowledge, retriever, llm = service(documents=[])
    client.app.state.chat_service = knowledge
    result = ask(client, "哪些因素对这个问题影响最大，为什么？", history=[
        {"role": "user", "content": "只根据知识库文献回答：" + QUESTION},
        {"role": "assistant", "content": "当前没有正文证据。"},
        {"role": "user", "content": "这些因素怎样相互作用？"},
        {"role": "assistant", "content": "仍需正文依据。"},
    ]).json()

    assert result["outcome"] == "clarification" and llm.last_messages is None
    assert result["warnings"][0]["code"] == "mechanism_evidence_missing"
    assert "氮素淋失" in retriever.calls[-1][0]
    assert "请先上传" not in result["answer"]


@pytest.mark.parametrize("attached", [False, True])
def test_explicit_extremum_and_reason_keep_file_workflow(client, tmp_path, attached):
    token = upload(client, tmp_path) if attached else None
    result = ask(client, "硝态氮最大值是多少，为什么可能这么高？", file=token).json()

    assert result["agent_route"] == ("COMPOSED" if attached else "CLARIFY")
    if attached:
        assert result["file_evidence"][0]["value"] == 1.5
    else:
        assert "请先上传" in result["answer"]


def test_general_crop_factors_use_current_prompt_instead_of_saved_short_claims(client):
    knowledge, retriever, llm = service(text=EXPLANATION, documents=[])
    client.app.state.chat_service = knowledge
    prompts = client.app.state.agent_runtime.runs.prompts
    selected = prompts.save("详细因素解释", "充分展开解释各因素的作用过程。", "dev")
    prompts.activate(selected["prompt_id"], "dev")

    result = ask(client, "玉米农田" + QUESTION).json()

    assert result["outcome"] == "complete" and result["model"] == "fake-model"
    assert EXPLANATION in result["answer"] and len(retriever.calls) == 1
    assert selected["text"] in llm.last_messages[0].content
    assert "当前作物约束：玉米" in llm.last_messages[-1].content


@pytest.mark.parametrize("question", [
    "根据文献，" + QUESTION,
    "只根据知识库回答：" + QUESTION,
    "论文 [79] 中" + QUESTION,
])
def test_explicit_source_questions_do_not_fall_back_to_general_knowledge(client, question):
    knowledge, _, llm = service(text=EXPLANATION, documents=[])
    client.app.state.chat_service = knowledge

    result = ask(client, question).json()

    assert result["outcome"] == "clarification" and llm.last_messages is None
    assert result["warnings"][0]["code"] == "mechanism_evidence_missing"
    assert EXPLANATION not in result["answer"] and result["citations"] == []


def test_followup_retains_explicit_source_scope(client):
    knowledge, _, llm = service(text=EXPLANATION, documents=[])
    client.app.state.chat_service = knowledge

    result = ask(client, "上述氮素淋失主要受哪些因素影响？", history=[
        {"role": "user", "content": "只根据知识库文献解释氮素淋失。"},
        {"role": "assistant", "content": "当前未获得正文证据。"},
    ]).json()

    assert result["outcome"] == "clarification" and llm.last_messages is None
    assert result["warnings"][0]["code"] == "mechanism_evidence_missing"


def test_regular_source_qa_keeps_its_grounding_policy():
    from src.rag.retriever import RetrievalResult
    hit = RetrievalResult("body", DOCUMENT, .9, {"source": "synthetic.txt"})

    messages = build_messages("论文的结论是什么？", [hit], max_context_chars=4000)

    assert "回答必须基于下面给出的参考资料" in messages[0].content
    assert "当前任务是解释一般影响因素" not in messages[0].content
