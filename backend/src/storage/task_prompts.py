"""Immutable task-scoped versions with explicit activation and audit history."""
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from src.agent.task_prompts import DEFAULT_TASKS, TaskPromptInput
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class TaskPrompts:
    def __init__(self, db, lock):
        self.db, self.lock = db, lock
        with lock, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS task_prompt_versions (prompt_id TEXT PRIMARY KEY, scope TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS active_task_prompts (scope TEXT PRIMARY KEY, prompt_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_prompt_activations (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            ''')
            for scope, text in DEFAULT_TASKS.items():
                identifier = 'builtin-' + scope + '-v1'
                row = self._snapshot(TaskPromptInput(scope=scope, label=scope + ' 默认任务 v1', text=text), 'builtin', identifier)
                db.execute('INSERT OR IGNORE INTO task_prompt_versions VALUES (?,?,?)', (identifier, scope, json.dumps(row, ensure_ascii=False)))
                db.execute('INSERT OR IGNORE INTO active_task_prompts VALUES (?,?)', (scope, identifier))

    @staticmethod
    def _snapshot(body, actor, identifier):
        value = body.model_dump(mode='json')
        digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return {**value, 'prompt_id': identifier, 'version': 'task-' + digest[:16], 'sha256': digest, 'actor': actor, 'created_at': now()}

    def list(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM task_prompt_versions ORDER BY rowid DESC')]

    def get(self, identifier):
        with self.lock:
            row = self.db.execute('SELECT payload FROM task_prompt_versions WHERE prompt_id=?', (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, detail={'code': 'task_prompt_not_found', 'message': '未找到任务 Prompt 版本。'})
        return json.loads(row[0])

    def save(self, body, actor):
        value = self._snapshot(body, actor, str(uuid4()))
        with self.lock, self.db:
            self.db.execute('INSERT INTO task_prompt_versions VALUES (?,?,?)', (value['prompt_id'], value['scope'], json.dumps(value, ensure_ascii=False)))
        return value

    def active(self):
        with self.lock:
            return {scope: json.loads(payload) for scope, payload in self.db.execute('SELECT a.scope,v.payload FROM active_task_prompts a JOIN task_prompt_versions v ON a.prompt_id=v.prompt_id')}

    def activate(self, scope, identifier, actor):
        value = self.get(identifier)
        if value['scope'] != scope:
            raise HTTPException(422, detail={'code': 'task_prompt_scope_mismatch', 'message': '候选与所选任务范围不一致。'})
        with self.lock, self.db:
            old = self.db.execute('SELECT prompt_id FROM active_task_prompts WHERE scope=?', (scope,)).fetchone()
            event = {'scope': scope, 'old_prompt_id': old[0] if old else None, 'new_prompt_id': identifier, 'actor': actor, 'created_at': now()}
            self.db.execute('INSERT OR REPLACE INTO active_task_prompts VALUES (?,?)', (scope, identifier))
            self.db.execute('INSERT INTO task_prompt_activations VALUES (?,?)', (str(uuid4()), json.dumps(event, ensure_ascii=False)))
        return value
