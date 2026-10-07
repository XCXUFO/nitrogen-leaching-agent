import json
import sqlite3
from pathlib import Path

import pytest

from src.operations.archive import backup, database_inventory, export_evidence, restore, verify


def test_wal_backup_restore_preserves_every_record_and_never_overwrites(tmp_path):
    source = tmp_path / 'live.sqlite3'
    access = tmp_path / 'access.json'
    access.write_text('{"users": []}')
    with sqlite3.connect(source) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE eval_reviews (id TEXT PRIMARY KEY, payload TEXT)')
        db.execute('INSERT INTO eval_reviews VALUES (?,?)', ('old-review', '{"overall":"fail"}'))
        db.commit()
        bundle = tmp_path / 'backup'
        manifest = backup(source, access, bundle)
        assert manifest['database'] == database_inventory(source)
        recovered = tmp_path / 'recovered'
        assert restore(bundle, recovered) == manifest
        assert database_inventory(recovered / 'runs.sqlite3') == database_inventory(source)
        with pytest.raises(FileExistsError):
            restore(bundle, recovered)
        assert recovered.stat().st_mode & 0o777 == 0o700
        assert (recovered / 'access-keys.json').stat().st_mode & 0o777 == 0o600
        exported = tmp_path / 'evidence.json'
        assert export_evidence(recovered / 'runs.sqlite3', exported)['tables'] == {'eval_reviews': 1}
        assert json.loads(exported.read_text())['tables']['eval_reviews'][0]['id'] == 'old-review'
        with pytest.raises(FileExistsError):
            export_evidence(source, exported)
        (bundle / 'access-keys.json').write_text('tampered')
        with pytest.raises(ValueError, match='fingerprint'):
            restore(bundle, tmp_path / 'bad')
        assert not (tmp_path / 'bad').exists()
        assert db.execute('SELECT COUNT(*) FROM eval_reviews').fetchone()[0] == 1


def test_missing_source_and_manifest_path_traversal_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        backup(tmp_path / 'missing', tmp_path / 'missing-access', tmp_path / 'bundle')
    assert not (tmp_path / 'missing').exists()
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / 'manifest.json').write_text(json.dumps({'format_version': 1, 'files': {'../secret': 'x'}}))
    with pytest.raises(ValueError, match='Unsupported'):
        verify(bundle)
