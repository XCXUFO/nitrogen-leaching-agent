"""Local CLI for auditable WHCNS nitrogen/water balance reading."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model_tools.whcns_results import summarize_result
from src.model_tools.workbooks import WorkbookError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--kind", choices=("nitrogen", "water"), required=True)
    parser.add_argument("--out", type=Path, help="new local JSON output; existing files are not overwritten")
    args = parser.parse_args()
    try:
        report = summarize_result(args.path, kind=args.kind)
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("x", encoding="utf-8") as target:
                target.write(payload)
            print(f"Wrote {args.out}: {report['rows']} rows, sha256={report['sha256']}")
        else:
            print(payload, end="")
    except (WorkbookError, OSError) as exc:
        print(json.dumps({"error": "invalid_result_file", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
