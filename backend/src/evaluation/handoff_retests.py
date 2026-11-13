"""Authorized full-pipeline retests of immutable offline conversation sources."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from pydantic import Field
from loguru import logger

from src.agent.contracts import Contract
from src.agent.task_prompts import TaskScope
from src.api.chat_schema import ChatRequest
from src.evaluation.store import fail, now


class HandoffRetestInput(Contract):
    submission_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    prompt_id: str = Field(min_length=1, max_length=100)
    task_prompt_ids: dict[TaskScope, str] = Field(default_factory=dict, max_length=3)


class HandoffJudgment(Contract):
    conclusion: str = Field(pattern=r'^(pass|fail|pending)$')
    basis: str = Field(min_length=1, max_length=5000)


def sources(database: Path) -> list[dict]:
    if not database.is_file():
        return []
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM handoff_sources ORDER BY local_id')]


class HandoffRetests:
    def __init__(self, runtime, source_database):
        self.runtime = runtime
        self.source_database = Path(source_database)
        self.db, self.lock = runtime.runs._connection, runtime.runs._lock
        self.tasks = {}
        with self.lock, self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS handoff_retests (
                attempt_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, actor TEXT NOT NULL,
                submission_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(actor,submission_id))''')
            for aid, raw in self.db.execute('SELECT attempt_id,payload FROM handoff_retests').fetchall():
                value = json.loads(raw)
                if value['status'] in {'queued', 'running'}:
                    value.update(status='interrupted', finished_at=now())
                    self.db.execute('UPDATE handoff_retests SET payload=? WHERE attempt_id=?', (json.dumps(value, ensure_ascii=False), aid))

    def source(self, identifier):
        item = next((r for r in sources(self.source_database) if r['local_id'] == identifier), None)
        if item is None:
            raise fail('handoff_source_not_found', '未找到本地交接来源，请先运行隔离导入脚本。', 404)
        return item

    def list(self, source_id):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM handoff_retests WHERE source_id=? ORDER BY rowid DESC', (source_id,))]

    def get(self, attempt_id):
        with self.lock:
            row = self.db.execute('SELECT payload FROM handoff_retests WHERE attempt_id=?', (attempt_id,)).fetchone()
        if row is None:
            raise fail('handoff_attempt_not_found', '未找到此验证记录。', 404)
        return json.loads(row[0])

    def save(self, value):
        with self.lock, self.db:
            self.db.execute('UPDATE handoff_retests SET payload=? WHERE attempt_id=?', (json.dumps(value, ensure_ascii=False), value['attempt_id']))

    def submit(self, source_id, body, user, execute):
        source = self.source(source_id)
        fingerprint = hashlib.sha256(json.dumps([source_id, body.prompt_id, body.task_prompt_ids], sort_keys=True).encode()).hexdigest()
        prompt = next((p for p in self.runtime.runs.prompts.list() if p['prompt_id'] == body.prompt_id), None)
        if prompt is None:
            raise fail('prompt_not_found', '请选择已保存的表达 Prompt。', 404)
        config = {**self.runtime.expression_snapshot(), 'communication': prompt}
        if body.task_prompt_ids and source['source']['baseline']['skills'] == ['capability_guidance']:
            raise fail('program_has_no_task_prompt', '程序能力说明不使用任务 Prompt。', 422)
        for scope, identifier in body.task_prompt_ids.items():
            candidate = self.runtime.runs.task_prompts.get(identifier)
            if candidate['scope'] != scope:
                raise fail('task_prompt_scope_mismatch', '候选与所选任务范围不一致。', 422)
            config['task_prompts'][scope] = candidate
        with self.lock, self.db:
            prior = self.db.execute('SELECT attempt_id,fingerprint FROM handoff_retests WHERE actor=? AND submission_id=?', (user.tester_id, body.submission_id)).fetchone()
            if prior:
                if prior[1] != fingerprint:
                    raise fail('handoff_submission_conflict', '同一提交标识不能用于不同来源或候选。')
                identifier = prior[0]
                created = False
            else:
                if len(self.tasks) >= 2:
                    raise fail('handoff_capacity', '已有两个验证在运行，请稍后重试。', 429)
                identifier = str(uuid4())
                value = {'attempt_id': identifier, 'source_id': source_id, 'actor': user.tester_id,
                         'created_at': now(), 'status': 'queued', 'mode': 'full_pipeline',
                         'candidate_scope': 'program' if source['source']['baseline']['skills'] == ['capability_guidance'] else 'communication', 'requested_prompt_id': body.prompt_id, 'requested_task_prompt_ids': body.task_prompt_ids,
                         'expression_config': config, 'config_version': self.runtime.config_version,
                         'config_manifest': self.runtime.config_manifest,
                         'source_snapshot': source, 'steps': [], 'quality': 'pending', 'judgments': [],
                         'deployment_status': 'not_linked', 'simulated': False}
                self.db.execute('INSERT INTO handoff_retests VALUES (?,?,?,?,?,?)', (identifier, source_id, user.tester_id, body.submission_id, fingerprint, json.dumps(value, ensure_ascii=False)))
                created = True
        if created:
            task = asyncio.create_task(self.run(identifier, execute))
            self.tasks[identifier] = task
            task.add_done_callback(lambda completed: self._done(identifier, completed))
        return self.get(identifier)

    def _done(self, identifier, task):
        self.tasks.pop(identifier, None)
        try:
            value = self.get(identifier)
            if value['status'] in {'queued', 'running'}:
                value.update(status='interrupted' if task.cancelled() else 'failed', finished_at=now())
                self.save(value)
            if not task.cancelled():
                task.exception()
        except Exception:
            logger.exception('Handoff terminal state could not be saved | attempt_id={}', identifier)

    async def run(self, identifier, execute):
        value = self.get(identifier)
        value['status'] = 'running'
        self.save(value)
        source = value['source_snapshot']
        history = list(source['seed_history'])
        session = 'handoff_' + identifier.replace('-', '')
        try:
            for step in source['case']['steps']:
                if self.runtime.config_version != value['config_version']:
                    raise fail('handoff_build_changed', '构建版本已改变，请建立新的验证。')
                if step['action'] != 'query':
                    value.update(status='blocked', blocked_step=len(value['steps']) + 1)
                    break
                run_id = str(uuid4())
                bounded_history = [{**turn, 'content': turn['content'][:4000]} for turn in history[-12:]]
                entry = {'run_id': run_id, 'query': step['input'], 'history': bounded_history, 'status': 'running'}
                value['steps'].append(entry)
                self.save(value)
                query = ChatRequest(query=step['input'], history=bounded_history, session_id=session, operator_id=value['actor'])
                entry.update(query=query.query, history=query.model_dump()['history'])
                response = await execute(query, run_id, value['expression_config'])
                trace = self.runtime.runs.get(run_id)
                if not trace or trace.skill_config['communication']['prompt_id'] != value['requested_prompt_id']:
                    raise fail('handoff_candidate_unverified', '未保存可核对的实际候选版本。')
                if response.model == 'simulated':
                    value['simulated'] = True
                entry.update(status='completed', response=response.model_dump(mode='json'),
                             actual_prompt=trace.skill_config['communication'],
                             actual_config_version=trace.config_version, case_context=trace.case_context,
                             actual_task_prompts=trace.skill_config.get('task_prompts', {}),
                             task_prompt_usage=trace.skill_config.get('task_prompt_usage', []))
                history += [{'role': 'user', 'content': query.query}, {'role': 'assistant', 'content': response.answer}]
                self.save(value)
            else:
                value['status'] = 'completed'
                used = {u.get('prompt_id') for step in value['steps'] for u in step.get('task_prompt_usage', [])}
                value['unused_task_scopes'] = [scope for scope, pid in value.get('requested_task_prompt_ids', {}).items() if pid not in used]
        except asyncio.CancelledError:
            value['status'] = 'interrupted'
            if value['steps'] and value['steps'][-1]['status'] == 'running':
                value['steps'][-1]['status'] = 'interrupted'
        except Exception as exc:
            value['status'] = 'failed'
            detail = getattr(exc, 'detail', {})
            code = detail.get('code', 'handoff_execution_failed') if isinstance(detail, dict) else 'handoff_execution_failed'
            value['error_code'] = code
            if value['steps'] and value['steps'][-1]['status'] == 'running':
                value['steps'][-1].update(status='failed', error_code=code)
        finally:
            value['finished_at'] = now()
            self.save(value)

    def judge(self, identifier, body, user):
        with self.lock, self.db:
            row = self.db.execute('SELECT payload FROM handoff_retests WHERE attempt_id=?', (identifier,)).fetchone()
            if row is None:
                raise fail('handoff_attempt_not_found', '未找到此验证记录。', 404)
            value = json.loads(row[0])
            if value['status'] != 'completed':
                raise fail('handoff_attempt_incomplete', '技术执行未完成，不能作为有效核对依据。')
            if body.conclusion == 'pass' and value.get('unused_task_scopes'):
                raise fail('task_candidate_not_used', '所选任务候选未实际进入模型调用，不能确认该候选验证符合。')
            if not body.basis.strip():
                raise fail('handoff_basis_required', '请填写核对依据。', 422)
            value['judgments'].append({**body.model_dump(), 'actor': user.tester_id, 'created_at': now(), 'method': 'human'})
            value['quality'] = body.conclusion
            self.db.execute('UPDATE handoff_retests SET payload=? WHERE attempt_id=?', (json.dumps(value, ensure_ascii=False), identifier))
        return value

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
