import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.evaluation.handoff import import_package, load_package

SOURCE = Path(__file__).resolve().parents[2] / "docs/iterations/2026-11-09-prd-handoff/source"


def test_idempotent_source_only_import(tmp_path):
    db_path = tmp_path / 'archive.sqlite3'
    assert import_package(SOURCE, db_path)['inserted'] == 8
    assert import_package(SOURCE, db_path)['inserted'] == 0
    with sqlite3.connect(db_path) as db:
        rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM handoff_sources')]
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert len(rows) == 8
    assert sum(len(r['baseline']['turns']) for r in rows) == 21
    assert sum(r['source']['source_review_status'] == 'needs_changes' for r in rows) == 5
    assert all(r['new_run_ids'] == [] and r['new_result'] == '未运行' for r in rows)
    assert tables == {'handoff_packages', 'handoff_sources'}


def test_history_and_trajectory_are_preserved():
    rows = {r['source']['id']: r for r in load_package(SOURCE)['snapshots']}
    fix = rows['FIX-05']
    assert fix['source']['target_turn'] == 2
    assert [h['role'] for h in fix['seed_history']] == ['user', 'assistant']
    assert fix['case']['steps'][0]['input'] == fix['baseline']['turns'][1]['user']
    keep = rows['KEEP-03']
    assert keep['seed_history'] == []
    assert len(keep['case']['steps']) == 3
    assert [s['input'] for s in keep['case']['steps']] == [t['user'] for t in keep['baseline']['turns']]
    assert keep['local_id'] != rows['KEEP-01']['local_id']


def test_checksum_rejected_before_import(tmp_path):
    source = tmp_path / 'source'
    shutil.copytree(SOURCE, source)
    with (source / 'data/reviewed-cases.json').open('a') as f:
        f.write(' ')
    database = tmp_path / 'archive.sqlite3'
    with pytest.raises(ValueError, match='checksum'):
        import_package(source, database)
    assert not database.exists()


def test_application_database_rejected(tmp_path):
    database = tmp_path / 'app.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE agent_runs (run_id TEXT)')
    with pytest.raises(ValueError, match='dedicated'):
        import_package(SOURCE, database)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [('agent_runs',)]


def test_immutable_sources_not_overwritten(tmp_path):
    database = tmp_path / 'archive.sqlite3'
    import_package(SOURCE, database)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE handoff_sources SET payload='{}' WHERE local_id LIKE '%FIX-05'")
    with pytest.raises(ValueError, match='immutable'):
        import_package(SOURCE, database)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT payload FROM handoff_sources WHERE local_id LIKE '%FIX-05'").fetchone()[0] == '{}'
