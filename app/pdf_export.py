from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Iterable, List, Sequence

from calendar import monthrange

from . import services
from .models import TimeEntry, User, VacationRequest
from .schemas import VacationSummary

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except ImportError as exc:  # pragma: no cover - handled at runtime when dependency missing
    colors = None  # type: ignore[assignment]
    A4 = None  # type: ignore[assignment]
    getSampleStyleSheet = None  # type: ignore[assignment]
    mm = None  # type: ignore[assignment]
    Paragraph = None  # type: ignore[assignment]
    SimpleDocTemplate = None  # type: ignore[assignment]
    Spacer = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    TableStyle = None  # type: ignore[assignment]
    _REPORTLAB_IMPORT_ERROR: Exception | None = exc
else:
    _REPORTLAB_IMPORT_ERROR = None


def _ensure_reportlab() -> None:
    if _REPORTLAB_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Für den PDF-Export wird die Python-Bibliothek 'reportlab' benötigt."
        ) from _REPORTLAB_IMPORT_ERROR


def _format_minutes(value: int) -> str:
    hours, minutes = divmod(int(value), 60)
    return f"{hours:02d}:{minutes:02d}"


def export_time_overview_pdf(
    *,
    user: User,
    selected_month: date,
    entries: Iterable[TimeEntry],
    total_work_minutes: int,
    target_minutes: int,
    vacation_minutes: int,
    overtime_taken_minutes: int,
    total_overtime_minutes: int,
    total_undertime_minutes: int,
    vacation_summary: VacationSummary,
    company_totals: List[dict[str, object]],
    overtime_limit_minutes: int,
    overtime_limit_exceeded: bool,
    overtime_limit_excess_minutes: int,
    overtime_limit_remaining_minutes: int,
    vacations: Iterable[VacationRequest] | None = None,
    holiday_dates: Iterable[date] | None = None,
) -> BytesIO:
    _ensure_reportlab()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    story: List[object] = []
    holiday_date_set = set(holiday_dates or [])

    title = f"Arbeitszeitübersicht – {selected_month.strftime('%m/%Y')}"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 3 * mm))
    footer_left = f"Mitarbeiter: {user.full_name} ({user.username})"
    footer_right = f"Erstellt am: {date.today().strftime('%d.%m.%Y')}"
    story.append(Spacer(1, 5 * mm))

    summary_data = [
        ["Monatliches Soll", f"{_format_minutes(target_minutes)} Std"],
        ["Ist-Stunden", f"{_format_minutes(total_work_minutes)} Std"],
        ["Urlaubsstunden", f"{_format_minutes(vacation_minutes)} Std"],
        ["Überstundenabbau", f"{_format_minutes(overtime_taken_minutes)} Std"],
        ["Überstunden (Monat)", f"{_format_minutes(total_overtime_minutes)} Std"],
    ]
    if overtime_limit_minutes:
        summary_data.append(
            ["Überstundenlimit (Monat)", f"{_format_minutes(overtime_limit_minutes)} Std"]
        )
        if overtime_limit_exceeded:
            summary_data.append(
                ["Limit überschritten", f"{_format_minutes(overtime_limit_excess_minutes)} Std"]
            )
        else:
            summary_data.append(
                ["Verfügbar bis Limit", f"{_format_minutes(overtime_limit_remaining_minutes)} Std"]
            )
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
    story.append(Spacer(1, 5 * mm))

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
        story.append(Spacer(1, 5 * mm))

    entry_data = [["Datum", "Firma", "Start", "Ende", "Arbeitszeit", "Kommentar"]]
    sorted_entries = sorted(entries, key=lambda item: (item.work_date, item.start_time))
    total_minutes = 0
    for entry in sorted_entries:
        end_value = "läuft" if entry.is_open else entry.end_time.strftime("%H:%M")
        company_name = entry.company.name if entry.company else "Allgemeine Arbeitszeit"
        total_minutes += entry.worked_minutes
        entry_data.append(
            [
                entry.work_date.strftime("%d.%m.%Y"),
                company_name,
                entry.start_time.strftime("%H:%M"),
                end_value,
                f"{_format_minutes(entry.worked_minutes)} Std",
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
    ])
    entry_col_widths = [
        doc.width * 0.14,
        doc.width * 0.26,
        doc.width * 0.12,
        doc.width * 0.12,
        doc.width * 0.18,
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

    month_start = selected_month.replace(day=1)
    month_end = date(selected_month.year, selected_month.month, monthrange(selected_month.year, selected_month.month)[1])
    vacation_list = list(vacations or [])
    vacation_rows: list[list[str]] = []
    for vacation in vacation_list:
        overlap_start = max(month_start, vacation.start_date)
        overlap_end = min(month_end, vacation.end_date)
        if overlap_start > overlap_end:
            continue
        credited = services.calculate_required_vacation_minutes(
            vacation.user,
            overlap_start,
            overlap_end,
            holiday_date_set,
        )
        if credited <= 0:
            continue
        label = "Überstundenabbau" if vacation.use_overtime else "Urlaub"
        vacation_rows.append(
            [
                overlap_start.strftime("%d.%m.%Y"),
                overlap_end.strftime("%d.%m.%Y"),
                f"{_format_minutes(credited)} Std",
                label,
            ]
        )
    if vacation_rows:
        vacation_table = Table(
            [["Start", "Ende", "Anzurechnung", "Typ"], *vacation_rows],
            hAlign="LEFT",
        )
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
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("Urlaub im Monat", styles["Heading2"]))
        story.append(vacation_table)

    def _add_footer(canvas, document):  # type: ignore[override]
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


def export_team_overview_pdf(
    *,
    period_label: str,
    period_range: str,
    start_date: date,
    end_date: date,
    total_minutes: int,
    total_entries: int,
    unique_users: int,
    status_summary: Sequence[dict[str, object]],
    company_totals: Sequence[dict[str, object]],
    user_totals: Sequence[dict[str, object]],
    entries: Iterable[TimeEntry],
    vacation_minutes_total: int,
    effective_minutes: int,
    vacations: Iterable[VacationRequest] | None = None,
    holiday_dates: Iterable[date] | None = None,
) -> BytesIO:
    _ensure_reportlab()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    story: List[object] = []
    holiday_date_set = set(holiday_dates or [])

    story.append(Paragraph(f"Team-Zeitübersicht – {period_label}", styles["Title"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"Zeitraum: {period_range}", styles["Normal"]))
    story.append(Paragraph(f"Erstellt am: {date.today().strftime('%d.%m.%Y')}", styles["Normal"]))
    story.append(Spacer(1, 5 * mm))

    summary_data = [
        ["Arbeitszeit (bewertet)", f"{_format_minutes(total_minutes)} Std"],
        ["Effektiv inkl. Urlaub", f"{_format_minutes(effective_minutes)} Std"],
        ["Urlaubsstunden", f"{_format_minutes(vacation_minutes_total)} Std"],
        ["Buchungen gesamt", str(total_entries)],
        ["Mitarbeitende", str(unique_users)],
    ]
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
    story.append(summary_table)
    story.append(Spacer(1, 5 * mm))

    if status_summary:
        status_data = [["Status", "Anzahl"]]
        for item in status_summary:
            status_data.append([str(item.get("label", "")), str(item.get("count", 0))])
        status_table = Table(status_data, hAlign="LEFT")
        status_table.setStyle(
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
        story.append(Paragraph("Statusverteilung", styles["Heading2"]))
        story.append(status_table)
        story.append(Spacer(1, 5 * mm))

    if company_totals:
        company_data = [["Firma", "Buchungen", "Arbeitszeit"]]
        for record in company_totals:
            company_data.append(
                [
                    str(record.get("name", "")),
                    str(record.get("count", 0)),
                    f"{_format_minutes(int(record.get('minutes', 0)))} Std",
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
        story.append(Paragraph("Firmenübersicht", styles["Heading2"]))
        story.append(company_table)
        story.append(Spacer(1, 5 * mm))

    if user_totals:
        user_data = [["Mitarbeiter", "Arbeitszeit", "Buchungen", "Firmen", "Urlaub"]]
        for record in user_totals:
            user_obj = record.get("user")
            companies = record.get("companies", [])
            company_lines = []
            for company in companies:
                label = str(company.get("name", ""))
                minutes = _format_minutes(int(company.get("minutes", 0)))
                count = company.get("count", 0)
                company_lines.append(f"{label}: {minutes} Std ({count})")
            companies_text = "<br/>".join(company_lines) if company_lines else "-"
            user_data.append(
                [
                    str(getattr(user_obj, "full_name", "")),
                    f"{_format_minutes(int(record.get('minutes', 0)))} Std",
                    str(record.get("count", 0)),
                    Paragraph(companies_text, styles["Normal"]),
                    _format_minutes(int(record.get("vacation_minutes", 0))),
                ]
            )
        user_table = Table(
            user_data,
            hAlign="LEFT",
            colWidths=[
                doc.width * 0.24,
                doc.width * 0.18,
                doc.width * 0.12,
                doc.width * 0.28,
                doc.width * 0.18,
            ],
        )
        user_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("VALIGN", (0, 1), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(Paragraph("Mitarbeiterübersicht", styles["Heading2"]))
        story.append(user_table)
        story.append(Spacer(1, 5 * mm))

    entry_data = [["Datum", "Mitarbeiter", "Firma", "Start", "Ende", "Arbeitszeit", "Kommentar"]]
    sorted_entries = sorted(
        entries,
        key=lambda item: (item.work_date, item.start_time, getattr(item.user, "full_name", "")),
    )
    total_entry_minutes = 0
    for entry in sorted_entries:
        total_entry_minutes += entry.worked_minutes
        end_value = "läuft" if entry.is_open else entry.end_time.strftime("%H:%M")
        entry_data.append(
            [
                entry.work_date.strftime("%d.%m.%Y"),
                entry.user.full_name if entry.user else "-",
                entry.company.name if entry.company else "Allgemeine Arbeitszeit",
                entry.start_time.strftime("%H:%M"),
                end_value,
                f"{_format_minutes(entry.worked_minutes)} Std",
                entry.notes or "-",
            ]
        )
    entry_data.append(
        [
            "Summe",
            "",
            "",
            "",
            f"{_format_minutes(total_entry_minutes)} Std",
            "",
        ]
    )
    entry_table = Table(
        entry_data,
        colWidths=[
            doc.width * 0.11,
            doc.width * 0.17,
            doc.width * 0.17,
            doc.width * 0.08,
            doc.width * 0.08,
            doc.width * 0.12,
            doc.width * 0.27,
        ],
        repeatRows=1,
    )
    entry_table.setStyle(
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
    story.append(Paragraph("Einzelbuchungen", styles["Heading2"]))
    story.append(entry_table)

    vacation_list = list(vacations or [])
    if vacation_list:
        vacation_data = [["Mitarbeiter", "Start", "Ende", "Anzurechnung", "Typ", "Kommentar"]]
        for vacation in vacation_list:
            overlap_start = max(start_date, vacation.start_date)
            overlap_end = min(end_date, vacation.end_date)
            if overlap_start > overlap_end:
                continue
            credited = services.calculate_required_vacation_minutes(
                vacation.user,
                overlap_start,
                overlap_end,
                holiday_date_set,
            )
            if credited <= 0:
                continue
            vacation_data.append(
                [
                    vacation.user.full_name if vacation.user else "Unbekannt",
                    overlap_start.strftime("%d.%m.%Y"),
                    overlap_end.strftime("%d.%m.%Y"),
                    f"{_format_minutes(credited)} Std",
                    "Überstundenabbau" if vacation.use_overtime else "Urlaub",
                    vacation.comment or "-",
                ]
            )
        if len(vacation_data) > 1:
            vacation_table = Table(
                vacation_data,
                hAlign="LEFT",
                colWidths=[
                    doc.width * 0.22,
                    doc.width * 0.16,
                    doc.width * 0.16,
                    doc.width * 0.16,
                    doc.width * 0.14,
                    doc.width * 0.16,
                ],
                repeatRows=1,
            )
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
            story.append(Spacer(1, 5 * mm))
            story.append(Paragraph("Urlaub im Zeitraum", styles["Heading2"]))
            story.append(vacation_table)

    doc.build(story)
    buffer.seek(0)
    return buffer
