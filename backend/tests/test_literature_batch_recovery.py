"""Fault injection at persistence boundaries and real retry interleavings."""
import sqlite3
import time
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, Request

from src.api import literature, literature_batch
from src.evaluation.contracts import Principal


def setup_batch(tmp_path):
    db = literature.LiteratureStore(str(tmp_path / 'papers.db'), str(tmp_path / 'pdfs'))
    owner = Principal(tester_id='review', role='tester')
    request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(literature=db))})
    (db.root / 'upload-review').write_bytes(b'%PDF-fixture')
    with db.write():
        db.db.execute('INSERT INTO uploads VALUES (?,?,?,?,?,?,NULL)',
                      ('review', 'review.pdf', 'reviewhash', 12, owner.tester_id, literature.now()))
        paper = literature.create_paper_record(db, literature.PaperInput(upload_id='review'), owner)
    batch = literature_batch.create_batch_ai(request, literature_batch.BatchAIInput(
        paper_ids=[paper['id']], ai_extract=True, ai_tag=False), BackgroundTasks(), owner)
    return request, owner, db, paper, batch


@pytest.mark.asyncio
@pytest.mark.parametrize('after_receipt_write', [False, True])
async def test_crash_rolls_back_paper_and_receipt_then_recovers(tmp_path, monkeypatch, after_receipt_write):
    request, owner, db, paper, batch = setup_batch(tmp_path)
    async def extract(*args):
        return {'fields': {'title': 'Successfully parsed title'}, 'warning': ''}
    monkeypatch.setattr(literature_batch, 'extract_paper_fields', extract)
    original_write = literature_batch.write_batch
    class ProcessStopped(BaseException):
        pass
    def interrupted_write(store, value):
        if value['items'][0]['status'] == 'ready':
            # The paper is updated on the writer's connection but remains invisible
            # to another connection until the receipt can be committed with it.
            assert store.get_paper(paper['id'])['revision'] == 2
            with sqlite3.connect(tmp_path / 'papers.db') as reader:
                assert reader.execute('SELECT revision FROM papers').fetchone()[0] == 1
            if after_receipt_write:
                original_write(store, value)
            raise ProcessStopped()
        original_write(store, value)
    monkeypatch.setattr(literature_batch, 'write_batch', interrupted_write)
    try:
        with pytest.raises(ProcessStopped):
            await literature_batch.process_batch(request, batch['id'], owner)
        receipt = literature_batch.read_batch(db, batch['id'], owner)
        assert receipt['items'][0]['status'] == 'processing'
        assert receipt['items'][0]['revision'] == db.get_paper(paper['id'])['revision'] == 1
        assert db.get_paper(paper['id'])['title'] == paper['title']
        receipt['items'][0]['started_at'] = time.time() - 600
        monkeypatch.setattr(literature_batch, 'write_batch', original_write)
        with db.write():
            literature_batch.write_batch(db, receipt)
        literature_batch.retry_import(request, batch['id'], BackgroundTasks(), None, owner)
        await literature_batch.process_batch(request, batch['id'], owner)
        receipt = literature_batch.read_batch(db, batch['id'], owner)
        assert receipt['items'][0]['status'] == 'ready'
        assert receipt['items'][0]['revision'] == db.get_paper(paper['id'])['revision'] == 2
        assert db.get_paper(paper['id'])['title'] == 'Successfully parsed title'
        assert len(db.events('paper', paper['id'])) == 2  # Rolled-back edits leave no event.
    finally:
        db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('new_worker_completed', [False, True])
async def test_stale_worker_never_saves_or_replaces_receipt(tmp_path, monkeypatch, new_worker_completed):
    request, owner, db, paper, batch = setup_batch(tmp_path)
    calls = 0
    async def replaced_during_extract(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            current = literature_batch.read_batch(db, batch['id'], owner)
            with db.write():
                current['items'][0]['started_at'] = time.time() - 600
                literature_batch.write_batch(db, current)
            literature_batch.retry_import(request, batch['id'], BackgroundTasks(), None, owner)
            if new_worker_completed:
                await literature_batch.process_batch(request, batch['id'], owner)
            return {'fields': {'title': 'Old worker result'}, 'warning': ''}
        return {'fields': {'title': 'New worker result'}, 'warning': ''}
    monkeypatch.setattr(literature_batch, 'extract_paper_fields', replaced_during_extract)
    try:
        await literature_batch.process_batch(request, batch['id'], owner)
        receipt = literature_batch.read_batch(db, batch['id'], owner)
        if not new_worker_completed:
            assert receipt['items'][0]['status'] == 'queued'
            assert db.get_paper(paper['id'])['revision'] == 1
            await literature_batch.process_batch(request, batch['id'], owner)
            receipt = literature_batch.read_batch(db, batch['id'], owner)
        assert receipt['items'][0]['status'] == 'ready'
        assert receipt['items'][0]['revision'] == 2
        assert db.get_paper(paper['id'])['title'] == 'New worker result'
        assert len(db.events('paper', paper['id'])) == 2
    finally:
        db.close()
