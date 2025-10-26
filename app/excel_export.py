from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Iterable, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from . import services
from .models import TimeEntry, VacationRequest


def export_time_entries(
    entries: Iterable[TimeEntry],
    vacations: Optional[Iterable[VacationRequest]] = None,
    *,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Arbeitszeiten"

    headers = [
        "Mitarbeiter",
        "Firma",
        "Datum",
        "Start",
        "Ende",
        "Pause (Min)",
        "Arbeitszeit (Min)",
        "Überstunden (Min)",
        "Kommentar",
    ]
    ws.append(headers)

    header_font = Font(bold=True)
    for cell in ws[1]:
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for entry in entries:
        end_value = "läuft" if entry.is_open else entry.end_time.strftime("%H:%M")
        ws.append(
            [
                entry.user.full_name if entry.user else "",
                entry.company.name if entry.company else "",
                entry.work_date.strftime("%d.%m.%Y"),
                entry.start_time.strftime("%H:%M"),
                end_value,
                entry.total_break_minutes,
                entry.worked_minutes,
                entry.overtime_minutes,
                entry.notes,
            ]
        )

    for column_cells in ws.columns:
        max_length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
        adjusted_width = max_length + 2
        ws.column_dimensions[column_cells[0].column_letter].width = adjusted_width

    vacation_list = list(vacations or [])
    if vacation_list:
        vacation_ws = wb.create_sheet(title="Urlaub")
        vacation_ws.append(["Start", "Ende", "Anzurechnung (Min)", "Typ", "Kommentar"])
        for cell in vacation_ws[1]:
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        for vacation in vacation_list:
            start_date = max(period_start or vacation.start_date, vacation.start_date)
            end_date = min(period_end or vacation.end_date, vacation.end_date)
            credited = services.calculate_required_vacation_minutes(
                vacation.user,
                start_date,
                end_date,
            )
            if credited <= 0:
                continue
            vacation_ws.append(
                [
                    start_date.strftime("%d.%m.%Y"),
                    end_date.strftime("%d.%m.%Y"),
                    credited,
                    "Überstundenabbau" if vacation.use_overtime else "Urlaub",
                    vacation.comment or "",
                ]
            )
        for column_cells in vacation_ws.columns:
            max_length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
            adjusted_width = max_length + 2
            vacation_ws.column_dimensions[column_cells[0].column_letter].width = adjusted_width

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
