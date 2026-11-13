"""Sync the supplied server taxonomy into local databases, with backups and a receipt."""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
REDIRECTS = {
    'T-067d23c4868a': 'T-74ce41cce69c',  # Deprecated maize -> current maize.
    'T-0d6db06e5bda': 'T-068675c101f2',  # Deprecated Guangxi -> current Guangxi.
}


def synchronize(db, snapshot, *, actor='local-taxonomy-sync'):
    """Caller owns the transaction; the case database is attached as tag_cases."""
    tags = {t['id']: dict(t) for t in snapshot['tags']}
    if len(tags) != len(snapshot['tags']):
        raise ValueError('Snapshot contains duplicate tag IDs.')
    deprecated = {t['id'] for t in tags.values() if t['name'] == '已废弃'}
    if deprecated != set(REDIRECTS):
        raise ValueError('Deprecated tags differ from the two reviewed IDs.')
    for old, new in REDIRECTS.items():
        if new not in tags or not tags[new]['effective_enabled'] or tags[old]['dimension_key'] != tags[new]['dimension_key']:
            raise ValueError('A deprecated tag has no valid replacement.')
    target = {k: v for k, v in tags.items() if k not in deprecated}
    reparented = []
    for tag in target.values():
        if tag['parent_id'] in REDIRECTS:
            old_parent = tag['parent_id']
            tag['parent_id'] = REDIRECTS[old_parent]
            reparented.append({'id': tag['id'], 'name': tag['name'], 'before_parent_id': old_parent, 'parent_id': tag['parent_id']})
        seen, node = {tag['id']}, tag
        while node['parent_id']:
            parent = target.get(node['parent_id'])
            if parent is None or parent['id'] in seen or parent['dimension_key'] != tag['dimension_key']:
                raise ValueError('Snapshot contains an invalid tag hierarchy.')
            seen.add(parent['id'])
            node = parent
    dimensions = snapshot['dimensions']
    dimension_keys = {d['key'] for d in dimensions}
    if len(dimension_keys) != len(dimensions) or len({d['name'] for d in dimensions}) != len(dimensions):
        raise ValueError('Snapshot contains duplicate dimensions.')
    if any(t['dimension_key'] not in dimension_keys for t in target.values()):
        raise ValueError('Snapshot contains an unknown dimension.')
    existing = {r['id']: dict(r) for r in db.execute('SELECT * FROM tags')}
    extras = set(existing) - set(tags)
    if extras:
        raise ValueError('Local-only tags require review: ' + ', '.join(sorted(extras)))
    old_dimensions = {r['name']: dict(r) for r in db.execute('SELECT * FROM dimensions')}
    if set(old_dimensions) - {d['name'] for d in dimensions}:
        raise ValueError('Local-only dimensions require review.')
    at = datetime.now(timezone.utc).isoformat()
    reason = '同步2026-11-11服务器标签快照，归并并移除两个已废弃标签。'

    def audit(entity, identifier, action, before, after):
        summary = {'create': '同步新增', 'edit': '同步更新', 'delete': '归并并删除废弃标签'}[action]
        db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)', (uuid4().hex, entity, identifier, action, actor, at,
            json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), reason, summary))

    changed = False
    mapping = {}
    for index, dimension in enumerate(dimensions):
        before = old_dimensions.get(dimension['name'])
        identifier = before['id'] if before else 'D-' + hashlib.sha256(('snapshot-dimension:' + dimension['key']).encode()).hexdigest()[:12]
        mapping[dimension['key']] = identifier
        values = dict(name=dimension['name'], description=dimension.get('description', ''), selection=dimension['selection'],
            required=int(dimension['required']), enabled=int(dimension['enabled']), sort_order=index)
        if not before:
            db.execute('INSERT INTO dimensions VALUES (?,?,?,?,?,?,?,?,?)', (identifier, *values.values(), at, at))
        elif any(before[key] != value for key, value in values.items()):
            db.execute('UPDATE dimensions SET name=?,description=?,selection=?,required=?,enabled=?,sort_order=?,updated_at=? WHERE id=?',
                (*values.values(), at, identifier))
        else:
            continue
        changed = True
        audit('dimension', identifier, 'edit' if before else 'create', before, values)

    # Insert ancestors first, independent of the order of rows in the source file.
    pending = dict(target)
    written = set()
    while pending:
        ready = [t for t in pending.values() if not t['parent_id'] or t['parent_id'] in written]
        if not ready:
            raise ValueError('Unable to order tag ancestors.')
        for tag in ready:
            identifier = tag['id']
            before = existing.get(identifier)
            values = dict(dimension_id=mapping[tag['dimension_key']], parent_id=tag['parent_id'], name=tag['name'],
                description=tag.get('description', ''), enabled=int(tag['enabled']), sort_order=tag['display_index'])
            if not before:
                db.execute('INSERT INTO tags VALUES (?,?,?,?,?,?,?,?,?)', (identifier, *values.values(), at, at))
            elif any(before[key] != value for key, value in values.items()):
                db.execute('UPDATE tags SET dimension_id=?,parent_id=?,name=?,description=?,enabled=?,sort_order=?,updated_at=? WHERE id=?',
                    (*values.values(), at, identifier))
            else:
                written.add(identifier)
                del pending[identifier]
                continue
            changed = True
            audit('tag', identifier, 'edit' if before else 'create', before, values)
            written.add(identifier)
            del pending[identifier]

    def normalize(identifiers):
        mapped = list(dict.fromkeys(REDIRECTS.get(i, i) for i in identifiers))
        if set(mapped) - set(target):
            raise ValueError('An asset references an unknown tag.')
        ancestors = set()
        for identifier in mapped:
            parent = target[identifier]['parent_id']
            while parent:
                ancestors.add(parent)
                parent = target[parent]['parent_id']
        return [i for i in mapped if i not in ancestors]

    migrated_papers, migrated_cases = [], []
    for paper in db.execute('SELECT id,data FROM papers').fetchall():
        before = [r[0] for r in db.execute('SELECT tag_id FROM paper_tags WHERE paper_id=? ORDER BY tag_id', (paper['id'],))]
        after = normalize(before)
        data = json.loads(paper['data'])
        if before == after and sorted(data.get('tag_ids', before)) == sorted(after):
            continue
        db.execute('DELETE FROM paper_tags WHERE paper_id=?', (paper['id'],))
        db.executemany('INSERT INTO paper_tags VALUES (?,?)', [(paper['id'], identifier) for identifier in after])
        data['tag_ids'] = after
        db.execute('UPDATE papers SET data=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=?',
            (json.dumps(data, ensure_ascii=False), actor, at, paper['id']))
        audit('paper', paper['id'], 'edit', {'tag_ids': before}, {'tag_ids': after})
        migrated_papers.append({'id': paper['id'], 'before': before, 'after': after})
        changed = True
    for case in db.execute('SELECT id,tag_ids FROM tag_cases.reference_cases').fetchall():
        before = json.loads(case['tag_ids'])
        after = normalize(before)
        if before == after:
            continue
        db.execute('UPDATE tag_cases.reference_cases SET tag_ids=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=?',
            (json.dumps(after), actor, at, case['id']))
        audit('case', case['id'], 'edit', {'tag_ids': before}, {'tag_ids': after})
        migrated_cases.append({'id': case['id'], 'before': before, 'after': after})
        changed = True
    removed = []
    for identifier in REDIRECTS:
        if identifier in existing:
            db.execute('DELETE FROM tags WHERE id=?', (identifier,))
            audit('tag', identifier, 'delete', existing[identifier], {'replacement_id': REDIRECTS[identifier]})
            removed.append(identifier)
            changed = True

    interrupted = []
    if changed:
        interrupted = [dict(r) for r in db.execute("SELECT job_id,count(*) AS count FROM asset_tag_items WHERE status IN ('queued','processing') GROUP BY job_id")]
        db.execute("UPDATE asset_tag_items SET status='conflict',attempt=NULL,message='标签体系已同步，请按最新标签重新发起全库打标。' WHERE status IN ('queued','processing')")
        for job in interrupted:
            db.execute('UPDATE asset_tag_jobs SET updated_at=? WHERE id=?', (time.time(), job['job_id']))
    violations = list(db.execute('PRAGMA main.foreign_key_check')) + list(db.execute('PRAGMA tag_cases.foreign_key_check'))
    if violations:
        raise ValueError('Foreign key checks failed: ' + repr(violations))
    if {r[0] for r in db.execute('SELECT id FROM tags')} != set(target):
        raise ValueError('The final tag catalog does not match the planned catalog.')
    return {'changed': changed, 'dimension_ids': mapping, 'dimension_count': len(mapping), 'tag_count': len(target),
        'per_dimension': dict(Counter(t['dimension_key'] for t in target.values())),
        'excluded_source_ids': list(REDIRECTS), 'removed_local_ids': removed, 'redirects': REDIRECTS,
        'reparented': reparented, 'migrated_papers': migrated_papers, 'migrated_cases': migrated_cases,
        'interrupted_tagging_jobs': interrupted, 'online_written': False}


def main():
    sys.path.insert(0, str(ROOT / 'backend'))
    from src.config import Settings
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--db', type=Path, default=Path(settings.literature_db))
    parser.add_argument('--case-db', type=Path, default=Path(settings.case_library_db))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    for path in (args.db, args.case_db):
        if not path.is_file() or ROOT not in path.resolve().parents:
            parser.error('Only existing databases inside this workspace can be synchronized.')
    if (ROOT / 'backend/var/handoff').resolve() not in args.output.resolve().parents:
        parser.error('Output must be a new directory under backend/var/handoff.')
    source = args.source.read_bytes()
    snapshot = json.loads(source)
    args.output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(args.db, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('ATTACH DATABASE ? AS tag_cases', (str(args.case_db.resolve()),))
    try:
        db.execute('BEGIN IMMEDIATE')
        if args.apply:
            # Both databases are write-locked while separate readers back up
            # the committed state; never call backup on the writer connection.
            for name, path in [('literature-before.sqlite3', args.db), ('cases-before.sqlite3', args.case_db)]:
                with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as reader, sqlite3.connect(args.output / name) as backup:
                    reader.backup(backup)
        result = synchronize(db, snapshot)
        result.update(applied=args.apply, source=str(args.source), source_sha256=hashlib.sha256(source).hexdigest(),
            database=str(args.db), case_database=str(args.case_db), captured_date=snapshot['captured_date'])
        exported = {'dimensions': [dict(r) for r in db.execute('SELECT * FROM dimensions ORDER BY sort_order')],
            'tags': [dict(r) for r in db.execute('SELECT * FROM tags ORDER BY dimension_id,sort_order')]}
        (args.output / 'taxonomy-after.json').write_text(json.dumps(exported, ensure_ascii=False, indent=2))
        receipt = args.output / 'receipt.json'
        receipt.write_text(json.dumps({**result, 'applied': False, 'status': 'prepared'}, ensure_ascii=False, indent=2))
        if args.apply:
            db.commit()
        else:
            db.rollback()
        result['status'] = 'applied' if args.apply else 'preview'
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({k: result[k] for k in ('applied', 'dimension_count', 'tag_count', 'removed_local_ids', 'reparented', 'interrupted_tagging_jobs', 'online_written')}, ensure_ascii=False))
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()
