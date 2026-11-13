"""Receipt boundaries use tiny synthetic archives, never production originals."""
import hashlib
import json
from zipfile import ZipFile

import pytest

from src.evaluation.material_handoff import receive_archive, relative_path, verify_files


def package(path, text=b'original', extra=None):
    manifest = {'files': [{'path': 'runs/record.json', 'bytes': len(text),
                           'sha256': hashlib.sha256(text).hexdigest()}]}
    with ZipFile(path, 'w') as archive:
        archive.writestr('export/manifest.json', json.dumps(manifest))
        archive.writestr('export/runs/record.json', text)
        if extra:
            archive.writestr(*extra)


def test_receipt_idempotent_and_changed_package_cannot_replace_originals(tmp_path):
    archive, target = tmp_path / 'source.zip', tmp_path / 'received'
    package(archive)
    assert receive_archive(archive, target)
    assert not receive_archive(archive, target)
    package(archive, b'changed')
    with pytest.raises(ValueError, match='immutable'):
        receive_archive(archive, target)
    assert (target / 'runs/record.json').read_bytes() == b'original'


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'C:/file', 'a\\b', 'a/../b', 'a//b'])
def test_unsafe_paths_rejected(name):
    with pytest.raises(ValueError, match='unsafe'):
        relative_path(name)


def test_unlisted_file_or_traversal_cannot_publish_partial_receipt(tmp_path):
    archive, target = tmp_path / 'source.zip', tmp_path / 'received'
    package(archive, extra=('export/extra', 'unlisted'))
    with pytest.raises(ValueError, match='unlisted'):
        receive_archive(archive, target)
    assert not target.exists()
    package(archive, extra=('export/../outside', 'escape'))
    with pytest.raises(ValueError, match='unsafe'):
        receive_archive(archive, target)
    assert not target.exists() and not (tmp_path / 'outside').exists()


def test_corruption_in_existing_receipt_is_detected_without_overwrite(tmp_path):
    archive, target = tmp_path / 'source.zip', tmp_path / 'received'
    package(archive)
    receive_archive(archive, target)
    (target / 'runs/record.json').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash mismatch'):
        verify_files(target)
    with pytest.raises(ValueError, match='hash mismatch'):
        receive_archive(archive, target)
    assert (target / 'runs/record.json').read_bytes() == b'tampered'
