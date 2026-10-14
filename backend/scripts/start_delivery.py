"""Start the verified workspace build on the stable local ports."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.request import urlopen

from delivery_checks import DIST_DIRS, verify

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description='Start a fingerprinted local delivery build.')
    parser.add_argument('--manifest', default='delivery-source-manifest-2026-10-12-review.json')
    parser.add_argument('--dist-dir', choices=DIST_DIRS)
    parser.add_argument('--check', action='store_true', help='Verify source and build without starting services')
    args = parser.parse_args()
    directory = ROOT / 'docs/iterations/2026-09-29-agent-harness'
    path = (directory / args.manifest).resolve()
    if path.parent != directory or not path.is_file():
        raise SystemExit('Manifest must be a file in the delivery iteration directory')
    manifest = json.loads(path.read_text())
    try:
        binding = verify(ROOT, manifest, args.dist_dir)
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc
    version = manifest['build_version']
    if args.check:
        print(f"Verified {version}: {binding['dist_dir']} -> {binding['backend_url']}")
        return
    # Refuse before spawning either child if an existing service owns a port.
    for port in (8000, 3000):
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1', port))
            except OSError as exc: raise SystemExit(f'Port {port} is already in use; stop the existing service first') from exc
    service = ROOT / 'backend/var/service'
    service.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(EVAL_ENABLED='true', AGENT_BUILD_VERSION=version,
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               NEXT_TELEMETRY_DISABLED='1', NODE_OPTIONS='--max-old-space-size=1024',
               NITROGEN_NEXT_DIST_DIR=binding['dist_dir'], BACKEND_INTERNAL_URL=binding['backend_url'])
    started = []
    try:
        for name, cwd, command, health in [
            ('backend', ROOT / 'backend', [str(ROOT / 'backend/.venv/bin/python'), '-m', 'uvicorn',
                'src.main:app', '--host', '127.0.0.1', '--port', '8000', '--workers', '1',
                '--no-proxy-headers'], 'http://127.0.0.1:8000/api/ready'),
            ('frontend', ROOT / 'frontend', [str(ROOT / 'frontend/node_modules/.bin/next'), 'start', '--hostname', '127.0.0.1', '--port', '3000'], 'http://127.0.0.1:3000/showcase/literature'),
        ]:
            with (service / f'{name}.log').open('ab', buffering=0) as log:
                proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=log, start_new_session=True)
            started.append((name, proc))
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if proc.poll() is not None: raise RuntimeError(f'{name} exited; inspect {service / (name + ".log")}')
                try:
                    with urlopen(health, timeout=2) as response:
                        if response.status == 200: break
                except OSError: pass
                time.sleep(0.5)
            else: raise RuntimeError(f'{name} failed to become healthy; inspect its service log')
            (service / f'{name}.pid').write_text(str(proc.pid) + '\n')
            print(f'{name} healthy pid={proc.pid} build={version}', flush=True)
    except BaseException:
        for name, proc in reversed(started):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); proc.wait()
            (service / f'{name}.pid').unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    main()
