"""Versioned reuse metadata and a non-destructive first-batch import plan."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.agent.starred_match import question_key

BATCH = 'professional-sq-2026-11'
SOURCE = Path(__file__).resolve().parents[3] / 'docs/iterations/2026-11-11-retrieval-skills-v02/source/星标问题录入整理'


class StarredReuse(BaseModel):
    reuse_status: Literal['unknown','reference','partial','pending','conflict'] = 'unknown'
    coverage_scope: str = Field(default='',max_length=10000)
    excluded_scope: str = Field(default='',max_length=10000)
    source_refs: list[str] = Field(default_factory=list,max_length=30)
    variants: list[str] = Field(default_factory=list,max_length=30)
    original_question: str = Field(default='',max_length=20000)
    profile: Literal['general','scale_models','project_plan','whcns_intro'] = 'general'
    notes: str = Field(default='',max_length=10000)
    professional_review: Literal['unknown'] = 'unknown'


def first_batch(source=SOURCE):
    ledger=json.loads((source/'25条专业星标_整理台账.json').read_text())
    ready={row['source_sq_id']:row for row in json.loads((source/'首批9条_题目答案候选.json').read_text())}
    if len(ledger['records'])!=25 or len(ready)!=9: raise ValueError('Unexpected first batch counts')
    records=[]
    for row in ledger['records']:
        sq=row['source_sq_id']
        prepared=ready.get(sq,{})
        answer=prepared.get('answer','')
        if answer!=row['answer']: raise ValueError('Ledger and prepared answer differ: '+sq)
        status='reference' if answer else 'conflict' if sq=='SQ-027' else 'pending'
        profile='scale_models' if sq=='SQ-024' else 'whcns_intro' if sq=='SQ-026' else 'project_plan' if answer else 'general'
        refs=[row['source']]+['；'.join(str(value.get(key,'')) for key in ('title','location','url','doi') if value.get(key)) if isinstance(value,dict) else value for value in prepared.get('external_sources',[])]
        reuse=StarredReuse(reuse_status=status,coverage_scope=row['coverage'],excluded_scope=row['excluded'],
            source_refs=refs,variants=prepared.get('variants',[]),original_question=row['original_question'],
            profile=profile,notes=row.get('reason') or row.get('edit','')).model_dump()
        records.append({'source_sq_id':sq,'question':row['question'],'answer':answer,'reuse':reuse})
    if len({r['source_sq_id'] for r in records})!=25 or sum(bool(r['answer']) for r in records)!=9:
        raise ValueError('Invalid first batch')
    return records


def import_plan(store, records):
    existing=store.starred_questions()
    with store.lock:
        bindings={row[0]:row[1] for row in store.db.execute('SELECT source_sq_id,question_id FROM eval_starred_sources WHERE batch=?',(BATCH,))}
    by_id={row['question_id']:row for row in existing}
    output=[]
    for record in records:
        bound=bindings.get(record['source_sq_id'])
        matches=[row for row in existing if question_key(row['question'])==question_key(record['question'])]
        action='preserve' if bound and bound in by_id else 'bind_existing' if len(matches)==1 and matches[0]['answer']==record['answer'] else 'conflict' if matches or bound else 'create'
        output.append({'source_sq_id':record['source_sq_id'],'action':action,
            'question_id':bound or (matches[0]['question_id'] if len(matches)==1 else None),
            'question':record['question'],'has_answer':bool(record['answer'])})
    return {'batch':BATCH,'existing_count':len(existing),'records':output,'conflicts':[r for r in output if r['action']=='conflict']}


def import_first_batch(store, records, *, apply=False):
    """Lock and plan again inside one transaction; existing answers never get overwritten."""
    planned=import_plan(store,records)
    if not apply or planned['conflicts']: return planned | {'applied':False}
    # Store owns an ordinary Lock, so the transactional implementation uses its
    # private row helpers rather than recursively acquiring public method locks.
    from src.evaluation.store import now
    from uuid import uuid4
    with store.lock,store.db:
        store.db.execute('BEGIN IMMEDIATE')
        existing=store._starred_rows()
        bound={r[0]:r[1] for r in store.db.execute('SELECT source_sq_id,question_id FROM eval_starred_sources WHERE batch=?',(BATCH,))}
        applied=[]
        for record in records:
            sq=record['source_sq_id']
            if sq in bound:
                if not any(row['question_id']==bound[sq] for row in existing): raise ValueError('Source binding has no record')
                applied.append({'source_sq_id':sq,'question_id':bound[sq],'action':'preserve'})
                continue
            matches=[row for row in existing if question_key(row['question'])==question_key(record['question'])]
            if len(matches)>1 or matches and matches[0]['answer']!=record['answer']: raise ValueError('Concurrent import conflict: '+sq)
            if matches:
                identifier=matches[0]['question_id']
                # Metadata is answer-affecting and receives its own CAS revision.
                if matches[0].get('reuse') and matches[0]['reuse']!=record['reuse']: raise ValueError('Existing reuse scope differs: '+sq)
                store.db.execute('UPDATE eval_starred_questions SET reuse_json=?,revision=revision+1,updated_at=? WHERE question_id=?',
                    (json.dumps(record['reuse'],ensure_ascii=False),now(),identifier))
                action='bind_existing'
            else:
                identifier=str(uuid4()); stamp=now()
                store.db.execute('INSERT INTO eval_starred_questions (question_id,question,answer,created_at,updated_at,revision,reuse_json) VALUES (?,?,?,?,?,1,?)',
                    (identifier,record['question'],record['answer'],stamp,stamp,json.dumps(record['reuse'],ensure_ascii=False)))
                action='create'
            digest=hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            store.db.execute('INSERT INTO eval_starred_sources VALUES (?,?,?,?)',(BATCH,sq,identifier,digest))
            applied.append({'source_sq_id':sq,'question_id':identifier,'action':action})
    return planned | {'applied':True,'records':applied}
