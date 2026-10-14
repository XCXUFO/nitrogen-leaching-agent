import sqlite3

import pytest

from scripts.literature_archive import backup, restore, verify
from src.api.literature import LiteratureStore, PaperInput, ReasonInput, create_paper, delete_paper
from src.evaluation.contracts import Principal
from tests.test_literature import FakeRequest, upload_pdf


def test_archive_restore_keeps_deleted_files_and_audit(tmp_path):
    db_path, files = tmp_path / "live.db", tmp_path / "files"
    db = LiteratureStore(str(db_path), str(files))
    user = Principal(tester_id="tester", role="tester")
    try:
        paper = create_paper(FakeRequest(db), PaperInput(upload_id=upload_pdf(db, user)), user)
        delete_paper(FakeRequest(db), paper["id"], ReasonInput(reason="mistake"), user)
        upload_pdf(db, user)  # Uncommitted uploads must not be restored.
        archive, recovered = tmp_path / "archive", tmp_path / "recovered"
        assert backup(db_path, files, archive) == {"papers_including_deleted": 1, "pdf_files": 1}
        assert restore(archive, recovered) == verify(archive)
        with sqlite3.connect(recovered / "library.sqlite3") as restored:
            assert restored.execute("SELECT deleted FROM papers").fetchone()[0] == 1
            assert restored.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
            assert restored.execute("SELECT COUNT(*) FROM uploads WHERE consumed_at IS NULL").fetchone()[0] == 0
        assert (recovered / "files" / f"blob-{paper['sha256']}.pdf").is_file()
        with pytest.raises(FileExistsError): restore(archive, recovered)
        # Refuse corrupt archives before creating a destination.
        (archive / "files" / f"blob-{paper['sha256']}.pdf").write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="checksum"): restore(archive, tmp_path / "corrupt-restore")
        assert not (tmp_path / "corrupt-restore").exists()
    finally:
        db.close()


def test_missing_original_cannot_produce_success_manifest(tmp_path):
    db_path, files = tmp_path / "live.db", tmp_path / "files"
    db = LiteratureStore(str(db_path), str(files))
    user = Principal(tester_id="tester", role="tester")
    try:
        paper = create_paper(FakeRequest(db), PaperInput(upload_id=upload_pdf(db, user)), user)
        (files / f"blob-{paper['sha256']}.pdf").unlink()
        with pytest.raises(FileNotFoundError): backup(db_path, files, tmp_path / "archive")
        assert not (tmp_path / "archive" / "manifest.json").exists()
        with pytest.raises(FileExistsError): backup(db_path, files, tmp_path / "archive")
    finally:
        db.close()
