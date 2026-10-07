"""Record current answer and workbench source bytes, including uncommitted files."""
from __future__ import annotations

import hashlib
import json
import subprocess
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description='Fingerprint current uncommitted source without changing it.')
parser.add_argument('--output', required=True, help='Manifest path under docs/iterations/2026-09-29-agent-harness/')
name = parser.parse_args().output
OUTPUT = (ROOT / 'docs/iterations/2026-09-29-agent-harness' / name).resolve()
if OUTPUT.parent != (ROOT / 'docs/iterations/2026-09-29-agent-harness').resolve() or OUTPUT.exists():
    raise SystemExit('Output must be a new file in the iteration docs directory')
PREFIXES = ('backend/src/', 'backend/scripts/', 'backend/tests/', 'frontend/src/',
            'frontend/tests/', 'frontend/public/', 'data/demo/', 'data/eval/',
            'data/metadata/', 'data/papers/')
SINGLES = {'backend/pyproject.toml', 'backend/uv.lock', 'frontend/package.json',
           'frontend/pnpm-lock.yaml', 'frontend/playwright.config.ts',
           'frontend/next.config.ts', 'frontend/tsconfig.json',
           'frontend/eslint.config.mjs', 'frontend/.env.local.example',
           '.env.example', '.gitignore', 'frontend/.gitignore',
           '.github/workflows/ci.yml'}
paths = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
files = {}
for name in sorted(set(paths)):
    if not name or not (name.startswith(PREFIXES) or name in SINGLES):
        continue
    path = ROOT / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Unexpected source path: {name}')
    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
digest = hashlib.sha256()
for name, sha in files.items():
    digest.update(name.encode() + b'\0' + sha.encode() + b'\n')
created_at = datetime.now(timezone.utc)
build_version = f'delivery-{created_at:%Y%m%d}-{digest.hexdigest()[:12]}'
result = {'created_at': created_at.isoformat(),
          'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
          'source_sha256': digest.hexdigest(), 'build_version': build_version,
          'file_count': len(files), 'files': files,
          'scope': 'Current working-tree code, tests, dependency locks, public demo assets, and versioned evaluation data; ignored private data and external model/index assets excluded'}
OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(OUTPUT.relative_to(ROOT)), 'source_sha256': result['source_sha256'],
                  'file_count': len(files), 'build_version': build_version}))
