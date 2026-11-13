import importlib.util
import json
import shutil
import subprocess
import sys
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


def test_delivery_manifest_includes_retrieval_aliases_and_rejects_their_changes(tmp_path):
    fixture(tmp_path)
    scripts = tmp_path / 'backend/scripts'
    scripts.mkdir(parents=True)
    for name in ('create_delivery_manifest.py', 'delivery_checks.py'):
        shutil.copyfile(Path(__file__).parents[1] / 'scripts' / name, scripts / name)
    output_dir = tmp_path / 'docs/iterations/2026-09-29-agent-harness'
    output_dir.mkdir(parents=True)
    aliases = tmp_path / 'backend/data/retrieval/aliases.json'
    aliases.parent.mkdir(parents=True)
    aliases.write_text('{"aliases": []}')
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    # The source fingerprint records a base commit; no project Git state is used.
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '--allow-empty', '-qm', 'fixture'], cwd=tmp_path, check=True)
    subprocess.run([sys.executable, str(scripts / 'create_delivery_manifest.py'), '--output', 'fixture.json'],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    manifest = json.loads((output_dir / 'fixture.json').read_text())
    assert manifest['files']['backend/data/retrieval/aliases.json'] == checks.fingerprint(aliases)
    checks.verify(tmp_path, manifest)
    added = tmp_path / 'backend/src/new_runtime.py'
    added.parent.mkdir(parents=True)
    added.write_text('VALUE = 1\n')
    with pytest.raises(ValueError, match='inventory.*new_runtime.py'):
        checks.verify(tmp_path, manifest)
    added.unlink()
    checks.verify(tmp_path, manifest)
    aliases.write_text('{"aliases": ["changed"]}')
    with pytest.raises(ValueError, match='aliases.json'):
        checks.verify(tmp_path, manifest)
