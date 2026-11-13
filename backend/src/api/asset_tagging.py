"""Developer-only, durable whole-library tagging with revision-fenced saves."""
import asyncio
import json
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.api.literature import ExtractInput, extraction_path, fail, now, pdf_text_for_ai, store, validate_tag_selection
from src.api.literature_tagging import available_taxonomy, merge_tag_suggestions, suggest_tags
from src.evaluation.auth import current_user, require_developer
from src.evaluation.contracts import Principal

router = APIRouter(prefix='/asset-tag-jobs')


class StartInput(BaseModel):
    mode: Literal['merge', 'replace'] = 'merge'


def developer(user: Principal = Depends(current_user)):
    require_developer(user)
    return user


def catalog(db):
    # Membership counts change while tagging; only freeze the classification rules.
    return db.matching_taxonomy()


def preflight(request, db):
    if getattr(request.app.state, 'llm', None) is None:
        fail('tagging_unavailable', 'AI 服务暂不可用，请稍后重试。', 503)
    if not available_taxonomy(catalog(db))['tags']:
        fail('no_available_tags', '请先添加并启用标签。', 422)


def job_record(db, identifier):
    row = db.db.execute('SELECT * FROM asset_tag_jobs WHERE id=?', (identifier,)).fetchone()
    if row is None:
        fail('asset_tag_job_missing', '全库打标任务不存在。', 404)
    return dict(row)


def summary(db, identifier):
    with db.lock:
        job = job_record(db, identifier)
        counts = dict(db.db.execute('SELECT status,count(*) FROM asset_tag_items WHERE job_id=? GROUP BY status', (identifier,)).fetchall())
        kinds = dict(db.db.execute('SELECT kind,count(*) FROM asset_tag_items WHERE job_id=? GROUP BY kind', (identifier,)).fetchall())
    pending = counts.get('queued', 0) + counts.get('processing', 0)
    interrupted = bool(pending and time.time() - job['updated_at'] > 300)
    return {key: job[key] for key in ('id', 'actor', 'mode', 'created_at')} | {
        'counts': counts, 'assets': kinds, 'total': sum(counts.values()),
        'active': bool(pending), 'interrupted': interrupted,
        'taxonomy_changed': json.loads(job['taxonomy']) != catalog(db),
        'retryable': interrupted or bool(not pending and counts.get('failed')),
    }


def touch(db, identifier):
    db.db.execute('UPDATE asset_tag_jobs SET updated_at=? WHERE id=?', (time.time(), identifier))


async def process_job(request, identifier):
    db = store(request)
    cases = getattr(request.app.state, 'case_library', None)
    with db.lock:
        job = job_record(db, identifier)
    taxonomy = json.loads(job['taxonomy'])
    user = Principal(tester_id=job['actor'], role='developer')
    if not hasattr(request.app.state, 'asset_tagging_slots'):
        request.app.state.asset_tagging_slots = asyncio.Semaphore(3)

    async def process(item, attempt):
        if catalog(db) != taxonomy:
            fail('tagging_taxonomy_changed', '标签体系已变更，已跳过；请按最新标签重新发起。', 409)
        if item['kind'] == 'case':
            if cases is None:
                fail('case_tagging_unavailable', '案例库暂不可用。', 503)
            asset = cases.get(item['asset_id'])
            text = asset['body']
            fields = {key: asset[key] for key in ('title', 'body_format', 'explanation', 'supplementary', 'source')}
        else:
            asset = db.get_paper(item['asset_id'])
            fields = {key: asset.get(key, '') for key in ('title', 'abstract', 'conclusion')}
            path = extraction_path(db, ExtractInput(paper_id=asset['id']), user)
            text, _ = await pdf_text_for_ai(path)
        if asset['revision'] != item['revision']:
            fail('asset_changed', '资产已修改，已跳过；请重新发起打标。', 409)
        before = asset['tag_ids']
        selected = before if job['mode'] == 'merge' else []
        proposed = await suggest_tags(text, fields, taxonomy, selected, request.app.state.llm,
                                      source_kind='case' if item['kind'] == 'case' else 'literature')
        # Atomically save case/paper assignments and the receipt. Lock order matches
        # manual edits and taxonomy deletion: taxonomy first, then the case store.
        with db.write_with_cases(cases if item['kind'] == 'case' else None):
            current = db.db.execute('SELECT status,attempt FROM asset_tag_items WHERE job_id=? AND kind=? AND asset_id=?',
                                    (identifier, item['kind'], item['asset_id'])).fetchone()
            if current['status'] != 'processing' or current['attempt'] != attempt:
                return
            if catalog(db) != taxonomy:
                fail('tagging_taxonomy_changed', '标签体系已变更，已跳过；请按最新标签重新发起。', 409)
            tags = merge_tag_suggestions(taxonomy, selected, proposed)
            validate_tag_selection(db, tags, previous=before)
            at = now()
            if item['kind'] == 'case':
                updated = db.db.execute('UPDATE tag_cases.reference_cases SET tag_ids=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=? AND revision=? AND deleted=0',
                                        (json.dumps(tags), job['actor'], at, item['asset_id'], item['revision']))
            else:
                data = json.loads(db.db.execute('SELECT data FROM papers WHERE id=?', (item['asset_id'],)).fetchone()[0])
                data['tag_ids'] = tags
                updated = db.db.execute('UPDATE papers SET data=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=? AND revision=? AND deleted=0',
                                        (json.dumps(data, ensure_ascii=False), job['actor'], at, item['asset_id'], item['revision']))
            if updated.rowcount != 1:
                fail('asset_changed', '资产已修改或删除，已跳过；请重新发起打标。', 409)
            if item['kind'] == 'literature':
                db.db.execute('DELETE FROM paper_tags WHERE paper_id=?', (item['asset_id'],))
                db.db.executemany('INSERT INTO paper_tags VALUES (?,?)', [(item['asset_id'], tag) for tag in tags])
            db.event('paper' if item['kind'] == 'literature' else 'case', item['asset_id'], 'edit', job['actor'],
                     before={'tag_ids': before}, after={'tag_ids': tags}, reason=f'全库 AI 打标：{identifier}')
            db.db.execute("UPDATE asset_tag_items SET status='ready',message=?,before_tags=?,after_tags=? WHERE job_id=? AND kind=? AND asset_id=?",
                          ('已保存' if tags else '未匹配标签', json.dumps(before), json.dumps(tags), identifier, item['kind'], item['asset_id']))
            touch(db, identifier)

    async def worker():
        async with request.app.state.asset_tagging_slots:
            while True:
                attempt = uuid4().hex
                with db.write():
                    row = db.db.execute("SELECT * FROM asset_tag_items WHERE job_id=? AND status='queued' ORDER BY kind,asset_id LIMIT 1", (identifier,)).fetchone()
                    if row is None:
                        return
                    item = dict(row)
                    db.db.execute("UPDATE asset_tag_items SET status='processing',attempt=? WHERE job_id=? AND kind=? AND asset_id=?",
                                  (attempt, identifier, item['kind'], item['asset_id']))
                    touch(db, identifier)
                try:
                    await asyncio.wait_for(process(item, attempt), timeout=90)
                except Exception as exc:
                    conflict = isinstance(exc, HTTPException) and exc.status_code in {404, 409}
                    message = exc.detail.get('message', '打标失败，请重试。') if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else '打标失败，请重试。'
                    with db.write():
                        db.db.execute("UPDATE asset_tag_items SET status=?,message=? WHERE job_id=? AND kind=? AND asset_id=? AND attempt=? AND status='processing'",
                                      ('conflict' if conflict else 'failed', message, identifier, item['kind'], item['asset_id'], attempt))
                        touch(db, identifier)

    await asyncio.gather(*(worker() for _ in range(3)))


@router.post('', status_code=202)
def start(request: Request, body: StartInput, tasks: BackgroundTasks, user: Principal = Depends(developer)):
    db = store(request)
    preflight(request, db)
    cases = getattr(request.app.state, 'case_library', None)
    with db.write_with_cases(cases):
        active = db.db.execute("SELECT job_id FROM asset_tag_items WHERE status IN ('queued','processing') LIMIT 1").fetchone()
        if active:
            if json.loads(job_record(db, active[0])['taxonomy']) == catalog(db):
                return summary(db, active[0])
            db.db.execute("UPDATE asset_tag_items SET status='conflict',message='标签体系已变更，已由新任务接替。',attempt=NULL WHERE job_id=? AND status IN ('queued','processing')", (active[0],))
        identifier = uuid4().hex
        db.db.execute('INSERT INTO asset_tag_jobs VALUES (?,?,?,?,?,?)',
                      (identifier, user.tester_id, body.mode, json.dumps(catalog(db), ensure_ascii=False), now(), time.time()))
        papers = db.db.execute('SELECT id,data,revision FROM papers WHERE deleted=0').fetchall()
        items = [('literature', row['id'], json.loads(row['data']).get('title') or row['id'], row['revision']) for row in papers]
        if cases is not None:
            items.extend(('case', row['id'], row['title'], row['revision']) for row in db.db.execute('SELECT id,title,revision FROM tag_cases.reference_cases WHERE deleted=0'))
        if not items:
            fail('no_tagging_assets', '暂无可打标的文献或案例。', 422)
        db.db.executemany('INSERT INTO asset_tag_items(job_id,kind,asset_id,title,revision) VALUES (?,?,?,?,?)',
                         [(identifier, *item) for item in items])
    tasks.add_task(process_job, request, identifier)
    return summary(db, identifier)


@router.get('')
def history(request: Request, user: Principal = Depends(developer)):
    db = store(request)
    with db.lock:
        ids = [row[0] for row in db.db.execute('SELECT id FROM asset_tag_jobs ORDER BY created_at DESC LIMIT 10')]
    return {'items': [summary(db, identifier) for identifier in ids]}


@router.get('/{identifier}')
def detail(request: Request, identifier: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
           user: Principal = Depends(developer)):
    db = store(request)
    with db.lock:
        result = summary(db, identifier)
        items = [dict(row) for row in db.db.execute('SELECT * FROM asset_tag_items WHERE job_id=? ORDER BY kind,asset_id LIMIT ? OFFSET ?', (identifier, limit, offset))]
    for item in items:
        for key in ('before_tags', 'after_tags'):
            item[key] = json.loads(item[key]) if item[key] is not None else None
        item.pop('attempt', None)
    return result | {'items': items, 'offset': offset, 'limit': limit}


@router.post('/{identifier}/retry', status_code=202)
def retry(request: Request, identifier: str, tasks: BackgroundTasks, user: Principal = Depends(developer)):
    db = store(request)
    preflight(request, db)
    with db.write():
        job = job_record(db, identifier)
        if json.loads(job['taxonomy']) != catalog(db):
            fail('tagging_taxonomy_changed', '标签体系已变更，请重新发起全库打标。', 409)
        result = summary(db, identifier)
        if not result['retryable']:
            fail('tagging_retry_unavailable', '任务仍在运行或没有可重试项目。', 409)
        # All jobs share one queue; a later job must not race a retry of an old one.
        other = db.db.execute("SELECT 1 FROM asset_tag_items WHERE job_id!=? AND status IN ('queued','processing') LIMIT 1", (identifier,)).fetchone()
        if other:
            fail('tagging_in_progress', '已有全库打标任务运行中，请稍后重试。', 409)
        db.db.execute("UPDATE asset_tag_items SET status='queued',attempt=NULL,message='' WHERE job_id=? AND status IN ('failed','queued','processing')", (identifier,))
        touch(db, identifier)
    tasks.add_task(process_job, request, identifier)
    return summary(db, identifier)
