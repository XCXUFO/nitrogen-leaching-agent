"""Import the reviewed PRD sources into an isolated local SQLite archive."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.evaluation.handoff import import_package

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "docs/iterations/2026-11-09-prd-handoff/source")
    parser.add_argument("--database", type=Path, default=ROOT / "backend/var/handoff/2026-11-09.sqlite3")
    args = parser.parse_args()
    print(json.dumps(import_package(args.source, args.database), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
