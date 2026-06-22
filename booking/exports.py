"""Kleine Export-Helfer: Tabellen als CSV oder Excel (xlsx) ausliefern.

Bewusst dünn gehalten – nur Spaltenköpfe + Zeilen rein, fertige HttpResponse
raus. Beides, weil CSV sich gut weiterverarbeiten lässt (Buchhaltung/Abgleich)
und xlsx fürs Ansehen/Drucken bequemer ist.
"""
from __future__ import annotations

import csv

from django.http import HttpResponse


def csv_response(filename: str, columns, rows) -> HttpResponse:
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    resp.write("﻿")  # BOM, damit Excel Umlaute/UTF-8 erkennt
    writer = csv.writer(resp, delimiter=";")
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow(list(row))
    return resp


def xlsx_response(filename: str, title: str, columns, rows) -> HttpResponse:
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (title or "Export")[:31]
    ws.append(list(columns))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(list(row))
    ws.freeze_panes = "A2"
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    wb.save(resp)
    return resp


def table_response(fmt: str, filename: str, title: str, columns, rows) -> HttpResponse:
    """Wählt nach Format (\"csv\"/\"xlsx\") die passende Antwort."""
    rows = list(rows)
    if fmt == "csv":
        return csv_response(filename, columns, rows)
    return xlsx_response(filename, title, columns, rows)
