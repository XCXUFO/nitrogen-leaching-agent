"""Run from backend: .venv/bin/python scripts/eval_archive.py --help."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.operations.archive import backup, export_evidence, restore, verify


def main():
    parser = argparse.ArgumentParser(description='Private SQLite backup / verify / restore / evidence export. Existing destinations are never overwritten.')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('backup')
    create.add_argument('--database', type=Path, required=True)
    create.add_argument('--access', type=Path, required=True)
    create.add_argument('--credentials', type=Path)
    create.add_argument('--destination', type=Path, required=True)
    for command in ('verify', 'restore'):
        child = commands.add_parser(command)
        child.add_argument('--bundle', type=Path, required=True)
        if command == 'restore':
            child.add_argument('--destination', type=Path, required=True)
    export = commands.add_parser('export')
    export.add_argument('--database', type=Path, required=True)
    export.add_argument('--destination', type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    try:
        result = {'backup': backup, 'verify': verify, 'restore': restore, 'export': export_evidence}[command](**args)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')
    # No credential contents or evidence payloads on stdout.
    print(json.dumps({'command': command, 'result': result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
