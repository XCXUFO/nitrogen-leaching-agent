"""Conversation cases, grouped release checks, and issues sharing original evidence."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field

from src.agent.contracts import Contract
from src.api.chat_schema import ChatRequest


def now():
    return datetime.now(timezone.utc).isoformat()


def fail(code, message, status=409):
    raise HTTPException(status, detail={'code': code, 'message': message})


class GroupInput(Contract):
    title: str = Field(min_length=1, max_length=100)
    notes: str = Field(default='', max_length=3000)


class CaptureInput(Contract):
    session_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default='', max_length=200)
    expected: str = Field(default='', max_length=5000)
    notes: str = Field(default='', max_length=3000)


class CaseUpdate(Contract):
    title: str = Field(min_length=1, max_length=200)
    expected: str = Field(max_length=5000)
    notes: str = Field(default='', max_length=3000)
    expected_revision: int = Field(ge=1)


class BatchInput(Contract):
    submission_id: str = Field(min_length=1, max_length=100)
    group_ids: list[str] = Field(default_factory=list, max_length=10)
    case_ids: list[str] = Field(default_factory=list, max_length=100)
    version_name: str = Field(min_length=1, max_length=100)


class JudgmentInput(Contract):
    conclusion: str = Field(pattern=r'^(pass|fail|pending)$')
    note: str = Field(min_length=1, max_length=5000)


class IssueInput(Contract):
    session_id: str = Field(min_length=1, max_length=100)
    run_id: str | None = Field(default=None, max_length=100)
    note: str = Field(min_length=1, max_length=5000)
    origin_execution_issue_id: str | None = Field(default=None, max_length=100)


class IssueUpdate(Contract):
    status: str = Field(pattern=r'^(open|in_progress|ready_for_retest|closed)$')
    category: str = Field(default='其他', max_length=50)
    assignee: str = Field(default='', max_length=80)
    note: str = Field(min_length=1, max_length=5000)
    expected_revision: int = Field(ge=1)
    verification_batch_id: str | None = None


class FeedbackInput(Contract):
    run_id: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=5000)
    submission_id: str = Field(min_length=1, max_length=100)


class ConfirmationInput(Contract):
    note: str = Field(min_length=1, max_length=3000)


class ConversationCases:
    def __init__(self, runs):
        self.runs = runs
        self.db, self.lock = runs._connection, runs._lock
        self.jobs = {}
        with self.lock, self.db:
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS conversation_groups (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversation_cases (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS conversation_cases_fingerprint ON conversation_cases(fingerprint);
                CREATE TABLE IF NOT EXISTS conversation_group_members (group_id TEXT NOT NULL, case_id TEXT NOT NULL, PRIMARY KEY(group_id,case_id));
                CREATE TABLE IF NOT EXISTS conversation_batches (id TEXT PRIMARY KEY, actor TEXT NOT NULL, submission_id TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(actor,submission_id));
                CREATE TABLE IF NOT EXISTS conversation_issues (id TEXT PRIMARY KEY, source_key TEXT UNIQUE, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversation_version_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            ''')
            for identifier, raw in self.db.execute('SELECT id,payload FROM conversation_batches').fetchall():
                value = json.loads(raw)
                if value['status'] in {'queued', 'running'}:
                    value.update(status='interrupted', finished_at=now())
                    for result in value['results']:
                        self._interrupt_result(result)
                    self._write('conversation_batches', identifier, value)

    @staticmethod
    def _interrupt_result(result):
        if result['status'] == 'running':
            result['status'] = 'interrupted'
        for turn in result.get('turns', []):
            if turn['status'] == 'running':
                turn['status'] = 'interrupted'

    def _write(self, table, identifier, value):
        self.db.execute(f'UPDATE {table} SET payload=? WHERE id=?', (json.dumps(value, ensure_ascii=False), identifier))

    def _get(self, table, identifier):
        with self.lock:
            row = self.db.execute(f'SELECT payload FROM {table} WHERE id=?', (identifier,)).fetchone()
        if not row:
            fail('conversation_record_missing', '未找到这条记录，请刷新后重试。', 404)
        return json.loads(row[0])

    def create_group(self, body, actor):
        if not body.title.strip():
            fail('group_title_required', '请填写用例组名称。', 422)
        value = {'group_id': str(uuid4()), 'title': body.title.strip(), 'notes': body.notes.strip(),
                 'created_by': actor, 'created_at': now()}
        with self.lock, self.db:
            self.db.execute('INSERT INTO conversation_groups VALUES (?,?)', (value['group_id'], json.dumps(value, ensure_ascii=False)))
        return self.group(value['group_id'])

    def groups(self):
        with self.lock:
            identifiers = [r[0] for r in self.db.execute('SELECT id FROM conversation_groups ORDER BY rowid DESC')]
        return [self.group(identifier, details=False) for identifier in identifiers]

    def group(self, identifier, *, details=True):
        value = self._get('conversation_groups', identifier)
        with self.lock:
            rows = self.db.execute('SELECT c.payload FROM conversation_group_members m JOIN conversation_cases c ON c.id=m.case_id WHERE m.group_id=? ORDER BY m.rowid', (identifier,)).fetchall()
        cases = [json.loads(r[0]) for r in rows]
        return {**value, 'case_count': len(cases), 'turn_count': sum(len(c['turns']) for c in cases),
                **({'cases': cases} if details else {})}

    def memberships(self, session_id):
        with self.lock:
            rows = self.db.execute('SELECT DISTINCT g.payload FROM conversation_cases c JOIN conversation_group_members m ON m.case_id=c.id JOIN conversation_groups g ON g.id=m.group_id WHERE c.session_id=?', (session_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def capture(self, group_id, body, actor):
        self.group(group_id, details=False)
        session = self.runs.session(body.session_id)
        if not session:
            fail('session_not_found', '未找到原会话。', 404)
        if not 1 <= len(session['turns']) <= 40:
            fail('conversation_case_capacity', '会话用例支持1至40轮；请保留原会话并联系开发者处理更长记录。', 422)
        turns = []
        for turn in session['turns']:
            request = turn.get('request_snapshot') or {}
            if request.get('query') != turn['input']:
                fail('case_request_missing', '这段历史缺少原请求，无法保存可重放的会话用例。', 422)
            options = {k: request[k] for k in ('case_ids', 'case_mode', 'case_skill', 'k') if request.get(k) is not None}
            turns.append({'query': turn['input'], 'options': options, 'attachments': request.get('attachments', []),
                'has_attachments': request.get('has_attachments', False), 'source_run_id': turn['run_id'],
                'file_mode': request.get('file_mode', 'multiple' if request.get('has_attachments') else 'inherit'),
                'baseline_answer': turn.get('answer'), 'baseline_status': turn['status'],
                'baseline_config': turn['config_version'], 'baseline_citations': self.runs.get(turn['run_id']).evidence,
                'attachment_ref': (turn.get('state_before') or {}).get('attachment_ref')})
        # Evidence uses only serializable persisted metadata, never file leases.
        for turn in turns:
            turn['baseline_citations'] = [e.model_dump(mode='json') for e in turn['baseline_citations']]
        seed = session['turns'][0]['request_snapshot'].get('history', [])
        fingerprint = hashlib.sha256(json.dumps([session['session_id'], turns, seed], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with self.lock, self.db:
            row = self.db.execute('SELECT id FROM conversation_cases WHERE fingerprint=?', (fingerprint,)).fetchone()
            if row:
                identifier = row[0]
            else:
                identifier = str(uuid4())
                value = {'case_id': identifier, 'source_session_id': session['session_id'], 'title': body.title.strip() or session['topic'],
                    'expected': body.expected.strip(), 'notes': body.notes.strip(), 'turns': turns, 'seed_history': seed,
                    'created_by': actor, 'created_at': now(), 'revision': 1}
                self.db.execute('INSERT INTO conversation_cases VALUES (?,?,?,?)', (identifier, session['session_id'], fingerprint, json.dumps(value, ensure_ascii=False)))
            self.db.execute('INSERT OR IGNORE INTO conversation_group_members VALUES (?,?)', (group_id, identifier))
        return self.case(identifier)

    def case(self, identifier):
        return self._get('conversation_cases', identifier)

    def update_case(self, identifier, body, actor):
        with self.lock, self.db:
            value = self.case(identifier)
            if value['revision'] != body.expected_revision:
                fail('case_changed', '用例已被更新，请刷新后继续；当前输入请保留。')
            if not body.title.strip():
                fail('case_title_required', '请填写用例标题。', 422)
            value.update(title=body.title.strip(), expected=body.expected.strip(), notes=body.notes.strip(),
                revision=value['revision']+1, updated_by=actor, updated_at=now())
            self._write('conversation_cases', identifier, value)
        return value

    def remove_member(self, group_id, case_id):
        self.group(group_id, details=False)
        with self.lock, self.db:
            self.db.execute('DELETE FROM conversation_group_members WHERE group_id=? AND case_id=?', (group_id, case_id))

    def batches(self):
        with self.lock:
            rows = self.db.execute('SELECT payload FROM conversation_batches ORDER BY rowid DESC LIMIT 100').fetchall()
        return [self.batch_summary(json.loads(r[0])) for r in rows]

    @staticmethod
    def acceptance(value):
        results = value['results']
        if value['status'] != 'completed' or len(results) != len(value['cases']) or any(r['status'] != 'succeeded' for r in results):
            return 'blocked'
        if any(r.get('judgment', {}).get('conclusion') == 'fail' for r in results):
            return 'fail'
        if results and all(r['case']['expected'].strip() and r.get('judgment', {}).get('conclusion') == 'pass' for r in results):
            return 'pass'
        return 'pending'

    def batch_summary(self, value):
        return {k: value.get(k) for k in ('batch_id', 'group_ids', 'group_titles', 'version_name', 'created_at', 'created_by', 'status', 'config_version', 'finished_at')} | {
            'acceptance': self.acceptance(value), 'case_count': len(value['cases']),
            'source_session_ids': list(dict.fromkeys(c['source_session_id'] for c in value['cases'])),
            'completed_cases': sum(r['status'] != 'running' for r in value['results'])}

    def batch(self, identifier):
        value = self._get('conversation_batches', identifier)
        return {**value, **self.batch_summary(value)}

    def versions(self, case_id):
        self.case(case_id)
        with self.lock:
            rows = self.db.execute('SELECT payload FROM conversation_batches ORDER BY rowid DESC').fetchall()
        return [{'batch_id': b['batch_id'], 'version_name': b['version_name'], 'config_version': b['config_version'],
                 'created_at': b['created_at'], 'result': r} for row in rows if (b := json.loads(row[0]))
                for r in b['results'] if r['case']['case_id'] == case_id][:30]

    def start(self, body, actor, runtime, execute, restore, release):
        with self.lock, self.db:
            prior = self.db.execute('SELECT id FROM conversation_batches WHERE actor=? AND submission_id=?', (actor, body.submission_id)).fetchone()
            if prior:
                existing = self.batch(prior[0])
                if existing['group_ids'] != list(dict.fromkeys(body.group_ids)) or existing.get('case_ids', []) != list(dict.fromkeys(body.case_ids)) or existing['version_name'] != body.version_name.strip():
                    fail('batch_submission_conflict', '相同提交编号不能用于不同用例组或版本。')
                return existing
            if self.jobs:
                fail('conversation_batch_busy', '已有一组会话在重跑，请等待完成或取消。', 429)
            groups = [self.group(g) for g in dict.fromkeys(body.group_ids)]
            selected = [self.case(c) for c in dict.fromkeys(body.case_ids)]
            cases = list({c['case_id']: c for c in [*[c for g in groups for c in g['cases']], *selected]}.values())
            if not cases or len(cases) > 100:
                fail('group_case_capacity', '请选择包含1至100段会话的用例组。', 422)
            if not body.version_name.strip():
                fail('batch_version_required', '请填写这次验证的版本名称。', 422)
            value = {'batch_id': str(uuid4()), 'group_ids': [g['group_id'] for g in groups],
                'case_ids': list(dict.fromkeys(body.case_ids)),
                'group_titles': [g['title'] for g in groups] + ['会话：' + c['title'] for c in selected], 'version_name': body.version_name.strip(),
                'created_by': actor, 'created_at': now(), 'status': 'queued', 'cases': cases, 'results': [],
                'config_version': runtime.config_version, 'config_manifest': runtime.config_manifest,
                'prompt_snapshot': runtime.expression_snapshot(), 'judgments': []}
            self.db.execute('INSERT INTO conversation_batches VALUES (?,?,?,?)',
                (value['batch_id'], actor, body.submission_id, json.dumps(value, ensure_ascii=False)))
        task = asyncio.create_task(self._run(value, runtime, execute, restore, release))
        self.jobs[value['batch_id']] = task
        def done(future):
            self.jobs.pop(value['batch_id'], None)
            if future.cancelled() and value['status'] in {'queued', 'running'}:
                value.update(status='cancelled', finished_at=now())
                self._save_batch(value)
            elif not future.cancelled():
                future.exception()
        task.add_done_callback(done)
        return self.batch(value['batch_id'])

    def _save_batch(self, value):
        with self.lock, self.db:
            self._write('conversation_batches', value['batch_id'], value)

    async def _run(self, value, runtime, execute, restore, release):
        value['status'] = 'running'
        self._save_batch(value)
        try:
            for case in value['cases']:
                session_id = 'case_' + uuid4().hex
                result = {'case': case, 'session_id': session_id, 'status': 'running', 'turns': []}
                value['results'].append(result)
                self._save_batch(value)
                history = list(case['seed_history'])
                tokens = {}
                try:
                    for turn in case['turns']:
                        if runtime.config_version != value['config_version']:
                            fail('batch_build_changed', '服务版本变化，本次验证已停止。')
                        selected = []
                        if turn['has_attachments'] and not turn['attachments']:
                            fail('case_attachment_missing', '原附件信息缺失，本会话受阻；未改为无附件提问。', 422)
                        for attachment in turn['attachments']:
                            sha = attachment.get('sha256')
                            key = (sha, attachment['filename'])
                            if key not in tokens:
                                raw = self.runs.attachments.get(sha) if sha else None
                                if raw is None or hashlib.sha256(raw).hexdigest() != sha:
                                    fail('case_attachment_missing', '原附件缺失或指纹不符，本会话受阻。', 422)
                                tokens[key] = await restore(raw, attachment['filename'], session_id)
                            selected.append(tokens[key])
                        files = {'file_id': selected[0]} if turn['file_mode'] == 'single' and len(selected) == 1 else {'file_ids': selected} if selected or turn['file_mode'] == 'multiple' else {}
                        if turn.get('attachment_ref') and not tokens and not selected:
                            fail('case_attachment_context_missing', '会话起点依赖未保存的附件上下文，无法完整重跑。', 422)
                        request = ChatRequest(query=turn['query'], history=history[-12:], session_id=session_id,
                            operator_id=value['created_by'], **files, **turn['options'])
                        run_id = str(uuid4())
                        entry = {'run_id': run_id, 'query': turn['query'], 'status': 'running'}
                        result['turns'].append(entry)
                        self._save_batch(value)
                        response = await execute(request, run_id, value['prompt_snapshot'])
                        trace = runtime.runs.get(run_id)
                        if not trace:
                            fail('case_trace_missing', '运行记录没有保存，不能作为验收依据。')
                        entry.update(status='succeeded', response=response.model_dump(mode='json'),
                            config_version=trace.config_version, latency_ms=trace.latency_ms)
                        if trace.status != 'ok' or trace.config_version != value['config_version']:
                            fail('case_run_invalid', '本轮异常或版本变化，不能作为完整验证结果。')
                        history += [{'role': 'user', 'content': turn['query'][:4000]}, {'role': 'assistant', 'content': response.answer[:4000]}]
                        self._save_batch(value)
                    result['status'] = 'succeeded'
                except asyncio.CancelledError:
                    self._interrupt_result(result)
                    raise
                except Exception as exc:
                    if result['turns'] and result['turns'][-1]['status'] == 'running':
                        result['turns'][-1]['status'] = 'failed'
                    detail = getattr(exc, 'detail', {})
                    result.update(status='blocked' if isinstance(detail, dict) and detail.get('code', '').startswith('case_attachment') else 'failed',
                        error=detail.get('message', '本会话重跑失败，请查看运行记录。') if isinstance(detail, dict) else '本会话重跑失败，请查看运行记录。')
                finally:
                    for token in tokens.values():
                        release(token)
                    self._save_batch(value)
            value['status'] = 'completed'
        except asyncio.CancelledError:
            value['status'] = 'cancelled'
        except Exception:
            value['status'] = 'failed'
        finally:
            value['finished_at'] = now()
            self._save_batch(value)

    def judge(self, batch_id, case_id, body, actor):
        with self.lock, self.db:
            value = self.batch(batch_id)
            if value['status'] != 'completed':
                fail('batch_not_finished', '请等待整组运行结束再验收。')
            result = next((r for r in value['results'] if r['case']['case_id'] == case_id), None)
            if not result or result['status'] != 'succeeded':
                fail('case_not_finished', '本会话没有完整完成，不能确认通过。')
            if body.conclusion == 'pass' and not result['case']['expected'].strip():
                fail('case_expected_required', '本次重跑尚无冻结的预期标准，请补充用例标准后重新验证。', 422)
            if not body.note.strip():
                fail('judgment_note_required', '请填写验收依据。', 422)
            judgment = {**body.model_dump(), 'actor': actor, 'at': now(), 'case_id': case_id}
            result['judgment'] = judgment
            value['judgments'].append(judgment)
            self._write('conversation_batches', batch_id, value)
        return self.batch(batch_id)

    def cancel(self, identifier):
        self.batch(identifier)
        job = self.jobs.get(identifier)
        if job:
            job.cancel()
        return self.batch(identifier)

    def version_events(self):
        with self.lock:
            rows = self.db.execute('SELECT payload FROM conversation_version_events ORDER BY rowid DESC').fetchall()
        return [json.loads(r[0]) for r in rows]

    def confirm(self, identifier, body, actor, runtime):
        with self.lock, self.db:
            batch = self.batch(identifier)
            if batch['acceptance'] != 'pass':
                fail('version_not_accepted', '所有会话均需完整运行并经人工验收通过，才能确认版本。')
            if runtime.config_version != batch['config_version'] or runtime.expression_snapshot() != batch['prompt_snapshot']:
                fail('version_changed', '当前服务或配置已变化，请重跑后再确认版本。')
            if not body.note.strip():
                fail('version_note_required', '请填写版本确认说明。', 422)
            event = {'event_id': str(uuid4()), 'action': 'confirm', 'batch_id': identifier,
                'version_name': batch['version_name'], 'config_version': batch['config_version'],
                'snapshot': batch['prompt_snapshot'], 'judgments': batch['judgments'], 'note': body.note.strip(), 'actor': actor, 'at': now(),
                'scope': 'configuration_confirmation'}
            self.db.execute('INSERT INTO conversation_version_events VALUES (?,?)', (event['event_id'], json.dumps(event, ensure_ascii=False)))
        return event

    def restore(self, identifier, body, actor, runtime):
        from src.storage.prompt_groups import PromptGroups, PromptGroupInput
        with self.lock:
            confirmation = next((e for e in self.version_events() if e['action'] == 'confirm' and e['batch_id'] == identifier), None)
            if not confirmation:
                fail('version_not_confirmed', '此版本尚未由开发者确认，不能作为回退目标。')
            if runtime.config_version != confirmation['config_version']:
                fail('code_rollback_required', '服务代码版本已变化。请通过部署流程回退代码，再恢复对应配置。')
            if self.jobs:
                fail('configuration_in_use', '请等待当前会话重跑结束，再恢复配置。')
            if not body.note.strip():
                fail('version_note_required', '请填写回退说明。', 422)
            snapshot = confirmation['snapshot']
            groups = PromptGroups(self.runs)
            group = groups.save(PromptGroupInput(label='恢复：' + confirmation['version_name'][:80],
                prompt_id=snapshot['communication']['prompt_id'],
                task_prompt_ids={k: p['prompt_id'] for k, p in snapshot['task_prompts'].items()}), actor)
            # Validate values before moving pointers, then commit them together.
            from src.agent.skill_config import ExpressionPreferences
            ExpressionPreferences.model_validate(snapshot['values'])
            before = runtime.expression_snapshot()
            with self.db:
                timestamp = now()
                self.db.execute('UPDATE active_prompt SET prompt_id=?,actor=?,changed_at=? WHERE singleton=1', (snapshot['communication']['prompt_id'], actor, timestamp))
                self.db.execute('INSERT OR REPLACE INTO active_prompt_group VALUES (1,?,?,?)', (group['group_id'], actor, timestamp))
                for scope, prompt in snapshot['task_prompts'].items():
                    self.db.execute('INSERT OR REPLACE INTO active_task_prompts VALUES (?,?)', (scope, prompt['prompt_id']))
                    activation = {'scope': scope, 'old_prompt_id': before['task_prompts'][scope]['prompt_id'], 'new_prompt_id': prompt['prompt_id'], 'group_id': group['group_id'], 'actor': actor, 'created_at': timestamp}
                    self.db.execute('INSERT INTO task_prompt_activations VALUES (?,?)', (str(uuid4()), json.dumps(activation, ensure_ascii=False)))
                revision = before['revision'] + 1
                self.db.execute('INSERT INTO skill_expression_revisions VALUES (?,?,?,?,?,?)', (revision, f'case-expression-v1:{revision}', actor, timestamp, 'restore', json.dumps(snapshot['values'])))
                event = {'event_id': str(uuid4()), 'action': 'restore', 'batch_id': identifier,
                    'version_name': confirmation['version_name'], 'config_version': runtime.config_version,
                    'note': body.note.strip(), 'actor': actor, 'at': now(), 'scope': 'prompt_and_expression',
                    'before': before, 'after': runtime.expression_snapshot()}
                self.db.execute('INSERT INTO conversation_version_events VALUES (?,?)', (event['event_id'], json.dumps(event, ensure_ascii=False)))
        return event

    def sync_issues(self):
        # Import existing conversation marks into the same queue without changing
        # their original review events or losing their source identities.
        with self.lock, self.db:
            rows = self.db.execute('SELECT session_id,issues_json FROM session_review_state').fetchall()
            for session_id, raw in rows:
                for mark in json.loads(raw):
                    key = f"review:{session_id}:{mark['issue_id']}"
                    row = self.db.execute('SELECT id,payload FROM conversation_issues WHERE source_key=?', (key,)).fetchone()
                    if row:
                        value = json.loads(row[1])
                        # Direct review actions are still reflected in the unified queue.
                        prior = value.get('source_status')
                        if prior != mark['status']:
                            value.update(status='closed' if mark['status'] == 'resolved' else 'open',
                                source_status=mark['status'], revision=value['revision']+1)
                            self._write('conversation_issues', row[0], value)
                        continue
                    value = {'issue_id': str(uuid4()), 'session_id': session_id, 'run_id': mark['run_id'],
                        'source': 'conversation', 'source_issue_id': mark['issue_id'], 'source_status': mark['status'],
                        'note': mark['note'], 'status': 'closed' if mark['status'] == 'resolved' else 'open',
                        'category': '其他', 'assignee': '', 'revision': 1, 'created_by': mark['recorded_by'],
                        'created_at': now(), 'history': []}
                    self.db.execute('INSERT INTO conversation_issues VALUES (?,?,?)', (value['issue_id'], key, json.dumps(value, ensure_ascii=False)))

    def issues(self):
        self.sync_issues()
        with self.lock:
            rows = self.db.execute('SELECT payload FROM conversation_issues ORDER BY rowid DESC').fetchall()
        return [self._issue_links(json.loads(r[0])) for r in rows]

    def _issue_links(self, value):
        with self.lock:
            rows = self.db.execute('SELECT payload FROM conversation_cases WHERE session_id=? ORDER BY rowid DESC', (value['session_id'],)).fetchall()
        return {**value, 'cases': [{'case_id': c['case_id'], 'title': c['title']} for row in rows if (c := json.loads(row[0]))],
                'groups': self.memberships(value['session_id'])}

    def issue(self, identifier):
        self.sync_issues()
        return self._issue_links(self._get('conversation_issues', identifier))

    def create_issue(self, body, actor, *, source='conversation', submission_id=None):
        from src.evaluation.session_reviews import SessionReviewInput
        if not body.note.strip():
            fail('issue_note_required', '请填写具体问题。', 422)
        session = self.runs.session(body.session_id)
        if not session or (body.run_id and body.run_id not in [t['run_id'] for t in session['turns']]):
            fail('issue_session_missing', '未找到对应会话回答。', 404)
        action_id = ('feedback_' + hashlib.sha256(f'{actor}:{submission_id}'.encode()).hexdigest()) if submission_id else uuid4().hex
        # SessionReviews provides durable idempotency and optimistic concurrency.
        review = SessionReviewInput(action_id=action_id, expected_revision=session['review_revision'],
            action='issue', run_id=body.run_id or session['turns'][-1]['run_id'], note=body.note)
        if submission_id:
            with self.lock:
                old = self.db.execute('SELECT payload FROM session_review_events WHERE session_id=? AND action_id=?', (session['session_id'], action_id)).fetchone()
            if old:
                original = json.loads(old[0])['input']
                review.expected_revision = original['expected_revision']
        self.runs.reviews.apply(session['session_id'], review, actor)
        self.sync_issues()
        with self.lock, self.db:
            row = self.db.execute('SELECT id,payload FROM conversation_issues WHERE source_key=?', (f"review:{session['session_id']}:{action_id}",)).fetchone()
            value = json.loads(row[1])
            value['source'] = source
            self._write('conversation_issues', row[0], value)
        return self.issue(row[0])

    def update_issue(self, identifier, body, actor):
        from src.evaluation.session_reviews import SessionReviewInput
        value = self.issue(identifier)
        if value['revision'] != body.expected_revision:
            fail('issue_changed', '问题已被更新，请刷新后继续。')
        if not body.note.strip():
            fail('issue_note_required', '请填写处理说明。', 422)
        if body.status == 'closed':
            if not body.verification_batch_id:
                fail('issue_verification_required', '请选择此会话已经人工验收通过的重跑记录。', 422)
            batch = self.batch(body.verification_batch_id)
            matching = [r for r in batch['results'] if r['case']['source_session_id'] == value['session_id']]
            if batch['status'] != 'completed' or not any(r['status'] == 'succeeded' and r.get('judgment', {}).get('conclusion') == 'pass' for r in matching):
                fail('issue_verification_invalid', '所选记录没有此会话的人工验收通过结果。', 422)
        # Serialize with review actions; apply owns its transaction.
        with self.lock:
            current = self._get('conversation_issues', identifier)
            if current['revision'] != body.expected_revision:
                fail('issue_changed', '问题已被更新，请刷新后继续。')
            session = self.runs.session(value['session_id'])
            mark = next(m for m in session['review']['issues'] if m['issue_id'] == value['source_issue_id'])
            target = 'resolved' if body.status == 'closed' else 'open'
            if target != mark['status']:
                self.runs.reviews.apply(value['session_id'], SessionReviewInput(action_id=uuid4().hex,
                    expected_revision=session['review_revision'], action='resolve' if target == 'resolved' else 'reopen',
                    issue_id=mark['issue_id'], note=body.note), actor)
            current.update(status=body.status, category=body.category.strip() or '其他', assignee=body.assignee.strip(),
                source_status=target, revision=current['revision']+1, verification_batch_id=body.verification_batch_id)
            current['history'].append({'actor': actor, 'at': now(), 'status': body.status, 'note': body.note.strip(),
                'verification_batch_id': body.verification_batch_id})
            with self.db:
                self._write('conversation_issues', identifier, current)
        return self.issue(identifier)

    async def shutdown(self):
        jobs = list(self.jobs.values())
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
