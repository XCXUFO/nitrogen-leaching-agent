"""Read WHCNS balance outputs without assuming a verified simulation case."""
from __future__ import annotations

import math
from pathlib import Path

from .workbooks import WorkbookError, column_letter, read_workbook

TOOL_VERSION = "0.2.0"
SCHEMAS = {
    "nitrogen": {
        "sheet": "Nbal_out",
        "unit": "kg N ha-1",
        "fields": ("Upt_N", "leak_NO3", "leak_NH4", "N-Gas", "N-Nitr", "N-Vola", "N-mine", "N2O emission"),
        "manual_pdf_page": 26,
    },
    "water": {
        "sheet": "WtaBal_out",
        "unit": "mm",
        "fields": ("ET0", "ETp", "ETa", "Ep", "Ea", "Tp", "Ta", "Draining", "IRRI", "PREC", "runoff"),
        "manual_pdf_page": 25,
    },
}


def summarize_result(path: Path, *, kind: str | None = None) -> dict:
    book = read_workbook(path)
    if kind is None:
        matches = [k for k, s in SCHEMAS.items() if any(t["name"] == s["sheet"] for t in book["sheets"])]
        if len(matches) != 1:
            raise WorkbookError("expected exactly one Nbal_out or WtaBal_out result sheet")
        kind = matches[0]
    if kind not in SCHEMAS:
        raise WorkbookError(f"unsupported result kind: {kind}")
    schema = SCHEMAS[kind]
    sheet = next((s for s in book["sheets"] if s["name"] == schema["sheet"]), None)
    if sheet is None:
        raise WorkbookError(f"required sheet missing: {schema['sheet']}")
    rows = sheet["rows"]
    if len(rows) < 2:
        raise WorkbookError("result sheet must contain a header and data rows")
    headers = [str(v).strip() if v is not None else "" for v in rows[0]]
    if headers[0].lower() != "day":
        raise WorkbookError("A1 must identify the model day; calendar dates are not inferred")
    if any(not h for h in headers) or len(headers) != len(set(headers)):
        raise WorkbookError("empty or duplicate headers are not supported")
    expected = [f"{field}({schema['unit']})" for field in schema["fields"]]
    missing = [field for field in expected if field not in headers]
    if missing:
        raise WorkbookError(f"required columns or exact units missing: {', '.join(missing)}")
    if len(headers) != len(expected) + 1:
        raise WorkbookError("unrecognized columns: review this output version before interpreting it")
    data = rows[1:]
    for r, row in enumerate(data, start=2):
        if len(row) != len(headers):
            raise WorkbookError(f"row width mismatch at {sheet['name']}!{r}")
        for c, value in enumerate(row, start=1):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise WorkbookError(f"finite numeric value required at {sheet['name']}!{column_letter(c)}{r}")
        day = row[0]
        if day < 1 or int(day) != day or (r > 2 and day != data[r-3][0] + 1):
            raise WorkbookError(f"day must be a consecutive positive integer at {sheet['name']}!A{r}")
    columns = []
    for header in expected:
        c = headers.index(header)
        values = [row[c] for row in data]
        low, high = min(values), max(values)
        col = column_letter(c + 1)
        def extreme(value):
            index = values.index(value)
            return {"value": value, "cell": f"{sheet['name']}!{col}{index+2}",
                    "model_day": int(data[index][0]), "day_cell": f"{sheet['name']}!A{index+2}",
                    "occurrences": values.count(value)}
        try:
            raw_sum = math.fsum(values)
        except OverflowError as exc:
            raise WorkbookError(f"numeric sum overflow in {sheet['name']}!{col}") from exc
        columns.append({
            "header": header, "unit": schema["unit"], "count": len(values),
            "range": f"{sheet['name']}!{col}2:{col}{len(rows)}",
            "first": {"value": values[0], "cell": f"{sheet['name']}!{col}2"},
            "last": {"value": values[-1], "cell": f"{sheet['name']}!{col}{len(rows)}"},
            "min": extreme(low),
            "max": extreme(high),
            "raw_column_sum": raw_sum,
        })
    return {
        "tool": "whcns_balance_reader", "tool_version": TOOL_VERSION,
        "schema_id": f"whcns-received-20260926-{kind}-v1",
        "file": book["file"], "sha256": book["sha256"], "format": book["format"],
        "kind": kind, "sheet": sheet["name"], "rows": len(data),
        "model_day": {"first": int(data[0][0]), "last": int(data[-1][0])},
        "columns": columns,
        "manual_reference": {"source_id": "whcns-manual-202508", "pdf_page": schema["manual_pdf_page"],
                             "review_status": "pending", "version_match": "unconfirmed"},
        "warnings": book["warnings"] + [
            "raw_column_sum is arithmetic only, not a verified seasonal or annual total.",
            "Model day is not a calendar date. Run origin, input/output pairing and time semantics require confirmation.",
            "This reads supplied outputs; it does not execute WHCNS, validate the model or recommend management decisions.",
        ],
    }
