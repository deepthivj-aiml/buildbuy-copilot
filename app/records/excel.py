"""Shortlist Excel export — pure, no database.

``shortlist_to_excel`` turns the ranked shortlist rows the user sees
on the Suppliers & Twin tab into a real ``.xlsx`` file (openpyxl):
one row per shortlisted supplier, with cost, quality + evidence,
lead time, MOQ and contact details where held. The same rows the UI
shows — nothing stored, nothing invented; a supplier with no phone
or address exports an empty cell, never a guessed value.
"""

from __future__ import annotations

import io

SHORTLIST_COLUMNS = [
    "Rank",
    "Supplier",
    "Location",
    "Distance (mi)",
    "Unit price ($)",
    "Quantity",
    "Goods ($)",
    "Transport ($)",
    "Taxes/fees ($)",
    "Landed cost ($)",
    "Landed cost label",
    "Quality /100",
    "Quality evidence",
    "Lead time (days)",
    "MOQ",
    "Best value",
    "Cheapest",
    "Highest quality",
    "Official email",
    "Phone",
    "Address",
    "Contact source",
]


def _num(value):
    return value if isinstance(value, (int, float)) else None


def shortlist_to_excel(rows, requirement=None, delivery_location: str = "") -> bytes:
    """Build the .xlsx bytes for the ranked shortlist.

    ``rows`` are the ranked rows from ``rank_suppliers`` (frontend
    helper) or ``search_suppliers`` (backend) — dicts with the keys
    the Suppliers tab shows. ``requirement`` adds a title block
    (item / quantity / location / budget) at the top when given.
    Returns the file as bytes; the caller offers it as a download.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Shortlist"
    row_no = 1
    req = requirement or {}
    if req.get("item"):
        ws.cell(row=row_no, column=1,
               value=f"BuildBuy Copilot — shortlisted suppliers: "
                     f"{req.get('quantity', '')} x {req.get('item', '')}"
                     + (f", delivery to {req['location']}" if req.get("location") else "")
                     + (f", max budget ${req['budget']}" if req.get("budget") else ""))
        ws.cell(row=row_no, column=1).font = Font(bold=True, size=12)
        row_no += 1
        ws.cell(row=row_no, column=1,
               value=("Live data only — computed in this session from your "
                      "requirement. Quantities are estimates, not surveyed "
                      "quantities. Supplier records are synthetic demo records "
                      "until a real supplier directory is connected."))
        row_no += 2
    header_row = row_no
    for col, name in enumerate(SHORTLIST_COLUMNS, start=1):
        cell = ws.cell(row=header_row, column=col, value=name)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    data = sorted(rows or [],
                  key=lambda r: (r.get("value_rank") is None, r.get("value_rank")))
    qty = req.get("quantity") or 0
    for r in data:
        row_no += 1
        bd = r.get("landed_breakdown") or {}
        flags = {
            "Best value": "Yes" if r.get("is_best_value") else "",
            "Cheapest": "Yes" if r.get("is_cheapest") else "",
            "Highest quality": "Yes" if r.get("is_best_quality") else "",
        }
        evidence = r.get("quality_evidence") or []
        if isinstance(evidence, list):
            evidence = "; ".join(str(e) for e in evidence)
        transport = r.get("transport")
        values = [
            r.get("value_rank"),
            r.get("name"),
            r.get("location"),
            r.get("distance_mi"),
            _num(r.get("unit_price")),
            qty,
            _num(bd.get("goods")),
            _num(transport),
            _num(bd.get("taxes_fees")),
            _num(r.get("landed")),
            r.get("landed_label") or "",
            r.get("quality_score"),
            evidence,
            r.get("lead_days"),
            r.get("moq"),
            flags["Best value"],
            flags["Cheapest"],
            flags["Highest quality"],
            (r.get("email") or _extract_email(r)),
            r.get("phone") or "",
            r.get("address") or "",
            r.get("contact_source") or "",
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row_no, column=col, value=value)
            if isinstance(value, (int, float)):
                cell.number_format = '#,##0.00'
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    widths = {"A": 6, "B": 26, "C": 18, "D": 12, "E": 12, "F": 9, "G": 11,
              "H": 12, "I": 12, "J": 13, "K": 14, "L": 11, "M": 60,
              "N": 14, "O": 8, "P": 10, "Q": 10, "R": 13, "S": 30,
              "T": 14, "U": 22, "V": 22}
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _extract_email(row: dict) -> str:
    """Official email from a shortlist row, or "" when not held."""
    import re
    for key in ("email", "contact"):
        value = str(row.get(key) or "")
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)
        if m:
            return m.group(0)
    return ""
