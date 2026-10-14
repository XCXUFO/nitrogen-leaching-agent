import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('delivery_checks', Path(__file__).parents[1] / 'scripts/delivery_checks.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def fixture(root):
    source = root / 'source.py'
    source.write_text('version = 1')
    build = root / 'frontend/.next-candidate'
    (build / 'server').mkdir(parents=True)
    (build / 'static').mkdir()
    (build / 'server/page.js').write_text('page')
    (build / 'static/client.js').write_text('client')
    (build / 'BUILD_ID').write_text('synthetic-build')
    (build / 'routes-manifest.json').write_text(json.dumps({'rewrites': {'beforeFiles': [], 'afterFiles': [{'source': '/api/:path*', 'destination': 'http://127.0.0.1:8000/api/:path*'}], 'fallback': []}}))
    return {'files': {'source.py': checks.fingerprint(source)}, 'frontend_build': checks.build_binding(root, '.next-candidate', 'http://127.0.0.1:8000')}


@pytest.mark.parametrize('changed', ['source.py', 'frontend/.next-candidate/server/page.js', 'frontend/.next-candidate/static/client.js', 'frontend/.next-candidate/BUILD_ID'])
def test_source_and_build_changes_are_rejected(tmp_path, changed):
    manifest = fixture(tmp_path)
    assert checks.verify(tmp_path, manifest) == manifest['frontend_build']
    (tmp_path / changed).write_text('changed')
    with pytest.raises(ValueError): checks.verify(tmp_path, manifest)


def test_missing_source_wrong_build_and_wrong_proxy_are_rejected(tmp_path):
    manifest = fixture(tmp_path)
    with pytest.raises(ValueError, match='directory'): checks.verify(tmp_path, manifest, '.next')
    with pytest.raises(ValueError, match='binding'): checks.verify(tmp_path, {'files': manifest['files']})
    with pytest.raises(ValueError, match='backend'): checks.build_binding(tmp_path, '.next-candidate', 'http://127.0.0.1:8107')
    (tmp_path / 'source.py').unlink()
    with pytest.raises(ValueError, match='missing'): checks.verify(tmp_path, manifest)
