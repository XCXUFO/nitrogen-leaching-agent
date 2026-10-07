"""Build a deterministic synthetic water output for portable integration tests."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data/demo/waterbal_out.xls"


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"Refusing to replace {OUTPUT}")
    book = Workbook()
    sheet = book.active
    sheet.title = "WtaBal_out"
    sheet.append(["day", *(f"{name}(mm)" for name in (
        "ET0", "ETp", "ETa", "Ep", "Ea", "Tp", "Ta", "Draining", "IRRI", "PREC", "runoff"))])
    for day in range(1, 353):
        # Unique peak at day 276 verifies the original spreadsheet coordinates.
        sheet.append([day, *([0] * 9), 86 if day == 276 else 0, 0])
    book.save(OUTPUT)


if __name__ == "__main__":
    main()
