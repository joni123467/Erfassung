from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Iterable, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import TimeEntry, TimeEntryStatus, User
from .schemas import VacationSummary


def _format_minutes(value: int) -> str:
    hours, minutes = divmod(int(value), 60)
    return f"{hours:02d}:{minutes:02d}"


def _status_label(status: str) -> str:
    if status == TimeEntryStatus.APPROVED:
        return "Freigegeben"
    if status == TimeEntryStatus.PENDING:
        return "Wartet auf Freigabe"
    if status == TimeEntryStatus.REJECTED:
        return "Abgelehnt"
    return status.title()


def export_time_overview_pdf(
    *,
    user: User,
    selected_month: date,
    entries: Iterable[TimeEntry],
    total_work_minutes: int,
    target_minutes: int,
    overtime_taken_minutes: int,
    total_overtime_minutes: int,
    total_undertime_minutes: int,
    vacation_summary: VacationSummary,
    company_totals: List[dict[str, object]],
) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    story: List[object] = []

    title = f"Arbeitszeitübersicht – {selected_month.strftime('%m/%Y')}"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 4 * mm))
    footer_left = f"Mitarbeiter: {user.full_name} ({user.username})"
    footer_right = f"Erstellt am: {date.today().strftime('%d.%m.%Y')}"
    story.append(Spacer(1, 6 * mm))

    summary_data = [
        ["Monatliches Soll", f"{_format_minutes(target_minutes)} Std"],
        ["Ist-Stunden", f"{_format_minutes(total_work_minutes)} Std"],
        ["Überstundenabbau", f"{_format_minutes(overtime_taken_minutes)} Std"],
        ["Überstunden (Monat)", f"{_format_minutes(total_overtime_minutes)} Std"],
    ]
    if user.time_account_enabled:
        summary_data.append(["Minusstunden", f"{_format_minutes(total_undertime_minutes)} Std"])
    summary_table = Table(summary_data, hAlign="LEFT")
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    vacation_data = [
        ["Gesamturlaub", f"{vacation_summary.total_days:.2f} Tage"],
        ["Verbraucht", f"{vacation_summary.used_days:.2f} Tage"],
        ["Geplant", f"{vacation_summary.planned_days:.2f} Tage"],
        ["Resturlaub", f"{vacation_summary.remaining_days:.2f} Tage"],
    ]
    if vacation_summary.carryover_days > 0:
        vacation_data.insert(1, ["Übertrag", f"{vacation_summary.carryover_days:.2f} Tage"])
    vacation_table = Table(vacation_data, hAlign="LEFT")
    vacation_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    story.append(Paragraph("Arbeitszeitkennzahlen & Urlaub", styles["Heading2"]))
    metrics_table = Table(
        [[summary_table, vacation_table]],
        colWidths=[doc.width / 2, doc.width / 2],
        hAlign="LEFT",
    )
    metrics_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 12),
                ("LEFTPADDING", (1, 0), (1, -1), 12),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
            ]
        )
    )
    story.append(metrics_table)
    story.append(Spacer(1, 6 * mm))

    if company_totals:
        company_data = [["Firma", "Arbeitszeit", "Buchungen"]]
        for record in company_totals:
            company_data.append(
                [
                    str(record["name"]),
                    f"{_format_minutes(int(record["minutes"]))} Std",
                    str(record["count"]),
                ]
            )
        company_table = Table(company_data, hAlign="LEFT")
        company_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story.append(Paragraph("Firmenübersicht (freigegeben)", styles["Heading2"]))
        story.append(company_table)
        story.append(Spacer(1, 6 * mm))

    entry_data = [["Datum", "Firma", "Start", "Ende", "Arbeitszeit", "Status", "Kommentar"]]
    sorted_entries = sorted(entries, key=lambda item: (item.work_date, item.start_time))
    total_minutes = 0
    for entry in sorted_entries:
        end_value = "läuft" if entry.is_open else entry.end_time.strftime("%H:%M")
        company_name = entry.company.name if entry.company else "Allgemein"
        total_minutes += entry.worked_minutes
        entry_data.append(
            [
                entry.work_date.strftime("%d.%m.%Y"),
                company_name,
                entry.start_time.strftime("%H:%M"),
                end_value,
                f"{_format_minutes(entry.worked_minutes)} Std",
                _status_label(entry.status),
                entry.notes or "-",
            ]
        )
    entry_data.append([
        "Summe",
        "",
        "",
        "",
        f"{_format_minutes(total_minutes)} Std",
        "",
        "",
    ])
    entry_col_widths = [
        doc.width * 0.12,
        doc.width * 0.2,
        doc.width * 0.1,
        doc.width * 0.1,
        doc.width * 0.15,
        doc.width * 0.15,
        doc.width * 0.18,
    ]
    entry_table = Table(entry_data, colWidths=entry_col_widths, repeatRows=1)
    entry_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.whitesmoke]),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (2, 1), (4, -2), "CENTER"),
                ("SPAN", (0, -1), (3, -1)),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2ff")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (4, -1), (4, -1), "CENTER"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(Paragraph("Zeitbuchungen (Monat)", styles["Heading2"]))
    story.append(entry_table)

    def _add_footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        y_position = 12 * mm
        canvas.drawString(document.leftMargin, y_position, footer_left)
        right_width = canvas.stringWidth(footer_right, "Helvetica", 9)
        canvas.drawString(document.pagesize[0] - document.rightMargin - right_width, y_position, footer_right)
        canvas.restoreState()

    doc.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
    buffer.seek(0)
    return buffer
