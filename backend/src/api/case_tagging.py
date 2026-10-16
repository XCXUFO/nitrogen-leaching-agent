"""Durable case tagging receipts with optimistic saves and bounded AI workers."""
import asyncio
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.agent.case_ids import CaseId
from src.api.literature import validate_tag_selection
from src.api.literature_tagging import available_taxonomy, merge_tag_suggestions, suggest_tags
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal
from src.storage.case_library import fail

router = APIRouter()


class BatchInput(BaseModel):
    case_ids: list[CaseId] = Field(min_length=1, max_length=100)


def stores(request):
    cases = getattr(request.app.state, 'case_library', None)
    taxonomy = getattr(request.app.state, 'literature', None)
    if cases is None or taxonomy is None:
        fail(503, 'case_tagging_unavailable', '案例或标签系统暂不可用。')
    return cases, taxonomy


def check_ai(request, taxonomy):
    if getattr(request.app.state, 'llm', None) is None:
        fail(503, 'case_ai_unavailable', 'AI 服务暂不可用，请稍后重试。')
    if not available_taxonomy(taxonomy.taxonomy())['tags']:
        fail(422, 'no_available_tags', '请先添加并启用标签。')


@contextmanager
def transaction(db):
    with db.lock:
        db.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            db.db.commit()
        except BaseException:
            db.db.rollback()
            raise


def read_job(db, identifier, owner):
    with db.lock:
        row = db.db.execute('SELECT data FROM case_tag_jobs WHERE id=? AND owner=?', (identifier, owner)).fetchone()
    if row is None:
        fail(404, 'case_tag_job_missing', '打标任务不存在。')
    return json.loads(row[0])


def write_job(db, job):
    db.db.execute('UPDATE case_tag_jobs SET data=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job['id']))


def can_retry(item):
    return item['status'] == 'failed' or (item['status'] in {'queued', 'processing'} and time.time() - item['updated_at'] > 300)


def receipt(job):
    for item in job['items']:
        item['retryable'] = can_retry(item)
    return job


async def process_job(request, identifier, owner):
    cases, taxonomy = stores(request)
    if not hasattr(request.app.state, 'case_tagging_slots'):
        request.app.state.case_tagging_slots = asyncio.Semaphore(3)

    async def process(index):
        async with request.app.state.case_tagging_slots:
            attempt = uuid4().hex
            with transaction(cases):
                job = read_job(cases, identifier, owner)
                item = job['items'][index]
                if item['status'] != 'queued':
                    return
                item.update(status='processing', attempt=attempt, updated_at=time.time())
                write_job(cases, job)
            try:
                case = cases.get(item['case_id'])
                if case['revision'] != item['revision']:
                    fail(409, 'case_conflict', '案例已修改，请重新选择后打标。')
                fields = {key: case[key] for key in ('title', 'body_format', 'explanation', 'supplementary', 'source')}
                proposed = await asyncio.wait_for(suggest_tags(case['body'], fields, taxonomy.taxonomy(), [], request.app.state.llm, source_kind='case'), timeout=45)
                # Same lock order as manual case edits and taxonomy mutations.
                with taxonomy.write(), transaction(cases):
                    latest = read_job(cases, identifier, owner)
                    target = latest['items'][index]
                    if target.get('attempt') != attempt or target['status'] != 'processing':
                        return  # A stale worker may never save or replace a newer receipt.
                    tags = merge_tag_suggestions(taxonomy.taxonomy(), [], proposed)
                    validate_tag_selection(taxonomy, tags)
                    at = datetime.now(timezone.utc).isoformat()
                    updated = cases.db.execute('UPDATE reference_cases SET tag_ids=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=? AND revision=? AND deleted=0',
                        (json.dumps(tags), owner, at, case['id'], item['revision']))
                    if updated.rowcount != 1:
                        fail(409, 'case_conflict', '案例已修改或删除，请重新选择后打标。')
                    target.update(status='ready', revision=item['revision'] + 1, message='已保存' if tags else '未匹配标签', updated_at=time.time())
                    write_job(cases, latest)
            except Exception as exc:
                conflict = isinstance(exc, HTTPException) and exc.status_code in {404, 409}
                message = exc.detail.get('message', '打标失败，请重试。') if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else '打标失败，请重试。'
                with transaction(cases):
                    latest = read_job(cases, identifier, owner)
                    target = latest['items'][index]
                    if target.get('attempt') == attempt and target['status'] == 'processing':
                        target.update(status='conflict' if conflict else 'failed', message=message, updated_at=time.time())
                        write_job(cases, latest)

    job = read_job(cases, identifier, owner)
    await asyncio.gather(*(process(index) for index in range(len(job['items']))))


@router.post('/tag-jobs', status_code=202)
def start(request: Request, body: BatchInput, tasks: BackgroundTasks, user: Principal = Depends(current_user)):
    cases, taxonomy = stores(request)
    if len(set(body.case_ids)) != len(body.case_ids):
        fail(422, 'duplicate_case', '请勿重复选择案例。')
    check_ai(request, taxonomy)
    with transaction(cases):
        records = [cases.get(identifier) for identifier in body.case_ids]
        job = {'id': uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(), 'items': [
            {'case_id': case['id'], 'title': case['title'], 'revision': case['revision'], 'status': 'queued', 'message': '', 'updated_at': time.time()}
            for case in records]}
        cases.db.execute('INSERT INTO case_tag_jobs VALUES (?,?,?,?)', (job['id'], user.tester_id, job['created_at'], json.dumps(job, ensure_ascii=False)))
    tasks.add_task(process_job, request, job['id'], user.tester_id)
    return receipt(job)


@router.get('/tag-jobs')
def history(request: Request, user: Principal = Depends(current_user)):
    cases, _ = stores(request)
    with cases.lock:
        rows = cases.db.execute('SELECT data FROM case_tag_jobs WHERE owner=? ORDER BY created_at DESC LIMIT 10', (user.tester_id,)).fetchall()
    return {'items': [receipt(json.loads(row[0])) for row in rows]}


@router.get('/tag-jobs/{identifier}')
def detail(request: Request, identifier: str, user: Principal = Depends(current_user)):
    cases, _ = stores(request)
    return receipt(read_job(cases, identifier, user.tester_id))


@router.post('/tag-jobs/{identifier}/retry', status_code=202)
def retry(request: Request, identifier: str, tasks: BackgroundTasks, user: Principal = Depends(current_user)):
    cases, taxonomy = stores(request)
    check_ai(request, taxonomy)
    with transaction(cases):
        job = read_job(cases, identifier, user.tester_id)
        for item in job['items']:
            if can_retry(item):
                item.update(status='queued', message='', updated_at=time.time(), attempt=None)
        write_job(cases, job)
    tasks.add_task(process_job, request, identifier, user.tester_id)
    return receipt(job)
