"""CSV output that neutralises spreadsheet formula injection."""

from __future__ import annotations

import csv
import io

from fastapi.responses import Response


def safe_cell(value) -> str:
    s = "" if value is None else str(value)
    if s and s[0] in "=+-@\t\r":
        return "'" + s
    return s


def to_csv(headers: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([safe_cell(v) for v in r])
    return buf.getvalue()


def csv_response(filename: str, headers: list[str], rows: list[list]) -> Response:
    return Response(
        to_csv(headers, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
