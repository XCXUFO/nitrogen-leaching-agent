"""Record current answer and workbench source bytes, including uncommitted files."""
from __future__ import annotations

import hashlib
import json
import subprocess
import argparse
from datetime import datetime, timezone
from pathlib import Path
from delivery_checks import build_binding, source_inventory

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description='Fingerprint current uncommitted source without changing it.')
parser.add_argument('--output', required=True, help='Manifest path under docs/iterations/2026-09-29-agent-harness/')
parser.add_argument('--dist-dir', default='.next-candidate')
parser.add_argument('--backend-url', default='http://127.0.0.1:8000')
args = parser.parse_args()
name = args.output
binding = build_binding(ROOT, args.dist_dir, args.backend_url)
OUTPUT = (ROOT / 'docs/iterations/2026-09-29-agent-harness' / name).resolve()
if OUTPUT.parent != (ROOT / 'docs/iterations/2026-09-29-agent-harness').resolve() or OUTPUT.exists():
    raise SystemExit('Output must be a new file in the iteration docs directory')
files = {}
for name in source_inventory(ROOT):
    path = ROOT / name
    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
digest = hashlib.sha256()
for name, sha in files.items():
    digest.update(name.encode() + b'\0' + sha.encode() + b'\n')
created_at = datetime.now(timezone.utc)
build_version = f'delivery-{created_at:%Y%m%d}-{digest.hexdigest()[:12]}'
result = {'created_at': created_at.isoformat(),
          'source_inventory_version': 1,
          'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
          'source_sha256': digest.hexdigest(), 'build_version': build_version,
          'file_count': len(files), 'files': files, 'frontend_build': binding,
          'scope': 'Current working-tree code, tests, dependency locks, public demo assets, and versioned evaluation data; ignored private data and external model/index assets excluded'}
OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(OUTPUT.relative_to(ROOT)), 'source_sha256': result['source_sha256'],
                  'file_count': len(files), 'build_version': build_version}))
