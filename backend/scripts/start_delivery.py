"""Start the verified workspace build on the stable local ports."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description='Start a fingerprinted local delivery build.')
parser.add_argument('--manifest', default='delivery-source-manifest-2026-10-07.json')
parser.add_argument('--dist-dir', choices=('.next', '.next-candidate', '.next-workbench', '.next-demo'), default='.next')
args = parser.parse_args()
manifest_dir = ROOT / 'docs/iterations/2026-09-29-agent-harness'
manifest_path = manifest_dir / args.manifest
if manifest_path.parent != manifest_dir or not manifest_path.is_file():
    raise SystemExit('Manifest must be a file in the delivery iteration directory')
manifest = json.loads(manifest_path.read_text())
for name, expected in manifest['files'].items():
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Source changed after manifest: {name}')
if not (ROOT / 'frontend' / args.dist_dir / 'BUILD_ID').is_file():
    raise SystemExit(f'Frontend build missing: {args.dist_dir}')
version = manifest.get('build_version') or 'delivery-20261004-' + manifest['source_sha256'][:12]
service = ROOT / 'backend/var/service'
service.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.update(EVAL_ENABLED='true', AGENT_BUILD_VERSION=version,
           HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
           RAG_RERANKER_ENABLED='false', DEEPSEEK_PROXY='http://127.0.0.1:7890',
           NEXT_TELEMETRY_DISABLED='1', NODE_OPTIONS='--max-old-space-size=1024',
           NITROGEN_NEXT_DIST_DIR=args.dist_dir)
for name, cwd, command in [
    ('backend', ROOT / 'backend', [str(ROOT / 'backend/.venv/bin/python'), '-m', 'uvicorn',
                                 'src.main:app', '--host', '127.0.0.1', '--port', '8000', '--workers', '1']),
    ('frontend', ROOT / 'frontend', ['/usr/bin/pnpm', 'start', '--hostname', '127.0.0.1', '--port', '3000']),
]:
    with (service / f'{name}.log').open('ab', buffering=0) as log:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, start_new_session=True)
    (service / f'{name}.pid').write_text(str(proc.pid) + '\n')
    print(f'{name} pid={proc.pid} build={version}')
