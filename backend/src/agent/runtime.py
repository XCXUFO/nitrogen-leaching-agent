"""One bounded execution entry: context, policy, skills, state, evidence, trace."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from loguru import logger
from openai import APIConnectionError, APIError, APITimeoutError, AuthenticationError, RateLimitError

from src.agent.case_intent import CASE_SKILLS, case_mode, normalize_case_call
from src.agent.case_ids import MAX_CASE_IDS, case_ids_in
from src.agent.explanation_method import active_communication
from src.agent.answer_language import active_answer_language, detect_answer_language, enforce_response_language
from src.agent.web_evidence import active_web_observer, WEB_REQUEST
from src.agent.task_prompts import active_task_prompts, active_task_usage
from src.agent.concept_intent import concept_intent
from src.agent.domain_scope import DOMAIN_GUIDANCE_ANSWER, outside_domain
from src.agent.chat_service import ChatService, RAGQueryError, normalize_citations
from src.agent.contracts import AnswerSection, AttachmentState, Evidence, Route, RouteDecision, RunTrace, RunWarning, SkillName, StateSnapshot, TaskState, ToolCall
from src.agent.composition import METRIC_TERMS, MechanismEvidenceError, split_composed
from src.agent.file_chat import FIELD_ALIASES, parse_file_request, reply, requested_fields
from src.agent.query_intent import has_statistic_request
from src.agent.provided_text import has_provided_text
from src.model_tools.whcns_results import SCHEMAS
from src.agent.prompt import DialogueTurn
from src.agent.routing import FOLLOWUP, GREETING, crop_scope, decide, guidance_query, introductory_query
from src.agent.planning import plan
from src.agent.skills import KnowledgeUnavailable, SkillRegistry, build_registry
from src.agent.state import ConversationBusy, StateCapacityError, StateStore
from src.agent.skill_config import ExpressionPreferences
from src.agent.understanding import VERSION as UNDERSTANDING_VERSION, understand, map_tags, SWITCH, canonical, is_followup, explicit_tag_spans, remaining_context
from src.agent.starred_match import match_starred, applicability
from src.api.chat_schema import ChatRequest, ChatResponse
from src.storage.run_store import RunStore
from src.retrieval.web import WebResult


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
            evidence_id=f"{run_id}:{'web' if item.source_type == 'web' else 'literature'}:{item.index}", source_type="web" if item.source_type == "web" else "literature", source_id=item.chunk_id,
            claim_or_value=item.snippet,
            retrieval_ids=item.retrieval_ids, chunk_ids=item.chunk_ids,
            location={"citation_index": item.index, "chunk_id": item.chunk_id,
                      **({"char_start": item.char_start, "char_end": item.char_end} if item.char_start is not None and item.char_end is not None else {})},
            provenance={"source": item.source, "title": item.title or "", "review_identity":
                        "AI-assisted source checking" if response.model == "curated-excerpts-v1" else "unreviewed retrieval",
                        **({"publisher": item.publisher or "", "retrieved_at": item.retrieved_at or "", "fetch_status": item.fetch_status or "", "evidence_level": item.evidence_level or ""} if item.source_type == "web" else {}),
                        **({"content_version": item.content_version} if item.content_version else {}),
                        **({"paper_id": item.document_id} if item.document_id else {}),
                        **({"file_sha256": item.file_sha256} if item.file_sha256 else {})},
            status="curated" if response.model == "curated-excerpts-v1" else "retrieved",
        ))
    for item in response.case_references:
        evidence.append(Evidence(evidence_id=f"{run_id}:case:{item.id}", source_type="case",
                                 retrieval_ids=item.retrieval_ids, chunk_ids=[item.id],
                                 source_id=item.id, claim_or_value=item.title, status="retrieved",
                                 provenance={"source": item.source, "title": item.title}))
    return evidence


class AgentRuntime:
    def __init__(self, *, runs: RunStore | None = None, states: StateStore | None = None,
                 config_version: str = "unconfigured", config_manifest: dict | None = None, web=None, unified_routing=True,
                 semantic_query=None):
        self.runs = runs if runs is not None else RunStore()
        self.states = states if states is not None else StateStore()
        self.config_version = config_version
        self.config_manifest = config_manifest or {}
        self.web = web
        self.unified_routing = unified_routing
        self.semantic_query = semantic_query
        self._observers: dict = {}
        self._plans: set[str] = set()
        self._active_subtasks: dict[str, list[str]] = {}

    def expression_snapshot(self):
        # A restore moves preferences and all prompt pointers together. Readers
        # must hold the same lock across both reads to capture an actual version.
        with self.runs._lock:
            try:
                snapshot = self.runs.skill_config.current()
            except Exception:
                logger.exception("Expression configuration unavailable; using builtin defaults")
                snapshot = {"revision": 0, "version": "case-expression-v1:0", "values": ExpressionPreferences().model_dump(),
                        "fallback": True, "fallback_reason": "configuration_unavailable"}
            return {**snapshot, **self.runs.active_prompt_snapshot()}

    def _emit(self, trace, event):
        event = {"time": datetime.now(timezone.utc).isoformat(), **event}
        if event.get("type") in {"step_started", "step_finished"}:
            event = {"subtask_ids": self._active_subtasks.get(trace.run_id, [item["subtask_id"] for item in trace.understanding.get("subtasks", [])]), **event}
        observer = self._observers.get(trace.run_id)
        if observer:
            observer({"event_id": str(uuid4()), "time": datetime.now(timezone.utc).isoformat(), **event})
        if event.get("type") in {"step_started", "step_finished"}:
            trace.execution_steps.append(dict(event))

    def _service(self, trace, name, label, operation):
        step_id = str(uuid4())
        self._emit(trace, {"type": "step_started", "kind": "service", "step_id": step_id, "attempt_no": 1,
                           "name": label, "service": name, "status": "running"})
        try:
            value = operation()
        except Exception:
            self._emit(trace, {"type": "step_finished", "kind": "service", "step_id": step_id, "attempt_no": 1,
                               "name": label, "service": name, "status": "failed", "error_code": name + "_failed"})
            raise
        outcome = {"partial": "partial_coverage", "full": "full_coverage", "no_match": "no_result", "empty_answer": "empty_answer", "unavailable": "unavailable"}.get(value.get("status"), "has_result")
        self._emit(trace, {"type": "step_finished", "kind": "service", "step_id": step_id, "attempt_no": 1,
                           "name": label, "service": name, "status": "succeeded", "outcome": outcome})
        return value

    async def _call(self, registry: SkillRegistry, name: SkillName, payload: dict, trace: RunTrace):
        name, payload = normalize_case_call(name, payload)
        if name == "case_assistant":
            trace.decision.skills = ["case_assistant"]
        started = time.perf_counter()
        step_id = str(uuid4())
        if trace.run_id in self._observers and trace.run_id not in self._plans:
            self._emit(trace, {"type": "plan_created", "status": "planned", "skills": trace.decision.skills, "summary": "已确定本轮处理计划。"})
            self._plans.add(trace.run_id)
        try:
            self._emit(trace, {"type": "step_started", "kind": "skill", "step_id": step_id, "attempt_no": 1,
                               "skill": name, "name": registry.label(name), "status": "running", "summary": "正在使用相关能力。"})
        except Exception:
            # Admission succeeded but this action's start could not be recorded.
            # Explain the blocked step without inventing a completed tool call.
            self._emit(trace, {"type": "step_finished", "kind": "skill", "step_id": step_id, "attempt_no": 1,
                               "skill": name, "name": registry.label(name), "status": "failed", "outcome": "not_executed",
                               "error_code": "progress_unavailable", "summary": "执行前未能记录状态，本步骤未调用。"})
            raise
        status, failure = "ok", None
        outcome = "has_result"
        try:
            result = await registry.invoke(name, payload)
            if isinstance(result, ChatResponse) and result.route == "clarification":
                status = "clarification"
                outcome = "clarification"
            elif isinstance(result, ChatResponse) and (result.case_match == "missing" or (name == "knowledge_search" and result.retrieved_count == 0)):
                outcome = "no_result"
            return result
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
            failure = error_code(exc)
            outcome = "unfulfilled"
            raise
        finally:
            trace.tool_calls.append(ToolCall(skill=name, status=status, error_code=failure,
                                             latency_ms=int((time.perf_counter() - started) * 1000), step_id=step_id,
                                             case_mode=payload.get("mode") if name == "case_assistant" else None))
            try:
                self._emit(trace, {"type": "step_finished", "kind": "skill", "step_id": step_id, "attempt_no": 1,
                                   "skill": name, "name": registry.label(name),
                                   "status": {"ok": "succeeded", "clarification": "succeeded", "error": "failed", "cancelled": "cancelled"}[status],
                                   "outcome": outcome, "error_code": failure, "summary": "本步骤已结束。"})
            except Exception:
                logger.exception("Step event delayed; preserving computed output | run_id={}", trace.run_id)

    async def _tool_operation(self, trace, name, operation, *, retrieval=False, kind="tool", step_id=None, attempt_no=1):
        step_id = step_id or str(uuid4())
        parent = next((event["step_id"] for event in reversed(trace.execution_steps) if event.get("kind") == "skill" and event["type"] == "step_started"), None)
        base = {"kind": kind, "step_id": step_id, "parent_step_id": parent, "attempt_no": attempt_no,
                "name": name, "operation": "retrieval" if retrieval else "calculation"}
        self._emit(trace, {**base, "type": "step_started", "status": "running"})
        try:
            value = operation()
            result = await value if inspect.isawaitable(value) else value
        except BaseException as exc:
            self._emit(trace, {**base, "type": "step_finished", "status": "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed", "error_code": error_code(exc)})
            raise
        empty = ((isinstance(result, list) and not result) or (retrieval and isinstance(result, tuple) and isinstance(result[0], list) and not result[0])
                 or (retrieval and isinstance(result, WebResult) and not any(source.get("status") == "fetched" for source in result.sources)))
        self._emit(trace, {**base, "type": "step_finished", "status": "succeeded", "outcome": "no_result" if empty else "clarification" if isinstance(result, ChatResponse) and result.outcome == "clarification" else "has_result"})
        return result

    async def execute(self, body: ChatRequest, *, service: ChatService | None,
                      get_report: Callable[[str], Awaitable[dict]],
                      get_documents: Callable[[list[str]], list[dict]] | None = None,
                      case_store=None, llm=None, run_id: str | None = None, observer=None, run_context: dict | None = None,
                      expression_config: dict | None = None, taxonomy_provider=None, starred_provider=None,
                      attachment_metadata: list[dict] | None = None) -> ChatResponse:
        started = time.perf_counter()
        conversation_id = body.session_id or str(uuid4())
        run_id = run_id or str(uuid4())
        expression_config = expression_config or self.expression_snapshot()
        communication = expression_config.get("communication") or self.runs.prompts.active()
        tasks = expression_config.get("task_prompts") or self.runs.task_prompts.active()
        task_usage = []
        trace = RunTrace(run_id=run_id, conversation_ref=digest(conversation_id), input=body.query,
                         history_count=len(body.history),
                         started_at=datetime.now(timezone.utc).isoformat(), state_before=StateSnapshot(),
                         config_version=self.config_version, config_manifest=self.config_manifest,
                         skill_config={"case_explanation": expression_config,
                                       "communication": communication, "task_prompts": tasks, "task_prompt_usage": task_usage},
                         request_snapshot={**body.model_dump(exclude={"file_id", "file_ids", "operator_id", "session_id"}),
                                           "has_attachments": bool(body.file_id or body.file_ids),
                                           "file_mode": "multiple" if body.file_ids is not None else "single" if body.file_id else "inherit",
                                           "attachments": attachment_metadata or []},
                         **(run_context or {}))
        if trace.mode is None:
            trace.mode='specified' if body.case_skill or body.case_mode or body.case_ids else 'auto'
        if observer:
            self._observers[run_id] = observer
        response = None
        execution_error = None
        language_decision = detect_answer_language(body.query)
        trace.skill_config["answer_language"] = {"language": language_decision.language,
            "reason": language_decision.reason, "policy": language_decision.policy}
        language_token = active_answer_language.set(language_decision)
        communication_token = active_communication.set(communication)
        task_token = active_task_prompts.set(tasks)
        usage_token = active_task_usage.set(task_usage)
        web_token = active_web_observer.set(lambda record: trace.web_retrieval.append(record))
        try:
            with self.states.lease(conversation_id, body.file_id, session_files=body.file_ids is not None) as state:
                if body.file_ids is not None:
                    state.session_files_enabled = True
                    # The client sends all session capabilities, including collapsed files.
                    # This also allows replacing expired uploads without keeping dead tokens.
                    state.session_file_ids = list(dict.fromkeys(body.file_ids))
                trace.state_before = snapshot(state)
                try:
                    attachment_ids = state.session_file_ids if state.session_files_enabled else ([body.file_id] if body.file_id else [])
                    documents = get_documents(attachment_ids) if get_documents else []
                    response = await self._orchestrate(body, state, trace, service=service, get_report=get_report,
                                                       case_store=case_store, llm=llm, documents=documents,
                                                       expression_config=expression_config, taxonomy_provider=taxonomy_provider, starred_provider=starred_provider)
                except BaseException:
                    # A failed calculation may not leave an earlier metric ready for inference.
                    if trace.decision and trace.decision.route in {Route.FILE_ANALYSIS, Route.COMPOSED}:
                        self.states.clear_metric(state)
                    raise
                finally:
                    trace.state_after = snapshot(state)
            language_audit = await enforce_response_language(response, language_decision,
                llm=llm or getattr(service, "_llm", None),
                operation=lambda operation: self._tool_operation(trace, "统一回答语言并保留原始事实", operation, kind="service"))
            if "trial_prompt" in expression_config:
                citation_mapping = {}
            else:
                response.answer, response.citations, citation_mapping = normalize_citations(response.answer, response.citations)
            semantic_usage=trace.understanding.get('semantic',{}).get('usage',{})
            if semantic_usage:
                response.usage=response.usage.model_copy(update={key:getattr(response.usage,key)+semantic_usage.get(key,0)
                    for key in ('prompt_tokens','completion_tokens','total_tokens')})
            for section in response.sections:
                section.content = re.sub(r"\[(\d+)\](?!\()", lambda match: f"[{citation_mapping[int(match[1])]}]" if int(match[1]) in citation_mapping else "", section.content)
                section.citation_indices = [citation_mapping[index] for index in section.citation_indices if index in citation_mapping]
            response.run_id = run_id
            response.conversation_id = conversation_id
            response.agent_route = trace.decision.route
            response.evidence = collect_evidence(response, run_id)
            for item in trace.starred_match.get("adopted", []):
                existing=next((e for e in response.evidence if e.source_type=='starred' and e.source_id==item['question_id']),None)
                if existing:
                    existing.subtask_ids=list(dict.fromkeys([*existing.subtask_ids,item['subtask_id']]))
                    scopes=json.loads(existing.provenance.get('coverage_scope','[]'))
                    existing.provenance['coverage_scope']=json.dumps(list(dict.fromkeys([*scopes,*item.get('covered_aspects',[])])),ensure_ascii=False)
                    continue
                response.evidence.append(Evidence(evidence_id=f"{run_id}:starred:{item['question_id']}", source_type="starred",
                    source_id=item["question_id"], claim_or_value=item["answer"], status="maintained", subtask_ids=[item["subtask_id"]],
                    provenance={"fingerprint": item["fingerprint"], "source": "已有专业问答",
                                'revision':str(item.get('revision') or 'unknown'),
                                'source_refs':json.dumps(item.get('source_refs',[]),ensure_ascii=False),
                                'coverage_scope':json.dumps(item.get('covered_aspects',[]),ensure_ascii=False),
                                'professional_review':item.get('professional_review','unknown')}))
            for item in response.evidence:
                if not item.subtask_ids: item.subtask_ids = self._active_subtasks.get(run_id, [task["subtask_id"] for task in trace.understanding.get("subtasks", [])])
                if item.source_type == "case":
                    record = next((candidate for selection in trace.retrieval for candidate in selection.get("candidates", []) if candidate.get("id") == item.source_id and candidate.get("selected")), None)
                    if record: item.provenance.update({"fingerprint": record["fingerprint"], "revision": str(record["revision"]), "location": record["location"]})
            for section in response.sections:
                section.evidence_ids = [item.evidence_id for item in response.evidence
                                        if (item.source_type in {"literature", "web"} and item.location.get("citation_index") in section.citation_indices)
                                        or (item.source_type == "file" and int(item.evidence_id.rsplit(":", 1)[1]) in section.file_evidence_indices)]
            trace.evidence = response.evidence
            trace.sections, trace.warnings, trace.outcome = response.sections, response.warnings, response.outcome
            section_kinds = list(dict.fromkeys(section.kind for section in response.sections))
            adopted = trace.starred_match.get('adopted', [])
            continued = bool(trace.starred_match.get('continuation'))
            trace.answer_assembly = {
                'mode': 'starred_plus_continuation' if adopted and continued else 'starred_only' if adopted else
                        'file_plus_literature' if {'file_observation', 'literature_inference'} <= set(section_kinds) else 'single',
                'section_kinds': section_kinds, 'source_types': list(dict.fromkeys(item.source_type for item in response.evidence)),
                'skills': [call.skill for call in trace.tool_calls], 'outcome': response.outcome,
                'language': language_audit,
            }
            trace.answer, trace.model, trace.status = response.answer, response.model, "ok"
            return response
        except BaseException as exc:
            execution_error = exc
            language_audit = getattr(exc, "answer_language_audit", None)
            if language_audit is not None:
                trace.answer_assembly["language"] = language_audit
            trace.status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
            trace.error_code = error_code(exc)
            # The HTTP adapter can attach the same run ID to error responses.
            setattr(exc, "agent_run_id", run_id)
            raise
        finally:
            if trace.execution_plan:
                trace.execution_plan['actual_selected_skills'] = list(trace.decision.skills) if trace.decision else []
                trace.execution_plan['actual_calls'] = [call.model_dump(mode='json') for call in trace.tool_calls]
                trace.execution_plan['outcome'] = trace.outcome or trace.status
            active_communication.reset(communication_token)
            active_answer_language.reset(language_token)
            active_task_prompts.reset(task_token)
            active_task_usage.reset(usage_token)
            active_web_observer.reset(web_token)
            self._observers.pop(run_id, None)
            self._plans.discard(run_id)
            self._active_subtasks.pop(run_id, None)
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

    async def _orchestrate(self, body, state, trace, *, service, get_report, case_store, llm, documents,
                           expression_config, taxonomy_provider, starred_provider):
        async def policy_reply(*, outside):
            reason = "outside_supported_domain" if outside else "capability_request"
            trace.decision = RouteDecision(route=Route.OUT_OF_SCOPE if outside else Route.DIRECT,
                reason_code=reason, skills=["capability_guidance"])
            trace.execution_context = trace.understanding
            trace.starred_match = {"status": "not_applicable", "reason": reason, "adopted": []}
            trace.tag_mapping = {"status": "skipped", "reason": reason, "mappings": []}
            trace.execution_plan = plan(trace.understanding, trace.decision, service=service, llm=llm,
                cases=case_store, has_file=False, specified=False)
            state.last_tool = "capability_guidance"
            state.understanding_context = trace.understanding
            state.material_anchors = []
            registry = build_registry(service, get_report, llm=llm, case_store=case_store, web=self.web)
            query = body.query.strip()
            return await self._call(registry, "capability_guidance", {"outside_domain": outside,
                "introductory": introductory_query(query),
                "greeting": query.rstrip("!！。?？") if GREETING.fullmatch(query) else ""}, trace)

        guidance = guidance_query(body.query)
        if guidance or outside_domain(body.query):
            intent = "capability" if guidance else "knowledge"
            trace.understanding = {"status": "collected", "version": UNDERSTANDING_VERSION,
                "raw_query": body.query, "resolved_query": body.query,
                "subtasks": [{"subtask_id": f"{trace.run_id}:task:1", "query": body.query,
                    "intent": intent, "domain_scope": "supported" if guidance else "outside", "depends_on": []}],
                "semantic": {"status": "skipped", "reason": "capability_request" if guidance else "outside_supported_domain"},
                "conditions": [], "concepts": [], "intents": [intent], "unresolved": []}
            return await policy_reply(outside=not guidance)
        taxonomy = None
        try:
            taxonomy = taxonomy_provider() if taxonomy_provider and not guidance_query(body.query) else None
        except Exception:
            logger.warning("Taxonomy unavailable; preserving text query | run_id={}", trace.run_id)
        try:
            trace.understanding = self._service(trace, "understanding", "理解本轮问题与相关上下文", lambda: understand(body, state, trace, taxonomy))
        except Exception:
            # Do not guess context after failed interpretation.
            trace.understanding = {"status": "degraded", "version": UNDERSTANDING_VERSION, "raw_query": body.query,
                "resolved_query": body.query, "queries": [body.query], "conditions": [], "concepts": [], "anchors": [], "unresolved": [],
                "subtasks": [{"subtask_id": f"{trace.run_id}:task:1", "query": body.query, "intent": "knowledge", "depends_on": []}]}
        specified=bool(body.case_skill or body.case_mode or body.case_ids or "trial_prompt" in expression_config)
        questions=None
        try:
            needed=self.semantic_query is not None and not specified or any(not applicability(task,specified=specified) for task in trace.understanding['subtasks'])
            questions=starred_provider() if needed and starred_provider else None
        except Exception:
            logger.warning("Starred library unavailable | run_id={}",trace.run_id)
        semantic=None
        if self.semantic_query is not None:
            step_id=str(uuid4())
            self._emit(trace,{'type':'step_started','kind':'service','step_id':step_id,'attempt_no':1,
                'name':'理解用户意图、改写检索问题并核对星标语义覆盖','service':'semantic_query','status':'running'})
            try:
                semantic=await self.semantic_query.interpret(trace.understanding,questions,body.history,specified=specified,
                    has_file=bool(state.session_file_ids if state.session_files_enabled else body.file_id))
                trace.understanding['subtasks']=semantic['subtasks']
                trace.understanding['intents']=list(dict.fromkeys(task['intent'] for task in semantic['subtasks']))
                trace.understanding['semantic']=semantic
                trace.understanding['resolved_query']='；'.join(task.get('semantic_query') or task['query'] for task in semantic['subtasks'])
                trace.understanding['basis']='模型结合上下文理解需求并改写；明确条件保留检查与星标答案覆盖核对。'
                for rewrite in semantic['rewrites']:
                    if rewrite['clarification']:
                        message = rewrite['clarification'] if rewrite.get('domain_scope') == 'supported' else DOMAIN_GUIDANCE_ANSWER
                        trace.understanding.setdefault('unresolved',[]).append({'field':'semantic_reference',
                            'requires_clarification':True,'message':message})
                self._emit(trace,{'type':'step_finished','kind':'service','step_id':step_id,'attempt_no':1,
                    'name':'理解用户意图、改写检索问题并核对星标语义覆盖','service':'semantic_query','status':'succeeded','outcome':'has_result'})
            except Exception as exc:
                trace.understanding['semantic']={'status':'degraded','version':'semantic-query-v1',
                    'reason':'semantic_timeout' if isinstance(exc,TimeoutError) else 'semantic_interpretation_failed',
                    'fallback':'original_query_and_explicit_rules'}
                self._emit(trace,{'type':'step_finished','kind':'service','step_id':step_id,'attempt_no':1,
                    'name':'理解用户意图、改写检索问题并核对星标语义覆盖','service':'semantic_query','status':'failed',
                    'error_code':trace.understanding['semantic']['reason']})
                logger.warning("Semantic interpretation unavailable; using explicit rules | run_id={} | error={}",trace.run_id,type(exc).__name__)
        else:
            trace.understanding['semantic']={'status':'unavailable','reason':'semantic_model_unavailable',
                'fallback':'original_query_and_explicit_rules'}
        if outside_domain(body.query, trace.understanding):
            return await policy_reply(outside=True)
        try:
            def match():
                return match_starred(trace.understanding,questions,specified=specified,semantic=semantic)
            trace.starred_match=self._service(trace,"starred_match","核对已有问答的适用范围与未覆盖需求",match)
        except Exception:
            trace.starred_match={'status':'failed','error_code':'starred_match_failed','adopted':[],
                'remaining_tasks':trace.understanding['subtasks'],
                'remaining_subtask_ids':[task['subtask_id'] for task in trace.understanding['subtasks']]}
        adopted=trace.starred_match.get('adopted',[])
        tasks=trace.starred_match.get('remaining_tasks',trace.understanding['subtasks'])
        if semantic is not None:
            tasks=[{**task,'original_query':task['query'],'query':task.get('semantic_query') or task['query']} for task in tasks]
        scoped=remaining_context(trace.understanding,tasks)
        # Retrieval fallback is an internal policy, never a user-facing switch.
        scoped['allow_local_scope_expansion']=True
        trace.execution_context=scoped
        self._active_subtasks[trace.run_id]=[task['subtask_id'] for task in tasks]
        if SWITCH.search(body.query):
            state.crop = None
            state.current_case_ids = []
            state.user_selected_case_ids = []
            state.retrieved_case_ids = []
            state.case_context_text = ""
            state.case_material_source = None
            state.case_mode = None
            state.case_clarification_pending = False

        def reused_text():
            unique={}
            for item in adopted: unique.setdefault((item['question_id'],item['fingerprint']),item)
            return "参考已有专业问答：\n\n"+"\n\n".join(item['answer']+("\n\n资料来源："+"；".join(item['source_refs']) if item.get('source_refs') else '') for item in unique.values())

        if adopted and not tasks:
            trace.tag_mapping={'status':'skipped','reason':'starred_full_coverage','mappings':[]}
            trace.decision=decide(body.query,has_file=False,understanding=trace.understanding)
            trace.decision.skills,trace.decision.reason_code=[],"starred_full_coverage"
            trace.execution_plan=plan(scoped,trace.decision,service=service,llm=llm,cases=case_store,has_file=False,specified=specified)
            trace.execution_plan['covered_by_starred']=trace.starred_match.get('covered_aspects',[])
            response=reply(reused_text())
            response.route,response.outcome,response.model="knowledge","complete","maintained-qa-v2"
            state.last_tool=None
        else:
            try:
                if all(task.get('intent')=='capability' or guidance_query(task['query']) for task in tasks):
                    trace.tag_mapping={'status':'skipped','reason':'capability_request','mappings':[]}
                else:
                    trace.tag_mapping=self._service(trace,"tag_mapping","核对剩余需求的概念与共享标签",lambda:map_tags(scoped,taxonomy))
            except Exception:
                trace.tag_mapping={'status':'degraded','fallback_reason':'tag_mapping_failed','mappings':[],'unmatched':scoped.get('concepts',[])}
            if explicit_tag_spans(body.query):
                ambiguous=any(item.get('requires_resolution') for item in trace.tag_mapping.get('mappings',[]))
                if ambiguous or trace.tag_mapping.get('unresolved_filters') or not trace.tag_mapping.get('mappings'):
                    scoped.setdefault('unresolved',[]).append({'field':'explicit_tag_filter','requires_clarification':True,
                        'message':'请指定有效标签的完整路径；当前标签存在歧义、未确认别名或标签服务不可用，未扩大筛选范围。'})
            def record_retrieval(selection):
                parent = next((event for event in reversed(trace.execution_steps) if event.get('kind') == 'skill' and event['type'] == 'step_started'), {})
                trace.retrieval.append({"source_type":"case","subtask_ids":self._active_subtasks.get(trace.run_id,[]),
                    'skill':parent.get('skill'), 'skill_step_id':parent.get('step_id'), **selection})
            async def tool_runner(name,operation,**options):
                return await self._tool_operation(trace,name,operation,**options)
            registry=build_registry(service,get_report,case_store=case_store,llm=llm,expression_config=expression_config,web=self.web,
                understanding=scoped,tag_mapping=trace.tag_mapping,retrieval_observer=record_retrieval,tool_runner=tool_runner)
            continuation=body.model_copy(update={'query':scoped['resolved_query']}) if adopted else body
            trace.decision=decide(continuation.query,has_file=bool(state.session_file_ids) if state.session_files_enabled else bool(body.file_id),
                understanding=scoped if self.unified_routing else None)
            trace.execution_plan=plan(scoped,trace.decision,service=service,llm=llm,cases=case_store,
                has_file=bool(state.session_file_ids or body.file_id),specified=specified)
            trace.execution_plan['covered_by_starred']=trace.starred_match.get('covered_aspects',[])
            try:
                clarification=next((item['message'] for item in scoped.get('unresolved',[]) if item['requires_clarification']),None)
                if "trial_prompt" in expression_config:
                    trace.decision.route,trace.decision.skills,trace.decision.reason_code=Route.KNOWLEDGE,['case_assistant'],'prompt_comparison'
                    response=await self._call(registry,'case_assistant',{'query':body.query,'mode':'explain'},trace)
                elif clarification:
                    trace.decision.route,trace.decision.skills,trace.decision.reason_code=Route.CLARIFY,['clarification'],'uncertain_context'
                    response=await self._call(registry,'clarification',{'message':clarification},trace)
                else:
                    response=await self._execute(continuation,state,trace,registry,documents)
            except Exception as exc:
                if not adopted: raise
                response=reply("未覆盖部分本次未能完成，请补充条件或稍后重新执行。")
                response.outcome='partial'
                response.warnings=[RunWarning(code=error_code(exc),message="后续处理未完成，已有问答的可用内容已保留。")]
            trace.starred_match['continuation']={'outcome':response.outcome,'actual_skills':[call.skill for call in trace.tool_calls],
                'subtask_ids':[task['subtask_id'] for task in tasks]}
            if adopted:
                response.answer=reused_text()+"\n\n其余问题：\n\n"+response.answer
                if response.outcome=='clarification': response.outcome='partial'
        state.understanding_context = {**trace.understanding, "literature_scope": response.literature_scope}
        previous_case_anchors = [a for a in state.material_anchors if a.get("source_type") == "case" and a.get("source_id") in state.current_case_ids]
        state.material_anchors = [{"source_turn_id": trace.turn_id, "source_run_id": trace.run_id, "source_type": "case", "source_id": item.id,
                                   "title": item.title, "version": next((record.get("fingerprint") for selection in trace.retrieval for record in selection.get("candidates", []) if record.get("id") == item.id), None)} for item in response.case_references]
        if not response.case_references and state.last_tool == "case_assistant":
            state.material_anchors += previous_case_anchors
        state.material_anchors += [{"source_turn_id": trace.turn_id, "source_run_id": trace.run_id, "source_type": "literature", "source_id": item.chunk_id,
                                    "version": hashlib.sha256(item.snippet.encode()).hexdigest()} for item in response.citations]
        state.material_anchors += [{"source_turn_id": trace.turn_id, "source_run_id": trace.run_id, "source_type": "file", "source_id": item.sha256,
                                   "version": item.sha256, "filename": item.filename, "field": item.field, "cell": item.cell} for item in response.file_evidence]
        return response

    async def _execute(self, body: ChatRequest, state: TaskState, trace: RunTrace,
                       registry: SkillRegistry, documents: list[dict]) -> ChatResponse:
        context=trace.execution_context or trace.understanding
        crop_changed, crop = crop_scope(canonical(body.query))
        current_crops = [item["value"] for item in context.get("conditions", []) if item.get("category") == "crop" and item.get("source") == "current_user" and not item.get("negated")]
        if len(set(current_crops)) == 1:
            crop_changed, crop = True, current_crops[0]
        if crop_changed:
            state.crop = crop
        session_files = state.session_files_enabled
        routing_context = context if body.query == trace.input else {**context, 'resolved_query':body.query}
        trace.decision = decide(body.query, has_file=bool(state.session_file_ids) if session_files else body.file_id is not None,
                                understanding=routing_context if self.unified_routing else None)
        explicit_ids = body.case_ids or case_ids_in(body.query)
        new_text = has_provided_text(body.query) or bool(re.search(r"[:：\n]", body.query))
        if (documents and not (body.case_skill or body.case_mode) and not explicit_ids
                and trace.decision.skills == ["case_assistant"]
                and not re.search(r"案例|[:：\n]", body.query)):
            trace.decision.skills = ["knowledge_search"]
            trace.decision.reason_code = "session_document_question"
        previous_case_skill = state.last_tool in CASE_SKILLS
        referent = bool(re.search(r"刚才|上述|上面|上文|前文|你(?:说|提到|展示)的|前面|其中|该案例|案例中|这些|这两|两者|前者|后者|第[一二三四五]|对比|比较|区别|再解释|详细解释|(?<!其)它|这个|那个", body.query))
        new_search = bool(re.search(r"(?:有没有|有哪些|寻找|查找|找|推荐|介绍).{0,12}案例|(?:其他|别的|更多).{0,8}案例", body.query))
        case_followup = (previous_case_skill and not explicit_ids and not documents and not new_text
                         and trace.decision.route == Route.KNOWLEDGE and not new_search
                         and (referent or state.case_clarification_pending or bool(re.fullmatch(r"为什么(?:要)?这样.{0,12}[？?。]*|效果(?:如何|怎么样|呢)[？?。]*|还有什么证据[？?。]*", body.query)))
                         and not re.search(r"文献|论文|手册|换个话题|另一个问题", body.query))
        # User source material is verified state, not a previous model answer.
        # Corrections can contain colons and can resume after an unrelated turn.
        record_instruction = re.split(r"[:：\n]", body.query, maxsplit=1)[0]
        record_followup = (state.case_material_source == "user_text" and bool(state.case_context_text)
            and not explicit_ids and not documents and not new_search and not SWITCH.search(body.query)
            and not re.search(r"文献|论文|手册|案例|上传|文件|\.xlsx?\b", body.query, re.I)
            and trace.decision.route in {Route.KNOWLEDGE, Route.CLARIFY}
            and ((not new_text and is_followup(body.query)) or bool(re.search(
                r"更正|其他(?:条件)?不变|重新给出|(?:汇总|总结).{0,8}(?:最终|当前|采用)|"
                r"(?:列出|汇总).{0,12}(?:目前|当前)|现在.{0,12}(?:试验|计划).{0,8}(?:改为|改成)", record_instruction))))
        case_followup = case_followup or record_followup
        if case_followup:
            trace.decision.route = Route.KNOWLEDGE
            trace.decision.skills = ["case_assistant"]
            trace.decision.reason_code = "case_followup"
        if body.case_skill or body.case_mode:
            trace.decision.route = Route.KNOWLEDGE
            trace.decision.skills = ["case_assistant"]
            trace.decision.reason_code = "explicit_case_mode" if body.case_mode else "legacy_case_entry"
        elif explicit_ids:
            trace.decision.route = Route.KNOWLEDGE
            trace.decision.skills = ["case_assistant"]
            trace.decision.reason_code = "explicit_case_ids"
        if trace.decision.skills == ["case_assistant"]:
            default = state.case_mode if case_followup and state.case_clarification_pending else "explain" if (case_followup or explicit_ids or body.case_skill == "explain" or new_text) else "search"
            mode = body.case_mode or case_mode(body.query, default)
            ids = list(explicit_ids)
            previous_displayed = list(state.current_case_ids)
            context_text = ""
            if case_followup:
                # Only displayed identifiers (or verified user selection), never all retrieved candidates.
                ids = context.get("resolved_case_ids") or list(state.current_case_ids) or list(state.user_selected_case_ids)
                context_text = state.case_context_text
            elif mode == "search" and not new_text and re.search(r"类似|这种情况|别人", body.query):
                context_text = next((turn.content for turn in reversed(body.history) if turn.role == "user"), "")
            if len(ids) > MAX_CASE_IDS:
                raise HTTPException(413, detail={"code": "case_capacity", "message": "单次最多指定 30 个案例，请缩小范围。"})
            next_context = context_text or body.query
            if case_followup:
                next_context = f"{context_text}\n用户补充：{body.query}"
                if len(next_context) > 24000:
                    raise HTTPException(413, detail={"code": "case_capacity", "message": "累计补充内容超过容量，请在新对话中精简说明。"})
            lookup_cases = (body.case_skill == "reference" or mode == "search" or trace.decision.reason_code in {"case_reference_intent", "case_reference_and_explanation"} or (bool(re.search(r"案例|库中|库内", body.query)) and not new_text))
            if case_followup and state.case_material_source == "user_text" and body.case_skill != "reference":
                lookup_cases = False
            if (not (ids or new_text or context_text or lookup_cases) and
                    (mode in {"compare", "evidence"} or re.search(r"这[份段张些个两]|那[份段张些个两]|上述|上面|指定|材料中|表格中", body.query))):
                trace.decision.route = Route.CLARIFY
                trace.decision.reason_code = "missing_case_material"
                return await self._call(registry, "clarification", {"message": "请指定要核对或比较的案例，或粘贴相关材料；当前没有已确认的对象。"}, trace)
            trace.case_context = {"mode": mode, "previous_displayed_case_ids": previous_displayed,
                                  "user_selected_case_ids": list(explicit_ids), "requested_case_ids": ids}
            # A referent without a verified displayed scope must not search unrelated objects.
            if referent and not new_search and not new_text and not ids and state.case_material_source != "user_text" and not (body.case_mode == "search" or body.case_skill == "reference"):
                trace.decision.route = Route.CLARIFY
                trace.decision.reason_code = "missing_case_referent"
                return await self._call(registry, "clarification", {"message": "当前没有可确认的已展示案例，请指定案例或粘贴要解释的材料。"}, trace)
            result = await self._call(registry, "case_assistant", {
                "query": (body.query if case_followup and state.case_material_source == "user_text" else
                    context.get("resolved_query", body.query) if body.query == trace.input else body.query),
                "mode": mode, "case_ids": ids, "lookup_cases": lookup_cases, "context_text": context_text,
                "history": [t.model_dump() for t in body.history]}, trace)
            result.case_route = ["case_assistant"]
            result.case_mode = mode
            retrieved = list(dict.fromkeys(record["id"] for selection in trace.retrieval if selection.get("source_type") == "case"
                for record in selection.get("candidates", []) if record.get("selected")))
            displayed = [item.id for item in result.case_references]
            material_source = "library" if ids or lookup_cases else "user_text"
            trace.case_context.update(retrieved_case_ids=retrieved, displayed_case_ids=displayed, material_source=material_source)
            state.last_tool, state.case_mode = "case_assistant", mode
            state.retrieved_case_ids = retrieved
            if explicit_ids:
                state.user_selected_case_ids = list(explicit_ids)
            elif not case_followup:
                state.user_selected_case_ids = []
            if displayed or not case_followup:
                state.current_case_ids = displayed
            if result.case_references:
                next_context += "\n本轮参考案例顺序：" + "、".join(item.title for item in result.case_references)
            state.case_context_text = next_context[-24000:]
            state.case_material_source = material_source
            state.case_clarification_pending = result.outcome == "clarification"
            return result
        recent_user = next((t.content for t in reversed(body.history) if t.role == "user"), "")
        if (trace.decision.skills == ["knowledge_search"] and
                re.fullmatch(r"(?:那|那么)?(?:它|这个|那个)(?:的)?(?:有什么用|有哪些用途|能做什么|怎么用|如何应用)[？?。]*", body.query)
                and (state.last_tool == "concept_explanation" or concept_intent(recent_user))):
            trace.decision.skills = ["concept_explanation"]
            trace.decision.reason_code = "concept_followup"
        if trace.decision.skills == ["concept_explanation"]:
            state.last_tool = "concept_explanation"
            return await self._call(registry, "concept_explanation", {"query": body.query, "history": [t.model_dump() for t in body.history],
                "k": body.k, "session_documents": documents}, trace)
        route = trace.decision.route
        attachment_count = len(state.session_file_ids) if session_files else int(body.file_id is not None)
        document_only = bool(documents) and len(documents) == attachment_count
        if documents and route in {Route.FILE_ANALYSIS, Route.COMPOSED} and (
            document_only or re.search(r"\.(?:txt|md|pdf|docx?)\b", body.query, re.I)
            or (route == Route.FILE_ANALYSIS and not has_statistic_request(body.query)
                and not re.search(r"\.(?:xls|xlsx)\b|nbal_out|wtabal_out|waterbal_out", body.query, re.I))
        ):
            trace.decision.route = route = Route.KNOWLEDGE
            trace.decision.reason_code = "session_document_question"
            trace.decision.skills = ["knowledge_search"]
        referent = re.compile(r"(?:它|这个|那个|这|那)(?:的)?(?:有什么用|能解决什么问题|是什么|呢|怎么样)[？?。]*")
        has_subject = any(turn.role == "user" and not (guidance_query(turn.content) or FOLLOWUP.fullmatch(turn.content)
                          or referent.fullmatch(turn.content)) for turn in body.history)
        more_context = bool(re.fullmatch(r"(?:还)?有(?:没有)?(?:什么)?(?:其他|其它|更多)(?:的)?(?:信息|内容|结果)(?:不|吗|么|呢)?[？?。]*|还有呢[？?。]*", body.query))
        if more_context and (state.session_file_ids if session_files else body.file_id) and not (
            document_only or (documents and state.last_tool == "knowledge_search")
        ):
            trace.decision.route = route = Route.FILE_ANALYSIS
            trace.decision.reason_code = "session_file_overview"
        elif more_context and not has_subject:
            trace.decision.route = route = Route.CLARIFY
            trace.decision.reason_code = "unclear_referent"
        if referent.fullmatch(body.query) and not has_subject:
            trace.decision.route = route = (Route.KNOWLEDGE if documents else Route.FILE_ANALYSIS) if session_files and state.session_file_ids else Route.CLARIFY
            trace.decision.reason_code = "unclear_referent"
        if route in {Route.DIRECT, Route.OUT_OF_SCOPE}:
            state.last_tool = "capability_guidance"
            return await self._call(registry, "capability_guidance", {"outside_domain": route == Route.OUT_OF_SCOPE}, trace)
        if route == Route.CLARIFY:
            self.states.clear_metric(state)
            message = ("请先上传要查询的结果表（.xls 或 .xlsx），再说明字段及最大值或最小值。"
                       if trace.decision.reason_code == "missing_attachment" else
                       "请补充你指的是哪个模型、指标或问题，以及希望了解的内容；如果要分析结果表，可上传文件并说明字段和统计项。")
            if trace.decision.reason_code == "unclear_intent":
                message = DOMAIN_GUIDANCE_ANSWER
            return await self._call(registry, "clarification", {"message": message}, trace)
        if session_files and route in {Route.FILE_ANALYSIS, Route.COMPOSED}:
            return await self._session_files(body, state, trace, registry, documents)
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
                operation = "最小值" if re.search(r"最小|最低|\b(?:minimum|min)\b", query, re.I) else "最大值"
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
            return await self._compose(body, state, trace, registry, documents)
        history = [DialogueTurn(role=m.role, content=m.content) for m in body.history]
        query = context.get("resolved_query", body.query) if body.query == trace.input else body.query
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
        factor_pattern = r"(?:氮素|硝态氮|硝酸盐).*?(?:淋失|淋洗).*?因素|哪些因素.*?(?:淋失|淋洗)"
        factor_question = bool(re.search(factor_pattern, body.query))
        previous_questions = []
        if is_followup(body.query):
            # Retain the ongoing user topic and source constraints, stopping at
            # its standalone question so earlier topics cannot leak back in.
            for turn in reversed(history):
                if turn.role != "user":
                    continue
                previous_questions.append(turn.content)
                if not is_followup(turn.content):
                    break
        previous_scope = "\n".join(reversed(previous_questions))
        source_scope = previous_scope + "\n" + body.query
        if (previous_scope and re.search(r"因素|因子|影响|作用|贡献|重要|关键|主导|为什么|为何|原因|机制|机理", body.query)
                and re.search(factor_pattern, previous_scope)):
            factor_question = True
            # Mechanism retrieval also needs the subject; it does not consume
            # dialogue history as factual evidence.
            query = f"前文用户问题与约束：\n{previous_scope}\n本轮问题：{query}"
        source_bound = bool(re.search(r"文献|论文|研究中|研究表明|参考资料|知识库|原文|正文|引用|出处|证据|doi|https?://|\[\d+\]", source_scope, re.I))
        general_factors = factor_question and not documents and not source_bound
        previous_document_scope = state.understanding_context.get('literature_scope') or {}
        document_followup = (bool(documents)
            and previous_document_scope.get('mode') == 'session_documents'
            and previous_document_scope.get('document_sha256') == sorted(document['sha256'] for document in documents)
            and (is_followup(body.query) or bool(re.search(r'据此|缺失|补(?:齐|全|出)|(?:材料|文档|文件)(?:中|里)', body.query))))
        try:
            result = await self._call(registry, "knowledge_search",
                                      {"query": query, "k": body.k, "history": history,
                                       "mode": "mechanisms" if factor_question and not documents and source_bound and not WEB_REQUEST.search(body.query) else "answer", "crop": state.crop,
                                       "allow_general_knowledge": general_factors,
                                       "purpose": "maize_factors" if factor_question and state.crop == "玉米" else "general",
                                       "session_document_only": (trace.decision.reason_code == "session_document_question" or document_followup)
                                           and not re.search(r"文献|论文|手册|知识库|联网|搜索|检索|search|papers?|literature", body.query, re.I),
                                       "session_documents": documents}, trace)
        except MechanismEvidenceError as exc:
            trace.decision.route = Route.CLARIFY
            trace.decision.reason_code = exc.code
            if exc.code == "mechanism_evidence_missing":
                message = "本次检索未获得足以支持这些影响因素的正文证据，不代表知识库中没有相关文献。可补充研究场景或调整问题后重试。"
            elif exc.code == "mechanism_output_invalid":
                message = "已找到候选正文，但本次机制回答的格式校验未通过，暂未生成可核对的结论。请重试；这不代表知识库缺少相关文献。"
            else:
                message = "已找到候选正文，但自动重试后生成的机制结论与引用或适用范围仍未通过核对，暂未生成可核对的回答。可稍后重试；这不代表你的问题有误或知识库缺少相关文献。"
            result = await self._call(registry, "clarification", {"message": message}, trace)
            result.warnings = [RunWarning(code=exc.code, message=message)]
        return result

    async def _session_files(self, body: ChatRequest, state: TaskState, trace: RunTrace,
                             registry: SkillRegistry, documents: list[dict]) -> ChatResponse:
        """Inspect session workbooks, then calculate only fields actually requested."""
        reports = []
        unavailable = []
        attachment_states = []
        for token in state.session_file_ids:
            try:
                inspection = await self._call(registry, "file_inspector", {"file_id": token}, trace)
                attachment_states.append(self._ready_attachment(inspection.report).model_copy(update={"file_id": token}))
                if inspection.report.get("kind") == "document":
                    continue
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
            operation = "最小值" if re.search(r"最小|最低|\b(?:minimum|min)\b", query, re.I) else "最大值"
            query = f"{state.current_metric} {operation}及对应日序"
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
        # Metadata after a comma (e.g. "给出单位和单元格") belongs to the
        # same calculation. Validate the complete single-field request first.
        clauses = ([query] if parse_file_request(query, all_fields, reports[0][1]["file"] if len(reports) == 1 else "")
                   else [part.strip() for part in re.split(r"[，,；;]|并且", query) if part.strip()])
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
            result = await self._compose(body.model_copy(update={"file_id": used[0][0]}), state, trace, registry, documents)
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
                       registry: SkillRegistry, documents: list[dict]) -> ChatResponse:
        file_query = split_composed(body.query)
        if file_query is None:
            self.states.clear_metric(state)
            trace.decision.route = Route.CLARIFY
            trace.decision.reason_code = "unsupported_composed_request"
            return await self._call(registry, "clarification", {"message":
                "请先明确要计算的字段与最大/最小值，再询问可能机制。例如：硝态氮最大值是多少，为什么可能这么高？"
                "目前组合分析不支持时段筛选、多指标比较或确定性归因。"}, trace)
        if state.current_metric and state.last_tool == "whcns_analyzer" and FOLLOWUP.fullmatch(file_query):
            operation = "最小值" if re.search(r"最小|最低|\b(?:minimum|min)\b", file_query, re.I) else "最大值"
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
                                             {"query": query, "k": body.k,
                                              "mode": "answer" if documents else "mechanisms", "crop": state.crop,
                                              "purpose": "peak" if peak_question else "general",
                                              "session_documents": documents}, trace)
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
                      f"{'上传资料与文献' if documents else '文献'}只提供待核查的机制，不能证明本表峰值原因；当前没有执行 WHCNS，也不据此给出施肥量。")
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
        result = reply(f"表中观察\n{file_text}\n\n为何目前不能归因\n{diagnosis}\n\n{'资料' if documents else '文献'}中的事件尺度线索\n{mechanism_text}\n\n下一步核查\n{limitation}",
                       evidence=numeric.file_evidence if numeric else [])
        result.route = "composed"
        result.outcome = "partial" if warnings and (numeric or knowledge) else "clarification" if warnings else "complete"
        result.attachment, result.sections, result.warnings = attachment, sections, warnings
        if knowledge:
            result.citations, result.usage = knowledge.citations, knowledge.usage
            result.retrieved_count, result.model = knowledge.retrieved_count, knowledge.model
        return result
