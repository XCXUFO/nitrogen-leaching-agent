"""SQLite postings and FTS over only changed materials; live eligibility stays authoritative."""
from __future__ import annotations

import json
import re
import time
import unicodedata
from contextlib import contextmanager

from src.agent.understanding import terms
from src.rag.reference_filter import is_reference_chunk

VERSION = 'local-postings-v2'


@contextmanager
def atomic(db):
    db.execute('SAVEPOINT retrieval_schema')
    try:
        yield
        db.execute('RELEASE retrieval_schema')
    except BaseException:
        db.execute('ROLLBACK TO retrieval_schema')
        db.execute('RELEASE retrieval_schema')
        raise


class Records(list):
    def __init__(self, items=(), diagnostics=None):
        super().__init__(items)
        self.diagnostics = diagnostics or {}


def fuse(routes, key=lambda item: item.chunk_id):
    """Reciprocal ranks, never add BM25, cosine and term scores directly."""
    scores, values, origins = {}, {}, {}
    for name, items in routes.items():
        seen = set()
        for rank, item in enumerate(items, 1):
            identifier = key(item)
            if identifier in seen: continue
            seen.add(identifier)
            scores[identifier] = scores.get(identifier, 0) + 1 / (60 + rank)
            values.setdefault(identifier, item)
            origins.setdefault(identifier, []).append({'route': name, 'rank': rank})
    order = sorted(values, key=lambda identifier: (-scores[identifier], str(identifier)))
    return [(values[identifier], scores[identifier], origins[identifier]) for identifier in order]


def retrieval_requests(query, understanding=None):
    understanding=understanding or {}
    tasks=understanding.get('subtasks',[])
    if understanding.get('semantic',{}).get('status')=='applied' and tasks:
        query='；'.join(task.get('retrieval_query') or task['query'] for task in tasks)
    excluded=[item for item in understanding.get('concepts',[]) if item.get('polarity')=='exclude' or item.get('replaced')]
    if excluded:
        query=''.join(unicodedata.normalize('NFKC',char) if char.isalnum() else char for char in query)
    for item in understanding.get('concepts',[]):
        if item.get('polarity')=='exclude' or item.get('replaced'):
            for value in (item['original'],item['canonical']): query=re.sub(re.escape(value),'',query,flags=re.I)
    groups={}
    common=[]
    for condition in understanding.get('conditions',[]):
        if condition.get('negated'): continue
        group=condition.get('object_group','subject')
        (common if group=='subject' else groups.setdefault(group,[])).append(condition['value'])
    requests={'full_text':query, **{f'object:{key}':' '.join(common+values) for key,values in list(groups.items())[:8]}}
    for task in (tasks[:8] if len(tasks)>1 else []):
        if task.get('intent') in {'file_calculation','capability'}: continue
        text=task.get('retrieval_query') or task['query']
        if excluded:
            text=''.join(unicodedata.normalize('NFKC',char) if char.isalnum() else char for char in text)
        for item in understanding.get('concepts',[]):
            if item.get('polarity')=='exclude' or item.get('replaced'):
                for value in (item['original'],item['canonical']): text=re.sub(re.escape(value),'',text,flags=re.I)
        if text and text not in requests.values(): requests['subtask:'+task['subtask_id']]=text
    return requests


class LocalIndex:
    def __init__(self, owner, kind):
        self.owner, self.db, self.kind = owner, owner.db, kind
        self.prefix = p = 'local_' + kind
        self.source = 'papers' if kind == 'literature' else 'reference_cases'
        with owner.lock, atomic(self.db):
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {p}_dirty (id TEXT PRIMARY KEY)')
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {p}_state (id TEXT PRIMARY KEY, version TEXT NOT NULL)')
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {p}_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {p}_stats (id TEXT PRIMARY KEY, reference_chunks INTEGER NOT NULL, indexed_chunks INTEGER NOT NULL DEFAULT 0)')
            if 'indexed_chunks' not in {r[1] for r in self.db.execute(f'PRAGMA table_info({p}_stats)')}:
                self.db.execute(f'ALTER TABLE {p}_stats ADD COLUMN indexed_chunks INTEGER NOT NULL DEFAULT 0')
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {p}_members (tag_id TEXT, id TEXT, PRIMARY KEY(tag_id,id))')
            self.db.execute(f'CREATE INDEX IF NOT EXISTS {p}_members_id ON {p}_members(id)')
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {p}_chunks (row_id INTEGER PRIMARY KEY, material_id TEXT NOT NULL)')
            self.db.execute(f'CREATE INDEX IF NOT EXISTS {p}_chunks_material ON {p}_chunks(material_id)')
            self.db.execute(f'''CREATE VIRTUAL TABLE IF NOT EXISTS {p}_fts USING fts5(
                material_id UNINDEXED, position UNINDEXED, version UNINDEXED,
                title_terms, body_terms, text UNINDEXED, char_start UNINDEXED, char_end UNINDEXED)''')
            existed = self.db.execute(f"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='{p}_insert'").fetchone()
            for event, ref in [('INSERT', 'new'), ('UPDATE', 'new'), ('DELETE', 'old')]:
                self.db.execute(f'DROP TRIGGER IF EXISTS {p}_{event.lower()}')
                self.db.execute(f'''CREATE TRIGGER {p}_{event.lower()} AFTER {event} ON {self.source}
                    BEGIN INSERT INTO {p}_dirty SELECT {ref}.id WHERE NOT EXISTS (SELECT 1 FROM {p}_dirty WHERE id={ref}.id); END''')
            self.db.execute(f'DROP TRIGGER IF EXISTS {p}_old_id')
            self.db.execute(f'''CREATE TRIGGER {p}_old_id AFTER UPDATE OF id ON {self.source}
                BEGIN INSERT INTO {p}_dirty SELECT old.id WHERE NOT EXISTS (SELECT 1 FROM {p}_dirty WHERE id=old.id); END''')
            if kind == 'literature':
                for table in ['paper_tags', 'literature_search_sync']:
                    for event, ref in [('INSERT', 'new'), ('UPDATE', 'new'), ('DELETE', 'old')]:
                        self.db.execute(f'DROP TRIGGER IF EXISTS {p}_{table}_{event.lower()}')
                        self.db.execute(f'''CREATE TRIGGER {p}_{table}_{event.lower()} AFTER {event} ON {table}
                            BEGIN INSERT INTO {p}_dirty SELECT {ref}.paper_id WHERE NOT EXISTS (SELECT 1 FROM {p}_dirty WHERE id={ref}.paper_id); END''')
            version = self.db.execute(f"SELECT value FROM {p}_meta WHERE key='version'").fetchone()
            if not existed or not version or version[0] != VERSION:
                self.db.execute(f'INSERT OR IGNORE INTO {p}_dirty SELECT id FROM {self.source}')
                self.db.execute(f'INSERT OR IGNORE INTO {p}_dirty SELECT id FROM {p}_state')

    def _read(self, identifier):
        if self.kind == 'case':
            row = self.db.execute('SELECT * FROM reference_cases WHERE id=? AND enabled=1 AND deleted=0', (identifier,)).fetchone()
            if row is None: return None
            item = dict(row)
            text = '\n'.join(item[k] for k in ('body', 'explanation', 'supplementary', 'source'))
            return str(item['revision']), item['title'], json.loads(item['tag_ids']), [{'text': text, 'char_start': 0, 'char_end': len(text)}]
        row = self.db.execute('''SELECT p.*,s.content_key,s.chunks_json FROM papers p
            JOIN literature_search_sync s ON s.paper_id=p.id WHERE p.id=? AND p.deleted=0 AND p.usage='normal' AND s.status='ready' ''', (identifier,)).fetchone()
        if row is None: return None
        paper = self.owner.paper(row)
        if self.owner.search_index.content_key(paper) != row['content_key']: return None
        return row['content_key'], paper['title'], paper['tag_ids'], json.loads(row['chunks_json'] or '[]')

    def ensure(self, rebuild=False):
        p = self.prefix
        # Savepoints also work when an existing library mutation owns the transaction.
        with self.owner.lock:
            self.db.execute('SAVEPOINT local_retrieval_build')
            try:
                version_row=self.db.execute(f"SELECT value FROM {p}_meta WHERE key='version'").fetchone()
                if rebuild or not version_row or version_row[0]!=VERSION:
                    self.db.execute(f'INSERT OR IGNORE INTO {p}_dirty SELECT id FROM {self.source}')
                    self.db.execute(f'INSERT OR IGNORE INTO {p}_dirty SELECT id FROM {p}_state')
                    self.db.execute(f'DELETE FROM {p}_fts')
                    self.db.execute(f'DELETE FROM {p}_chunks')
                dirty = [r[0] for r in self.db.execute(f'SELECT id FROM {p}_dirty')]
                for identifier in dirty:
                    self.db.execute(f'DELETE FROM {p}_fts WHERE rowid IN (SELECT row_id FROM {p}_chunks WHERE material_id=?)', (identifier,))
                    self.db.execute(f'DELETE FROM {p}_chunks WHERE material_id=?', (identifier,))
                    self.db.execute(f'DELETE FROM {p}_members WHERE id=?', (identifier,))
                    self.db.execute(f'DELETE FROM {p}_state WHERE id=?', (identifier,))
                    self.db.execute(f'DELETE FROM {p}_stats WHERE id=?', (identifier,))
                    material = self._read(identifier)
                    if material is None: continue
                    version, title, tags, chunks = material
                    title_terms = ' '.join(sorted(terms(title)))
                    valid = [(i,c) for i,c in enumerate(chunks) if self.kind=='case' or not is_reference_chunk(c['text'])]
                    for i,c in valid:
                        cursor=self.db.execute(f'INSERT INTO {p}_fts VALUES (?,?,?,?,?,?,?,?)',
                            (identifier,i,version,title_terms,' '.join(sorted(terms(c['text']))),c['text'],c['char_start'],c['char_end']))
                        self.db.execute(f'INSERT INTO {p}_chunks VALUES (?,?)',(cursor.lastrowid,identifier))
                    self.db.execute(f'INSERT INTO {p}_stats VALUES (?,?,?)', (identifier,len(chunks)-len(valid),len(valid)))
                    self.db.executemany(f'INSERT OR IGNORE INTO {p}_members VALUES (?,?)', [(t,identifier) for t in tags])
                    self.db.execute(f'INSERT INTO {p}_state VALUES (?,?)', (identifier,version))
                self.db.execute(f'DELETE FROM {p}_dirty')
                self.db.execute(f"INSERT OR REPLACE INTO {p}_meta VALUES ('version',?)", (VERSION,))
                self.db.execute('RELEASE local_retrieval_build')
                return len(dirty)
            except BaseException:
                self.db.execute('ROLLBACK TO local_retrieval_build')
                self.db.execute('RELEASE local_retrieval_build')
                raise

    def candidates(self, query, mapping=None, budget=160, understanding=None, material_ids=None):
        started = time.perf_counter()
        updated = self.ensure()
        p = self.prefix
        requests = retrieval_requests(query, understanding)
        scope_sql = ' AND material_id IN (SELECT value FROM json_each(?))' if material_ids is not None else ''
        scope_args = [json.dumps(sorted(material_ids))] if material_ids is not None else []
        with self.owner.lock:
            count = self.db.execute(f'SELECT count(*) FROM {p}_state').fetchone()[0]
            excluded, chunk_count = self.db.execute(f'SELECT coalesce(sum(reference_chunks),0),coalesce(sum(indexed_chunks),0) FROM {p}_stats').fetchone()
            routes = {}
            for name, text in requests.items():
                query_terms=sorted(terms(text))[:64]
                expression=' OR '.join('"'+word.replace('"','""')+'"' for word in query_terms)
                routes[name]=list(self.db.execute(f'''SELECT * FROM {p}_fts WHERE {p}_fts MATCH ? {scope_sql}
                    ORDER BY bm25({p}_fts,0,0,0,1,2) LIMIT ?''', [expression,*scope_args,budget])) if expression else []
            tags = set()
            for item in (mapping or {}).get('mappings', []):
                if item.get('polarity') == 'exclude': continue
                for candidate in item['candidates']:
                    tags.update(candidate.get('descendant_ids', [candidate['id']]))
            tagged = list(self.db.execute(f'''SELECT * FROM {p}_fts WHERE rowid IN
                (SELECT DISTINCT c.row_id FROM {p}_chunks c JOIN {p}_members m ON c.material_id=m.id
                 WHERE m.tag_id IN ({','.join('?' for _ in tags)})) {scope_sql} ORDER BY rowid LIMIT ?''', [*sorted(tags), *scope_args, budget])) if tags else []
            # Small corpora and generic case discovery stay exhaustive within budget.
            expand=self.kind=='case' and (count<=budget or not any(routes.values()) and not tags)
            expanded = list(self.db.execute(f'SELECT * FROM {p}_fts WHERE 1=1 {scope_sql} ORDER BY rowid LIMIT ?', [*scope_args,budget])) if expand else []
        routes.update(tag=tagged, bounded_expansion=expanded)
        merged = fuse(routes, key=lambda r: (r['material_id'], r['version'], r['position']))[:budget]
        rows = [dict(item) | {'fusion_score': score, 'recall_paths': paths} for item, score, paths in merged]
        return rows, {'version': VERSION, 'status': 'ready', 'material_count': count, 'rebuilt_materials': updated,
            'candidate_count': len(rows), 'candidate_budget': budget, 'coverage': 'bounded' if chunk_count > budget else 'within_budget',
            'chunk_count':chunk_count, 'excluded_reference_chunks':excluded,
            'routes': {name:len(items) for name,items in routes.items()}, 'elapsed_ms': round((time.perf_counter()-started)*1000,3)}
