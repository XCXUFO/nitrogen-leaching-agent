"""Consistent SQLite snapshots and non-overwriting recovery into a new directory."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def connect_readonly(path: Path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def database_inventory(path: Path) -> dict:
    with closing(connect_readonly(path)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        tables = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            rows = db.execute(f'SELECT * FROM {quoted}').fetchall()
            # Sort row digests, retaining duplicates, so physical page layout is irrelevant.
            hashes = sorted(hashlib.sha256(repr(row).encode()).hexdigest() for row in rows)
            tables[name] = {'rows': len(rows), 'sha256': hashlib.sha256(''.join(hashes).encode()).hexdigest()}
        schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        return {'tables': tables, 'schema_sha256': hashlib.sha256(repr(schema).encode()).hexdigest()}


def write_json(path: Path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    path.chmod(0o600)


def backup(database: Path, access: Path, destination: Path, credentials: Path | None = None) -> dict:
    # Validate sources before reserving the destination. Never create an empty source DB.
    if not database.is_file() or not access.is_file() or (credentials and not credentials.is_file()):
        raise ValueError('Backup source is missing')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    snapshot = destination / 'runs.sqlite3'
    with closing(connect_readonly(database)) as source, closing(sqlite3.connect(snapshot)) as target:
        source.backup(target)  # Includes committed WAL pages while the service is running.
    snapshot.chmod(0o600)
    files = {'runs.sqlite3': digest(snapshot)}
    for name, path in [('access-keys.json', access), ('access-credentials.txt', credentials)]:
        if path:
            shutil.copyfile(path, destination / name)
            (destination / name).chmod(0o600)
            files[name] = digest(destination / name)
    manifest = {'format_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                'files': files, 'database': database_inventory(snapshot),
                'scope': 'Run/evaluation database and access identities only; external assets, model/index files and in-memory sessions are not included'}
    write_json(destination / 'manifest.json', manifest)
    return manifest


def verify(bundle: Path) -> dict:
    manifest = json.loads((bundle / 'manifest.json').read_text())
    names = set(manifest['files'])
    if manifest.get('format_version') != 1 or not {'runs.sqlite3', 'access-keys.json'} <= names or not names <= {'runs.sqlite3', 'access-keys.json', 'access-credentials.txt'}:
        raise ValueError('Unsupported archive manifest')
    for name, expected in manifest['files'].items():
        path = bundle / name
        if path.is_symlink() or digest(path) != expected:
            raise ValueError(f'Archive fingerprint mismatch: {name}')
    if database_inventory(bundle / 'runs.sqlite3') != manifest['database']:
        raise ValueError('Archive database inventory mismatch')
    return manifest


def restore(bundle: Path, destination: Path) -> dict:
    manifest = verify(bundle)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in manifest['files']:
        shutil.copyfile(bundle / name, destination / name)
        (destination / name).chmod(0o600)
    write_json(destination / 'manifest.json', manifest)
    verify(destination)
    return manifest


def export_evidence(database: Path, destination: Path) -> dict:
    """Export all persisted evidence in one read transaction; excludes access keys."""
    with closing(connect_readonly(database)) as db:
        db.execute('BEGIN')
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                 if row[0] == 'agent_runs' or row[0].startswith('eval_')]
        tables = {}
        for name in names:
            cursor = db.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY rowid')
            tables[name] = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor]
    result = {'format_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'tables': tables}
    # Export contains questions/answers and local paths; keep private by default.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return {'tables': {name: len(rows) for name, rows in tables.items()}, 'sha256': digest(destination)}
