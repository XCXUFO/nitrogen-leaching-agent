"""Shared source and immutable frontend artifact verification."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

DIST_DIRS = ('.next', '.next-candidate', '.next-workbench', '.next-demo')


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
