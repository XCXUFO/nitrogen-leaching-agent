"""One bounded execution entry: context, policy, skills, state, evidence, trace."""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from loguru import logger
from openai import APIConnectionError, APIError, APITimeoutError, AuthenticationError, RateLimitError

from src.agent.chat_service import ChatService, RAGQueryError, normalize_citations
from src.agent.contracts import AnswerSection, AttachmentState, Evidence, Route, RunTrace, RunWarning, SkillName, StateSnapshot, TaskState, ToolCall
from src.agent.composition import METRIC_TERMS, MechanismEvidenceError, split_composed
from src.agent.file_chat import FIELD_ALIASES, parse_file_request, reply, requested_fields
from src.model_tools.whcns_results import SCHEMAS
from src.agent.prompt import DialogueTurn
from src.agent.routing import FOLLOWUP, GUIDANCE, crop_scope, decide
from src.agent.skills import KnowledgeUnavailable, SkillRegistry, build_registry
from src.agent.state import ConversationBusy, StateCapacityError, StateStore
from src.api.chat_schema import ChatRequest, ChatResponse
from src.storage.run_store import RunStore


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def snapshot(state: TaskState) -> StateSnapshot:
    return StateSnapshot(crop=state.crop, attachment_ref=digest(state.current_attachment_id) if state.current_attachment_id else None,
                         current_metric=state.current_metric, current_operation=state.current_operation,
                         last_tool=state.last_tool)


def error_code(exc: BaseException) -> str:
    if isinstance(exc, MechanismEvidenceError):
        return exc.code
    if isinstance(exc, HTTPException):
        return exc.detail.get("code", "request_failed") if isinstance(exc.detail, dict) else "request_failed"
    for cls, code in (
        (asyncio.CancelledError, "request_cancelled"),
        (ConversationBusy, "conversation_busy"), (StateCapacityError, "conversation_capacity"),
        (KnowledgeUnavailable, "rag_not_configured"), (RAGQueryError, "rag_query_failed"),
        (AuthenticationError, "llm_auth_failed"), (RateLimitError, "llm_rate_limited"),
        (APITimeoutError, "llm_timeout"), (APIConnectionError, "llm_unreachable"),
        (APIError, "llm_upstream_error"),
    ):
        if isinstance(exc, cls):
            return code
    return "internal_error"


def named_file_mismatch(query: str, selected_name: str) -> bool:
    """A named workbook must be the selected capability; two names need a new workflow."""
    mentions = re.findall(r"\.xlsx?\b", query, re.I)
    return bool(mentions) and (len(mentions) != 1 or selected_name.casefold() not in query.casefold())


def collect_evidence(response: ChatResponse, run_id: str) -> list[Evidence]:
    evidence = []
    for index, item in enumerate(response.file_evidence, 1):
        evidence.append(Evidence(
            evidence_id=f"{run_id}:file:{index}", source_type="file", source_id=item.sha256,
            claim_or_value=item.value, unit=item.unit, status="computed",
            location={"sheet": item.sheet, "cell": item.cell, "day_cell": item.day_cell,
                      "model_day": item.model_day, "data_range": item.data_range, "occurrences": item.occurrences},
            provenance={"filename": item.filename, "field": item.field, "operation": item.operation,
                        "tool_version": item.tool_version, "schema_id": item.schema_id},
        ))
    for item in response.citations:
        evidence.append(Evidence(
            evidence_id=f"{run_id}:literature:{item.index}", source_type="literature", source_id=item.chunk_id,
            claim_or_value=item.snippet,
            location={"citation_index": item.index, "chunk_id": item.chunk_id},
            provenance={"source": item.source, "title": item.title or "", "review_identity":
                        "AI-assisted source checking" if response.model == "curated-excerpts-v1" else "unreviewed retrieval"},
            status="curated" if response.model == "curated-excerpts-v1" else "retrieved",
        ))
    return evidence


class AgentRuntime:
    def __init__(self, *, runs: RunStore | None = None, states: StateStore | None = None,
                 config_version: str = "unconfigured", config_manifest: dict | None = None):
        self.runs = runs if runs is not None else RunStore()
        self.states = states if states is not None else StateStore()
        self.config_version = config_version
        self.config_manifest = config_manifest or {}

    async def _call(self, registry: SkillRegistry, name: SkillName, payload: dict, trace: RunTrace):
        started = time.perf_counter()
        status, failure = "ok", None
        try:
            result = await registry.invoke(name, payload)
            if isinstance(result, ChatResponse) and result.route == "clarification":
                status = "clarification"
            return result
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
            failure = error_code(exc)
            raise
        finally:
            trace.tool_calls.append(ToolCall(skill=name, status=status, error_code=failure,
                                             latency_ms=int((time.perf_counter() - started) * 1000)))

    async def execute(self, body: ChatRequest, *, service: ChatService | None,
                      get_report: Callable[[str], Awaitable[dict]]) -> ChatResponse:
        started = time.perf_counter()
        conversation_id = body.session_id or str(uuid4())
        run_id = str(uuid4())
        trace = RunTrace(run_id=run_id, conversation_ref=digest(conversation_id), input=body.query,
                         history_count=len(body.history),
                         started_at=datetime.now(timezone.utc).isoformat(), state_before=StateSnapshot(),
                         config_version=self.config_version, config_manifest=self.config_manifest)
        response = None
        execution_error = None
        try:
            with self.states.lease(conversation_id, body.file_id, session_files=body.file_ids is not None) as state:
                if body.file_ids is not None:
                    state.session_files_enabled = True
                    # The client sends all session capabilities, including collapsed files.
                    # This also allows replacing expired uploads without keeping dead tokens.
                    state.session_file_ids = list(dict.fromkeys(body.file_ids))
                trace.state_before = snapshot(state)
                try:
                    response = await self._execute(body, state, trace, build_registry(service, get_report))
                except BaseException:
                    # A failed calculation may not leave an earlier metric ready for inference.
                    if trace.decision and trace.decision.route in {Route.FILE_ANALYSIS, Route.COMPOSED}:
                        self.states.clear_metric(state)
                    raise
                finally:
                    trace.state_after = snapshot(state)
            response.answer, response.citations, citation_mapping = normalize_citations(response.answer, response.citations)
            for section in response.sections:
                section.content = re.sub(r"\[(\d+)\](?!\()", lambda match: f"[{citation_mapping[int(match[1])]}]" if int(match[1]) in citation_mapping else "", section.content)
                section.citation_indices = [citation_mapping[index] for index in section.citation_indices if index in citation_mapping]
            response.run_id = run_id
            response.conversation_id = conversation_id
            response.agent_route = trace.decision.route
            response.evidence = collect_evidence(response, run_id)
            for section in response.sections:
                section.evidence_ids = [item.evidence_id for item in response.evidence
                                        if (item.source_type == "literature" and item.location.get("citation_index") in section.citation_indices)
                                        or (item.source_type == "file" and int(item.evidence_id.rsplit(":", 1)[1]) in section.file_evidence_indices)]
            trace.evidence = response.evidence
            trace.sections, trace.warnings, trace.outcome = response.sections, response.warnings, response.outcome
            trace.answer, trace.model, trace.status = response.answer, response.model, "ok"
            return response
        except BaseException as exc:
            execution_error = exc
            trace.status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
            trace.error_code = error_code(exc)
            # The HTTP adapter can attach the same run ID to error responses.
            setattr(exc, "agent_run_id", run_id)
            raise
        finally:
            trace.latency_ms = int((time.perf_counter() - started) * 1000)
            try:
                self.runs.append(trace, session_id=conversation_id, operator_id=body.operator_id)
                if response is not None:
                    response.trace_saved = True
                if execution_error is not None:
                    setattr(execution_error, "agent_trace_saved", True)
            except Exception:
                # Do not turn a successfully computed answer into a retryable failure.
                # Evaluation callers must not treat this as a saved, reviewable run.
                logger.exception("Agent trace persistence failed | run_id={}", run_id)
                if response is not None:
                    response.trace_saved = False

    async def _execute(self, body: ChatRequest, state: TaskState, trace: RunTrace,
                       registry: SkillRegistry) -> ChatResponse:
        crop_changed, crop = crop_scope(body.query)
        if crop_changed:
            state.crop = crop
        session_files = state.session_files_enabled
        trace.decision = decide(body.query, has_file=bool(state.session_file_ids) if session_files else body.file_id is not None)
        route = trace.decision.route
        referent = re.compile(r"(?:它|这个|那个|这|那)(?:的)?(?:有什么用|能解决什么问题|是什么|呢|怎么样)[？?。]*")
        has_subject = any(turn.role == "user" and not (GUIDANCE.fullmatch(turn.content) or FOLLOWUP.fullmatch(turn.content)
                          or referent.fullmatch(turn.content)) for turn in body.history)
        more_context = bool(re.fullmatch(r"(?:还)?有(?:没有)?(?:什么)?(?:其他|其它|更多)(?:的)?(?:信息|内容|结果)(?:不|吗|么|呢)?[？?。]*|还有呢[？?。]*", body.query))
        if more_context and (state.session_file_ids if session_files else body.file_id):
            trace.decision.route = route = Route.FILE_ANALYSIS
            trace.decision.reason_code = "session_file_overview"
        elif more_context and not has_subject:
            trace.decision.route = route = Route.CLARIFY
            trace.decision.reason_code = "unclear_referent"
        if referent.fullmatch(body.query) and not has_subject:
            trace.decision.route = route = Route.FILE_ANALYSIS if session_files and state.session_file_ids else Route.CLARIFY
            trace.decision.reason_code = "unclear_referent"
        if route in {Route.DIRECT, Route.OUT_OF_SCOPE}:
            state.last_tool = "capability_guidance"
            return await self._call(registry, "capability_guidance", {"outside_domain": route == Route.OUT_OF_SCOPE}, trace)
        if route == Route.CLARIFY:
            self.states.clear_metric(state)
            message = ("请先上传 WHCNS 氮/水平衡输出表（.xls 或 .xlsx），再说明要查询的字段及最大值或最小值。"
                       if trace.decision.reason_code == "missing_attachment" else
                       "请补充你指的是哪个模型、指标或问题，以及希望了解的内容；如果要分析结果表，可上传文件并说明字段和统计项。")
            return await self._call(registry, "clarification", {"message": message}, trace)
        if session_files and route in {Route.FILE_ANALYSIS, Route.COMPOSED}:
            return await self._session_files(body, state, trace, registry)
        if route == Route.FILE_ANALYSIS:
            try:
                inspection = await self._call(registry, "file_inspector", {"file_id": body.file_id}, trace)
            except HTTPException as exc:
                if error_code(exc) != "invalid_result_file":
                    raise
                self.states.clear_metric(state)
                trace.decision.route = Route.CLARIFY
                trace.decision.reason_code = "invalid_attachment"
                result = reply(exc.detail["message"])
                result.attachment = AttachmentState.model_validate(exc.detail["attachment"])
                result.warnings = [RunWarning(code="invalid_result_file", message=exc.detail["message"])]
                return result
            if named_file_mismatch(body.query, inspection.report["file"]):
                self.states.clear_metric(state)
                trace.decision.route = Route.CLARIFY
                trace.decision.reason_code = "attachment_name_mismatch"
                result = reply("问题中的文件名与当前选中的文件不一致，或提到了多份文件。请先选择一份对应文件，再查询它的字段与极值。")
                result.attachment = self._ready_attachment(inspection.report)
                return result
            query = body.query
            if state.current_metric and state.last_tool == "whcns_analyzer" and FOLLOWUP.fullmatch(query):
                operation = "最小值" if "最小" in query or "最低" in query else "最大值"
                query = f"{state.current_metric} {operation}及对应日序"
                trace.decision.reason_code = "inherited_metric"
            result = await self._call(registry, "whcns_analyzer", {"query": query, "report": inspection.report}, trace)
            result.attachment = self._ready_attachment(inspection.report)
            if result.file_evidence:
                state.current_metric = result.file_evidence[0].field.split("(")[0]
                state.current_operation = [e.operation for e in result.file_evidence]
                state.last_tool = "whcns_analyzer"
            else:
                self.states.clear_metric(state)
                trace.decision.route = Route.CLARIFY
                trace.decision.reason_code = "unsupported_or_ambiguous_file_query"
            return result
        if route == Route.COMPOSED:
            return await self._compose(body, state, trace, registry)
        history = [DialogueTurn(role=m.role, content=m.content) for m in body.history]
        query = body.query
        if state.crop:
            # Explicit scope changes supersede prior context. Later follow-ups retain
            # necessary dialogue and repeat the constraint even after history truncation.
            if crop_changed:
                history = []
            else:
                changes = [i for i, turn in enumerate(history)
                           if turn.role == "user" and crop_scope(turn.content)[0]]
                if changes:
                    history = history[changes[-1]:]
            query = (f"当前作物约束：{state.crop}。只讨论该作物；不得将其他作物的研究结论直接迁移，"
                     f"证据不足时请明确说明。\n本轮问题：{body.query}")
        state.last_tool = "knowledge_search"
        factor_question = bool(re.search(r"(?:氮素|硝态氮|硝酸盐).*?(?:淋失|淋洗).*?因素|哪些因素.*?(?:淋失|淋洗)", body.query))
        try:
            result = await self._call(registry, "knowledge_search",
                                      {"query": query, "k": body.k, "history": history,
                                       "mode": "mechanisms" if factor_question else "answer", "crop": state.crop,
                                       "purpose": "maize_factors" if factor_question and state.crop == "玉米" else "general"}, trace)
        except MechanismEvidenceError as exc:
            trace.decision.route = Route.CLARIFY
            trace.decision.reason_code = exc.code
            if exc.code == "mechanism_evidence_missing":
                message = "本次检索未获得足以支持这些影响因素的正文证据，不代表知识库中没有相关文献。可补充研究场景或调整问题后重试。"
            elif exc.code == "mechanism_output_invalid":
                message = "已找到候选正文，但本次机制回答的格式校验未通过，暂未生成可核对的结论。请重试；这不代表知识库缺少相关文献。"
            else:
                message = "已找到候选正文，但本次生成的机制结论与引用或适用范围未通过核对。请重试或进一步限定研究场景。"
            result = await self._call(registry, "clarification", {"message": message}, trace)
            result.warnings = [RunWarning(code=exc.code, message=message)]
        return result

    async def _session_files(self, body: ChatRequest, state: TaskState, trace: RunTrace,
                             registry: SkillRegistry) -> ChatResponse:
        """Inspect session workbooks, then calculate only fields actually requested."""
        reports = []
        unavailable = []
        attachment_states = []
        for token in state.session_file_ids:
            try:
                inspection = await self._call(registry, "file_inspector", {"file_id": token}, trace)
                attachment_states.append(self._ready_attachment(inspection.report).model_copy(update={"file_id": token}))
                if not any(report["sha256"] == inspection.report["sha256"] for _, report in reports):
                    reports.append((token, inspection.report))
            except HTTPException as exc:
                if error_code(exc) not in {"file_not_found", "invalid_result_file"}:
                    raise
                unavailable.append(exc.detail["message"])
                attachment_states.append(AttachmentState(file_id=token, filename=exc.detail.get("attachment", {}).get("filename", "会话文件"),
                                                        status="expired" if error_code(exc) == "file_not_found" else "invalid"))

        def clarify(message: str) -> ChatResponse:
            self.states.clear_metric(state)
            trace.decision.route = Route.CLARIFY
            trace.decision.reason_code = "session_file_clarification"
            result = reply(message)
            result.attachments = attachment_states
            return result

        query = split_composed(body.query) if trace.decision.route == Route.COMPOSED else body.query
        if not query:
            return clarify("请说明要分析的字段和统计项，例如“硝态氮最大值及日序”。")
        followup = bool(FOLLOWUP.fullmatch(query))
        all_fields = list(dict.fromkeys(field for schema in SCHEMAS.values() for field in schema["fields"]))
        if followup:
            if not state.current_metric or state.last_tool != "whcns_analyzer":
                # Recover the subject, never a numeric answer, from earlier user turns.
                for turn in reversed(body.history):
                    if turn.role != "user":
                        continue
                    fields = requested_fields(turn.content, all_fields)
                    if not fields:
                        continue
                    if len(fields) == 1:
                        candidates = [(token, report) for token, report in reports
                                      if any(column["header"].split("(")[0] == fields[0] for column in report["columns"])]
                        if len(candidates) == 1:
                            state.current_metric = fields[0]
                            state.current_attachment_id = candidates[0][0]
                            state.last_tool = "whcns_analyzer"
                    break
            if not state.current_metric or state.last_tool != "whcns_analyzer":
                return clarify("请说明要查询哪个指标的最大值或最小值；已上传的会话文件无需再次上传。" if reports else
                               "文件已失效，请重新上传，并说明要查询的指标。")
            reports = [(token, report) for token, report in reports if token == state.current_attachment_id]
            query = f"{state.current_metric} {'最小值' if re.search('最小|最低', query) else '最大值'}及对应日序"
            trace.decision.reason_code = "inherited_metric"

        # Honor explicit workbook names instead of silently switching to a different table.
        names = re.findall(r"[\w-]+\.xlsx?\b", query, re.I)
        if names:
            missing = [name for name in names if not any(report["file"].casefold() == name.casefold() for _, report in reports)]
            if missing:
                return clarify("未找到可用的文件：" + "、".join(missing) + "。请上传对应文件；已失效的文件需要重新上传。")
        if not reports:
            return clarify("文件已失效或无法读取，请重新上传需要分析的结果表。" + " ".join(dict.fromkeys(unavailable)))
        if trace.decision.reason_code in {"session_file_overview", "unclear_referent"}:
            overview = "\n".join(f"- {report['file']}（{report['sha256'][:8]}）：{report['rows']} 条记录，字段包括 "
                                 + "、".join(column["header"].split("(")[0] for column in report["columns"]) + "。"
                                 for _, report in reports)
            return clarify("可以继续查看本会话已上传的结果表，无需再次上传：\n" + overview
                           + "\n请告诉我要进一步查询的指标和统计项，例如“PREC 最大值及日序”或“硝态氮最小值”。")

        # Each clause must fit the verified extrema grammar. Do not drop time windows,
        # comparisons, or other unsupported operations while answering a recognized part.
        clauses = [part.strip() for part in re.split(r"[，,；;]|并且", query) if part.strip()]
        requests = []
        for clause in clauses:
            clause_names = re.findall(r"[\w-]+\.xlsx?\b", clause, re.I)
            for name in clause_names:
                clause = re.sub(re.escape(name), "", clause, flags=re.I)
            parsed = parse_file_request(clause, all_fields)
            if parsed is None:
                # A shared operation can apply to several named fields, e.g.
                # “硝态氮和 PREC 的最大值及日序”. Validate the entire remainder.
                fields = requested_fields(clause, all_fields)
                reduced = clause
                for field in fields:
                    reduced = re.sub(r"(?<![a-z0-9_])" + re.escape(field) + r"(?![a-z0-9_])", "", reduced, flags=re.I)
                    for alias in FIELD_ALIASES.get(field, []):
                        reduced = reduced.replace(alias, "")
                reduced = reduced.replace("分别", "")
                shared = parse_file_request(fields[0] + reduced, all_fields) if len(fields) > 1 else None
                field_pattern = "|".join(re.escape(term) for field in fields for term in [field, *FIELD_ALIASES.get(field, [])])
                interleaved = bool(field_pattern and re.search(r"(?:最大|最小|最高|最低|峰值|max|min).*?(?:" + field_pattern + r")", clause, re.I))
                if shared and not interleaved:
                    requests.extend((field, shared[1], clause_names) for field in fields)
                    continue
                return clarify("请明确字段和统计项，例如“硝态氮最大值及日序，PREC 最大值及日序”。我会从会话文件中查找对应字段；目前支持整表最大值、最小值。")
            requests.append((*parsed, clause_names))
        results = []
        used = []
        for metric, operations, clause_names in requests:
            candidates = [(token, report) for token, report in reports
                          if (not clause_names or report["file"].casefold() in {name.casefold() for name in clause_names})
                          and any(column["header"].split("(")[0] == metric for column in report["columns"])]
            if not candidates:
                return clarify(f"指定的会话文件中没有可用的 {metric} 字段，请核对文件或上传包含该字段的结果表。" + " ".join(dict.fromkeys(unavailable)))
            for token, report in candidates:
                numeric_query = metric + " " + "及".join("最大值" if op == "max" else "最小值" for op in operations)
                result = await self._call(registry, "whcns_analyzer", {"query": numeric_query, "report": report}, trace)
                results.append(result)
                used.append((token, report))
        if trace.decision.route == Route.COMPOSED:
            if len(results) != 1:
                return clarify("已找到多份匹配结果表，请在问题中明确文件名，再查询极值及可能机制。")
            state.current_attachment_id = used[0][0]
            # Existing composed workflow retains its evidence and partial-failure handling.
            result = await self._compose(body.model_copy(update={"file_id": used[0][0]}), state, trace, registry)
            result.attachments = attachment_states
            return result
        evidence = [item for result in results for item in result.file_evidence]
        answer = "\n\n".join((f"### {report['file']} · {report['sha256'][:8]}\n" if len(results) > 1 else "") + result.answer
                              for result, (_, report) in zip(results, used))
        response = reply(answer, evidence=evidence)
        response.attachments = attachment_states
        if unavailable:
            response.answer += "\n\n另有会话文件已失效或无法读取，如需分析请重新上传。"
            response.warnings = [RunWarning(code="session_file_unavailable", message=message) for message in dict.fromkeys(unavailable)]
        if len(results) == 1:
            state.current_attachment_id = used[0][0]
            state.current_metric = evidence[0].field.split("(")[0]
            state.current_operation = [item.operation for item in evidence]
            state.last_tool = "whcns_analyzer"
            response.attachment = self._ready_attachment(used[0][1])
        else:
            self.states.clear_metric(state)
        return response

    @staticmethod
    def _ready_attachment(report: dict) -> AttachmentState:
        return AttachmentState(filename=report["file"], status="ready", rows=report["rows"], kind=report["kind"])

    async def _compose(self, body: ChatRequest, state: TaskState, trace: RunTrace,
                       registry: SkillRegistry) -> ChatResponse:
        file_query = split_composed(body.query)
        if file_query is None:
            self.states.clear_metric(state)
            trace.decision.route = Route.CLARIFY
            trace.decision.reason_code = "unsupported_composed_request"
            return await self._call(registry, "clarification", {"message":
                "请先明确要计算的字段与最大/最小值，再询问可能机制。例如：硝态氮最大值是多少，为什么可能这么高？"
                "目前组合分析不支持时段筛选、多指标比较或确定性归因。"}, trace)
        if state.current_metric and state.last_tool == "whcns_analyzer" and FOLLOWUP.fullmatch(file_query):
            operation = "最小值" if "最小" in file_query or "最低" in file_query else "最大值"
            file_query = f"{state.current_metric} {operation}及对应日序"
        fields = [field for schema in SCHEMAS.values() for field in schema["fields"]]
        named_file = re.search(r"[\w-]+\.xlsx?\b", file_query, re.I)
        parsed = parse_file_request(file_query, fields, named_file.group() if named_file else "")
        if parsed is None:
            self.states.clear_metric(state)
            trace.decision.route = Route.CLARIFY
            trace.decision.reason_code = "unsupported_or_ambiguous_file_query"
            return await self._call(registry, "clarification", {"message":
                "请明确一个字段的整表最大值或最小值。时段、浓度换算、多指标比较等要求尚不支持，不能用整表极值代替。"}, trace)
        numeric, knowledge = None, None
        attachment = None
        warnings = []
        try:
            inspected = await self._call(registry, "file_inspector", {"file_id": body.file_id}, trace)
            attachment = self._ready_attachment(inspected.report)
            if named_file_mismatch(body.query, inspected.report["file"]):
                self.states.clear_metric(state)
                trace.decision.route = Route.CLARIFY
                trace.decision.reason_code = "attachment_name_mismatch"
                result = reply("问题中的文件名与当前选中的文件不一致，或提到了多份文件。请先选择一份对应文件，再查询它的字段与极值。")
                result.attachment = attachment
                return result
            numeric = await self._call(registry, "whcns_analyzer", {"query": file_query, "report": inspected.report}, trace)
            if not numeric.file_evidence:
                self.states.clear_metric(state)
                trace.decision.route = Route.CLARIFY
                trace.decision.reason_code = "unsupported_or_ambiguous_file_query"
                numeric.attachment = attachment
                return numeric
        except HTTPException as exc:
            code = error_code(exc)
            if code not in {"invalid_result_file", "file_not_found", "file_tools_unavailable", "file_analysis_failed"}:
                raise
            self.states.clear_metric(state)
            message = exc.detail["message"]
            warnings.append(RunWarning(code=code, message=message))
            if code == "invalid_result_file":
                attachment = AttachmentState.model_validate(exc.detail["attachment"])
            elif code == "file_not_found":
                attachment = AttachmentState(filename="当前附件", status="expired")

        metric = parsed[0]
        peak_question = "max" in parsed[1]
        if metric in METRIC_TERMS:
            query = (f"{state.crop or '农田'} {METRIC_TERMS[metric]} 单次峰值 灌水或较强降雨后 水分渗漏 "
                     "硝酸盐淋洗动态 作物生育期 事件尺度机制" if peak_question else
                     f"{state.crop or '农田'} {METRIC_TERMS[metric]} 可能受哪些因素影响？仅解释文献中的一般机制和适用条件。")
            try:
                knowledge = await self._call(registry, "knowledge_search",
                                             {"query": query, "k": body.k, "mode": "mechanisms", "crop": state.crop,
                                              "purpose": "peak" if peak_question else "general"}, trace)
            except Exception as exc:
                # A generation/retrieval failure cannot invalidate verified arithmetic.
                knowledge = None
                logger.warning("Composed knowledge step failed | code={}", error_code(exc))
                warnings.append(RunWarning(code=error_code(exc), message="未获得可核查的文献机制说明，暂不推断原因。"))
        else:
            warnings.append(RunWarning(code="mechanism_metric_unsupported", message="请明确硝态氮、铵态氮或排水指标后再查询相关文献机制。"))

        if numeric:
            state.current_metric = metric
            state.current_operation = [item.operation for item in numeric.file_evidence]
            state.last_tool = "whcns_analyzer"
        else:
            self.states.clear_metric(state)
        diagnosis = (f"仅凭表中模型日序 {numeric.file_evidence[0].model_day} 的极值，无法确认峰值成因。"
                     if numeric and peak_question else "仅凭这一项表中数值，无法确认其成因。")
        diagnosis += "目前没有经核验与该输出配对的同期天气、灌溉、排水、施肥和土壤硝态氮记录。"
        limitation = ("先核实 manage_in 与输出表是否配对及模型日序定义；确认后再换算日历日期。"
                      "随后核对目标日及前后数日的 PREC、IRRI、Draining、施肥、土壤硝态氮剖面和模型配置。"
                      "文献只提供其他研究场景的待核查机制，不能证明本表峰值原因；当前没有执行 WHCNS，也不据此给出施肥量。")
        file_text = numeric.answer if numeric else "未取得有效文件计算结果。" + " ".join(w.message for w in warnings if w.code.startswith("file") or w.code == "invalid_result_file")
        mechanism_text = knowledge.answer if knowledge else "未获得可核查的文献机制说明，暂不推断原因。"
        sections = [AnswerSection(kind="file_observation", content=file_text,
                                  file_evidence_indices=list(range(1, len(numeric.file_evidence) + 1)) if numeric else []),
                    AnswerSection(kind="limitation", content=diagnosis)]
        if knowledge:
            sections.extend(knowledge.sections)
        else:
            sections.append(AnswerSection(kind="limitation", content=mechanism_text))
        sections.append(AnswerSection(kind="limitation", content=limitation))
        result = reply(f"表中观察\n{file_text}\n\n为何目前不能归因\n{diagnosis}\n\n文献中的事件尺度线索\n{mechanism_text}\n\n下一步核查\n{limitation}",
                       evidence=numeric.file_evidence if numeric else [])
        result.route = "composed"
        result.outcome = "partial" if warnings and (numeric or knowledge) else "clarification" if warnings else "complete"
        result.attachment, result.sections, result.warnings = attachment, sections, warnings
        if knowledge:
            result.citations, result.usage = knowledge.citations, knowledge.usage
            result.retrieved_count, result.model = knowledge.retrieved_count, knowledge.model
        return result
