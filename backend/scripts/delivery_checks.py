"""Shared source and immutable frontend artifact verification."""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path

DIST_DIRS = ('.next', '.next-candidate', '.next-workbench', '.next-demo', '.next-prompts', '.next-prompts-md')
SOURCE_PREFIXES = ('backend/src/', 'backend/scripts/', 'backend/tests/', 'frontend/src/',
                   'frontend/tests/', 'frontend/public/', 'data/demo/', 'data/eval/',
                   'data/metadata/', 'data/papers/')
SOURCE_SINGLES = {'backend/pyproject.toml', 'backend/uv.lock', 'frontend/package.json',
                  'backend/data/retrieval/aliases.json', 'frontend/pnpm-lock.yaml',
                  'frontend/playwright.config.ts', 'frontend/next.config.ts',
                  'frontend/tsconfig.json', 'frontend/eslint.config.mjs',
                  'frontend/.env.local.example', '.env.example', '.gitignore',
                  'frontend/.gitignore', '.github/workflows/ci.yml'}


def source_inventory(root: Path) -> list[str]:
    paths = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=root).decode().split('\0')
    result = []
    for name in sorted(set(paths)):
        if not name or not (name.startswith(SOURCE_PREFIXES) or name in SOURCE_SINGLES):
            continue
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Unexpected source path: {name}')
        result.append(name)
    return result


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_binding(root: Path, dist_dir: str, backend_url: str) -> dict:
    if dist_dir not in DIST_DIRS or backend_url != 'http://127.0.0.1:8000':
        raise ValueError('Delivery requires an approved build directory and backend http://127.0.0.1:8000')
    build = root / 'frontend' / dist_dir
    routes = json.loads((build / 'routes-manifest.json').read_text())
    rewrites = routes['rewrites']
    rules = rewrites if isinstance(rewrites, list) else [rule for group in rewrites.values() for rule in group]
    if not any(r.get('source') == '/api/:path*' and r.get('destination') == backend_url + '/api/:path*' for r in rules):
        raise ValueError('Frontend build API destination does not match delivery backend')
    # These build artifacts are immutable while Next serves the application.
    paths = [p for folder in ('server', 'static') for p in (build / folder).rglob('*') if p.is_file()]
    paths += [p for p in build.iterdir() if p.is_file() and (p.suffix == '.json' or p.name == 'BUILD_ID')]
    files = {str(p.relative_to(build)): fingerprint(p) for p in sorted(paths)}
    return {'dist_dir': dist_dir, 'backend_url': backend_url,
            'build_id': (build / 'BUILD_ID').read_text().strip(), 'files': files}


def verify(root: Path, manifest: dict, dist_dir: str | None = None) -> dict:
    if manifest.get('source_inventory_version') == 1:
        difference = set(source_inventory(root)) ^ set(manifest['files'])
        if difference:
            raise ValueError('Source inventory changed after manifest: ' + ', '.join(sorted(difference)))
    for name, expected in manifest['files'].items():
        path = root / name
        if not path.is_file() or fingerprint(path) != expected:
            raise ValueError(f'Source changed or missing after manifest: {name}')
    binding = manifest.get('frontend_build')
    if not binding:
        raise ValueError('Manifest lacks frontend build binding; generate a current delivery manifest')
    if dist_dir and dist_dir != binding['dist_dir']:
        raise ValueError('Requested build directory differs from manifest')
    actual = build_binding(root, binding['dist_dir'], binding['backend_url'])
    if actual != binding:
        raise ValueError('Frontend build changed after manifest; rebuild and generate a new manifest')
    return binding
