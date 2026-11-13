"""Integrated, conversation-sized evaluation, shared by developers and experts."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from src.api.chat import execute_chat
from src.api.files import file_store, inspect_upload
from src.api.session_documents import DOCUMENT_SUFFIXES, inspect_document
from src.evaluation.auth import current_user, require_developer
from src.evaluation.contracts import Principal
from src.evaluation.conversation_cases import (GroupInput, CaptureInput, CaseUpdate, BatchInput,
    JudgmentInput, IssueInput, IssueUpdate, ConfirmationInput, fail)

router = APIRouter()


def workspace(request):
    return request.app.state.agent_runtime.runs.conversation_cases


@router.get('/case-groups')
def groups(request: Request, user: Principal = Depends(current_user)):
    return workspace(request).groups()


@router.post('/case-groups', status_code=201)
def create_group(request: Request, body: GroupInput, user: Principal = Depends(current_user)):
    return workspace(request).create_group(body, user.tester_id)


@router.get('/case-groups/{group_id}')
def group(request: Request, group_id: str, user: Principal = Depends(current_user)):
    return workspace(request).group(group_id)


@router.post('/case-groups/{group_id}/cases', status_code=201)
def capture(request: Request, group_id: str, body: CaptureInput, user: Principal = Depends(current_user)):
    return workspace(request).capture(group_id, body, user.tester_id)


@router.delete('/case-groups/{group_id}/cases/{case_id}')
def remove(request: Request, group_id: str, case_id: str, user: Principal = Depends(current_user)):
    workspace(request).remove_member(group_id, case_id)
    return {'removed': True}


@router.get('/conversation-cases/{case_id}')
def case(request: Request, case_id: str, user: Principal = Depends(current_user)):
    store = workspace(request)
    value = store.case(case_id)
    return {**value, 'versions': store.versions(case_id), 'groups': store.memberships(value['source_session_id'])}


@router.put('/conversation-cases/{case_id}')
def update_case(request: Request, case_id: str, body: CaseUpdate, user: Principal = Depends(current_user)):
    return workspace(request).update_case(case_id, body, user.tester_id)


@router.get('/conversation-batches')
def batches(request: Request, user: Principal = Depends(current_user)):
    return workspace(request).batches()


@router.post('/conversation-batches', status_code=202)
async def start(request: Request, body: BatchInput, user: Principal = Depends(current_user)):
    runtime = request.app.state.agent_runtime
    files = file_store(request)

    async def restore(raw, filename, session_id):
        inspect = inspect_document if Path(filename).suffix.lower() in DOCUMENT_SUFFIXES else inspect_upload
        profile = await asyncio.to_thread(inspect, raw, filename)
        return files.put(raw, profile, session_id=session_id)

    async def execute(body, run_id, snapshot):
        return await execute_chat(request, body, runtime, run_id=run_id, expression_config=snapshot,
            run_context={'source': 'test'})

    return workspace(request).start(body, user.tester_id, runtime, execute, restore, files.remove)


@router.get('/conversation-batches/{batch_id}')
def batch(request: Request, batch_id: str, user: Principal = Depends(current_user)):
    return workspace(request).batch(batch_id)


@router.post('/conversation-batches/{batch_id}/cancel')
def cancel(request: Request, batch_id: str, user: Principal = Depends(current_user)):
    return workspace(request).cancel(batch_id)


@router.post('/conversation-batches/{batch_id}/cases/{case_id}/judgments')
def judge(request: Request, batch_id: str, case_id: str, body: JudgmentInput, user: Principal = Depends(current_user)):
    return workspace(request).judge(batch_id, case_id, body, user.tester_id)


@router.get('/conversation-issues')
def issues(request: Request, user: Principal = Depends(current_user)):
    store = workspace(request)
    # Old execution issues remain readable and can be captured as full sessions.
    legacy = request.app.state.evaluation.workflow.issues()
    result = store.issues()
    bridged = {i.get('origin_execution_issue_id') for i in result}
    for item in legacy:
        if item['issue_id'] in bridged:
            continue
        session = store.runs.session(item['run_id'])
        if session:
            result.append({'issue_id': 'legacy:' + item['issue_id'], 'session_id': session['session_id'],
                'run_id': item['run_id'], 'source': 'execution', 'note': item['title'] + '\n' + item.get('evidence_note', ''),
                'status': item['status'], 'category': '历史执行问题', 'assignee': item['assignee'],
                'created_at': item['created_at'], 'created_by': item['created_by'], 'revision': item['revision'],
                'history': item['history'], 'cases': [], 'groups': store.memberships(session['session_id']),
                'legacy_id': item['issue_id']})
    return result


@router.post('/conversation-issues', status_code=201)
def create_issue(request: Request, body: IssueInput, user: Principal = Depends(current_user)):
    store = workspace(request)
    if body.origin_execution_issue_id:
        original = request.app.state.evaluation.workflow.issue(body.origin_execution_issue_id)
        session = store.runs.session(original['run_id'])
        if not session or session['session_id'] != body.session_id or original['run_id'] != body.run_id:
            fail('issue_origin_mismatch', '原执行问题与会话不匹配。', 422)
        with store.lock:
            existing = next((i for i in store.issues() if i.get('origin_execution_issue_id') == body.origin_execution_issue_id), None)
            if existing:
                return existing
            issue = store.create_issue(body, user.tester_id, source='execution')
            issue['origin_execution_issue_id'] = body.origin_execution_issue_id
            issue.pop('cases', None)
            issue.pop('groups', None)
            with store.db:
                store._write('conversation_issues', issue['issue_id'], issue)
            return store.issue(issue['issue_id'])
    return store.create_issue(body, user.tester_id)


@router.get('/conversation-issues/{issue_id}')
def issue(request: Request, issue_id: str, user: Principal = Depends(current_user)):
    if issue_id.startswith('legacy:'):
        result = next((i for i in issues(request, user) if i['issue_id'] == issue_id), None)
        if result is None:
            fail('issue_not_found', '未找到该问题。', 404)
        return result
    return workspace(request).issue(issue_id)


@router.put('/conversation-issues/{issue_id}')
def update_issue(request: Request, issue_id: str, body: IssueUpdate, user: Principal = Depends(current_user)):
    return workspace(request).update_issue(issue_id, body, user.tester_id)


@router.get('/conversation-version-events')
def version_events(request: Request, user: Principal = Depends(current_user)):
    return workspace(request).version_events()


@router.post('/conversation-batches/{batch_id}/confirm')
def confirm_version(request: Request, batch_id: str, body: ConfirmationInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return workspace(request).confirm(batch_id, body, user.tester_id, request.app.state.agent_runtime)


@router.post('/conversation-batches/{batch_id}/restore')
def restore_version(request: Request, batch_id: str, body: ConfirmationInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return workspace(request).restore(batch_id, body, user.tester_id, request.app.state.agent_runtime)
