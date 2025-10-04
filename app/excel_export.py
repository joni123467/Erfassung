from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from .models import TimeEntry


def export_time_entries(entries: Iterable[TimeEntry]) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Arbeitszeiten"

    headers = [
        "Mitarbeiter",
        "Datum",
        "Start",
        "Ende",
        "Pause (Min)",
        "Arbeitszeit (Min)",
        "Überstunden (Min)",
        "Notiz",
    ]
    ws.append(headers)

    header_font = Font(bold=True)
    for cell in ws[1]:
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for entry in entries:
        ws.append(
            [
                entry.user.full_name if entry.user else "",
                entry.work_date.strftime("%d.%m.%Y"),
                entry.start_time.strftime("%H:%M"),
                entry.end_time.strftime("%H:%M"),
                entry.break_minutes,
                entry.worked_minutes,
                entry.overtime_minutes,
                entry.notes,
            ]
        )

    for column_cells in ws.columns:
        max_length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
        adjusted_width = max_length + 2
        ws.column_dimensions[column_cells[0].column_letter].width = adjusted_width

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
