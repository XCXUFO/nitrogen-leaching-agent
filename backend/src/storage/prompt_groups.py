"""Immutable, complete sets of communication and task prompt versions."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, field_validator

from src.agent.contracts import Contract
from src.agent.task_prompts import DEFAULT_TASKS, TaskScope


class PromptGroupInput(Contract):
    label: str = Field(min_length=1, max_length=100)
    prompt_id: str = Field(min_length=1, max_length=100)
    task_prompt_ids: dict[TaskScope, str] = Field(min_length=3, max_length=3)

    @field_validator('label')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请填写 Prompt 组名称。')
        return value.strip()


class PromptGroups:
    def __init__(self, runs):
        self.runs = runs
        self.db, self.lock = runs._connection, runs._lock
        with self.lock, self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS prompt_groups (group_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            self.db.execute('''CREATE TABLE IF NOT EXISTS active_prompt_group (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), group_id TEXT NOT NULL,
                actor TEXT NOT NULL, changed_at TEXT NOT NULL)''')
            empty = not self.db.execute('SELECT 1 FROM prompt_groups LIMIT 1').fetchone()
        if empty:
            self.save(PromptGroupInput(label='初始生效版本组', prompt_id=runs.prompts.active()['prompt_id'],
                task_prompt_ids={scope: p['prompt_id'] for scope, p in runs.task_prompts.active().items()}), 'builtin')

    def list(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM prompt_groups ORDER BY rowid DESC')]

    def get(self, identifier):
        with self.lock:
            row = self.db.execute('SELECT payload FROM prompt_groups WHERE group_id=?', (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, detail={'code': 'prompt_group_not_found', 'message': '未找到此 Prompt 组。'})
        return json.loads(row[0])

    def active(self):
        with self.lock:
            current = self.runs.active_prompt_snapshot()
            row = self.db.execute('SELECT group_id,actor,changed_at FROM active_prompt_group WHERE singleton=1').fetchone()
            groups = self.list()
            if row:
                groups.sort(key=lambda g: g['group_id'] != row[0])
            group = next((g for g in groups if
                g['communication']['prompt_id'] == current['communication']['prompt_id'] and
                all(g['task_prompts'][s]['prompt_id'] == current['task_prompts'][s]['prompt_id'] for s in DEFAULT_TASKS)), None)
            return {**current, 'group': group,
                    'activated_by': row[1] if row and group and row[0] == group['group_id'] else None,
                    'activated_at': row[2] if row and group and row[0] == group['group_id'] else None}

    def activate(self, identifier, actor):
        group = self.get(identifier)
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock, self.db:
            # Validate every version before moving any of the active pointers.
            if not self.db.execute('SELECT 1 FROM prompt_versions WHERE prompt_id=?',
                                   (group['communication']['prompt_id'],)).fetchone():
                raise HTTPException(404, detail={'code': 'prompt_not_found', 'message': '未找到组内全局表达版本。'})
            for scope in DEFAULT_TASKS:
                candidate = self.runs.task_prompts.get(group['task_prompts'][scope]['prompt_id'])
                if candidate['scope'] != scope:
                    raise HTTPException(422, detail={'code': 'task_prompt_scope_mismatch', 'message': '组内任务版本与任务范围不一致。'})
            self.db.execute('UPDATE active_prompt SET prompt_id=?,actor=?,changed_at=? WHERE singleton=1',
                            (group['communication']['prompt_id'], actor, timestamp))
            for scope in DEFAULT_TASKS:
                prompt_id = group['task_prompts'][scope]['prompt_id']
                old = self.db.execute('SELECT prompt_id FROM active_task_prompts WHERE scope=?', (scope,)).fetchone()
                event = {'scope': scope, 'old_prompt_id': old[0] if old else None, 'new_prompt_id': prompt_id,
                         'group_id': identifier, 'actor': actor, 'created_at': timestamp}
                self.db.execute('INSERT OR REPLACE INTO active_task_prompts VALUES (?,?)', (scope, prompt_id))
                self.db.execute('INSERT INTO task_prompt_activations VALUES (?,?)',
                                (str(uuid4()), json.dumps(event, ensure_ascii=False)))
            self.db.execute('INSERT OR REPLACE INTO active_prompt_group VALUES (1,?,?,?)', (identifier, actor, timestamp))
        return self.active()

    def save(self, body, actor):
        communication = next((p for p in self.runs.prompts.list() if p['prompt_id'] == body.prompt_id), None)
        if communication is None:
            raise HTTPException(404, detail={'code': 'prompt_not_found', 'message': '未找到全局表达版本。'})
        tasks = {}
        for scope in DEFAULT_TASKS:
            candidate = self.runs.task_prompts.get(body.task_prompt_ids[scope])
            if candidate['scope'] != scope:
                raise HTTPException(422, detail={'code': 'task_prompt_scope_mismatch', 'message': '任务版本与任务范围不一致。'})
            tasks[scope] = candidate
        snapshot = {'label': body.label, 'communication': communication, 'task_prompts': tasks}
        digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        value = {**snapshot, 'group_id': str(uuid4()), 'version': 'group-' + digest[:16], 'sha256': digest,
                 'actor': actor, 'created_at': datetime.now(timezone.utc).isoformat()}
        with self.lock, self.db:
            self.db.execute('INSERT INTO prompt_groups VALUES (?,?)', (value['group_id'], json.dumps(value, ensure_ascii=False)))
        return value
