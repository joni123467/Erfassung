from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
from typing import Iterable, List, Sequence
from xml.sax.saxutils import escape

from calendar import monthrange

from . import services
from .models import TimeEntry, TimeEntryStatus, User, VacationRequest, VacationStatus
from .schemas import VacationSummary

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except ImportError as exc:  # pragma: no cover - handled at runtime when dependency missing
    colors = None  # type: ignore[assignment]
    TA_CENTER = TA_LEFT = TA_RIGHT = None  # type: ignore[assignment]
    A4 = None  # type: ignore[assignment]
    ParagraphStyle = None  # type: ignore[assignment]
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


def _format_signed_minutes(value: int) -> str:
    minutes = int(value)
    sign = "-" if minutes < 0 else ""
    hours, remainder = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{remainder:02d}"


def _status_label(status: str) -> str:
    if status == TimeEntryStatus.APPROVED:
        return "Freigegeben"
    if status == TimeEntryStatus.PENDING:
        return "Wartet auf Freigabe"
    if status == TimeEntryStatus.REJECTED:
        return "Abgelehnt"
    return status.title()


_VACATION_STATUS_LABELS = {
    VacationStatus.PENDING: "Offen",
    VacationStatus.APPROVED: "Genehmigt",
    VacationStatus.REJECTED: "Abgelehnt",
    VacationStatus.WITHDRAW_REQUESTED: "Rücknahme angefragt",
    VacationStatus.CANCELLED: "Storniert",
}


def _vacation_status_label(status: str) -> str:
    return _VACATION_STATUS_LABELS.get(status, str(status).title())


def _workdays(start: date, end: date) -> int:
    current = start
    total = 0
    while current <= end:
        if current.weekday() < 5:
            total += 1
        current += timedelta(days=1)
    return total


# ── Shared layout system ─────────────────────────────────────────────────────
# Every table cell is rendered as a Paragraph so long content WRAPS inside its
# column instead of overflowing into the neighbour cell (the root cause of the
# previous overlap/cut-off issues). Compact margins, font sizes and paddings
# raise the information density without sacrificing readability.

_MARGIN_X = 14
_MARGIN_TOP = 12
_MARGIN_BOTTOM = 16

_COLOR_TEXT = "#0f172a"
_COLOR_MUTED = "#64748b"
_COLOR_HEAD_BG = "#eef2f7"
_COLOR_STRIPE = "#f8fafc"
_COLOR_GRID = "#cbd5e1"
_COLOR_FRAME = "#94a3b8"


def _build_styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor(_COLOR_TEXT))
    bold = dict(base, fontName="Helvetica-Bold")
    return {
        "title": ParagraphStyle(
            "ReportTitle", fontName="Helvetica-Bold", fontSize=15, leading=18,
            textColor=colors.HexColor(_COLOR_TEXT),
        ),
        "meta": ParagraphStyle(
            "ReportMeta", fontName="Helvetica", fontSize=8.5, leading=11,
            textColor=colors.HexColor(_COLOR_MUTED),
        ),
        "h2": ParagraphStyle(
            "ReportH2", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
            spaceBefore=8, spaceAfter=3, textColor=colors.HexColor(_COLOR_TEXT),
        ),
        "cell": ParagraphStyle("Cell", **base),
        "cell_c": ParagraphStyle("CellC", alignment=TA_CENTER, **base),
        "cell_r": ParagraphStyle("CellR", alignment=TA_RIGHT, **base),
        "cell_b": ParagraphStyle("CellB", **bold),
        "cell_bc": ParagraphStyle("CellBC", alignment=TA_CENTER, **bold),
        "cell_br": ParagraphStyle("CellBR", alignment=TA_RIGHT, **bold),
    }


def _p(value: object, style: ParagraphStyle) -> Paragraph:
    text = escape(str(value)) if not isinstance(value, Paragraph) else None
    return Paragraph(text, style) if text is not None else value  # type: ignore[return-value]


def _cell_style(styles: dict, align: str, bold: bool) -> ParagraphStyle:
    key = {"L": "cell", "C": "cell_c", "R": "cell_r"}[align]
    if bold:
        key = {"L": "cell_b", "C": "cell_bc", "R": "cell_br"}[align]
    return styles[key]


def _table_style(*, header: bool = True, last_row_total: bool = False) -> TableStyle:
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor(_COLOR_GRID)),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(_COLOR_FRAME)),
    ]
    body_start = 1 if header else 0
    body_end = -2 if last_row_total else -1
    commands.append(
        ("ROWBACKGROUNDS", (0, body_start), (-1, body_end), [colors.white, colors.HexColor(_COLOR_STRIPE)])
    )
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_COLOR_HEAD_BG)))
    if last_row_total:
        commands.extend(
            [
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(_COLOR_HEAD_BG)),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor(_COLOR_FRAME)),
            ]
        )
    return TableStyle(commands)


def _data_table(
    styles: dict,
    *,
    header: Sequence[str],
    rows: Sequence[Sequence[object]],
    fractions: Sequence[float],
    aligns: Sequence[str],
    doc_width: float,
    total_row: Sequence[object] | None = None,
    total_span: int = 0,
) -> Table:
    data: list[list[object]] = [
        [_p(value, _cell_style(styles, aligns[idx], bold=True)) for idx, value in enumerate(header)]
    ]
    for row in rows:
        data.append([_p(value, _cell_style(styles, aligns[idx], bold=False)) for idx, value in enumerate(row)])
    if total_row is not None:
        data.append(
            [_p(value, _cell_style(styles, aligns[idx], bold=True)) for idx, value in enumerate(total_row)]
        )
    table = Table(
        data,
        colWidths=[doc_width * fraction for fraction in fractions],
        repeatRows=1,
        hAlign="LEFT",
    )
    style = _table_style(header=True, last_row_total=total_row is not None)
    if total_row is not None and total_span > 1:
        style.add("SPAN", (0, -1), (total_span - 1, -1))
    table.setStyle(style)
    return table


def _kv_table(styles: dict, rows: Sequence[Sequence[str]], width: float) -> Table:
    data = [
        [_p(label, styles["cell_b"]), _p(value, styles["cell_r"])]
        for label, value in rows
    ]
    table = Table(data, colWidths=[width * 0.58, width * 0.42], hAlign="LEFT")
    table.setStyle(_table_style(header=False))
    return table


def _side_by_side(left: Table, right: Table, doc_width: float, gap: float = 12) -> Table:
    wrapper = Table([[left, right]], colWidths=[doc_width / 2, doc_width / 2], hAlign="LEFT")
    wrapper.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), gap / 2),
                ("LEFTPADDING", (1, 0), (1, -1), gap / 2),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return wrapper


def _vacation_overview_rows(
    vacations: Iterable[VacationRequest],
    start: date,
    end: date,
    *,
    include_user: bool,
) -> list[list[str]]:
    rows: list[list[str]] = []
    ordered = sorted(vacations, key=lambda item: (item.start_date, item.end_date))
    for vacation in ordered:
        overlap_start = max(start, vacation.start_date)
        overlap_end = min(end, vacation.end_date)
        if overlap_start > overlap_end:
            continue
        days = _workdays(overlap_start, overlap_end)
        vacation_type = "Überstundenabbau" if vacation.use_overtime else "Urlaub"
        if vacation.status == VacationStatus.APPROVED:
            credited = services.calculate_required_vacation_minutes(
                vacation.user, overlap_start, overlap_end
            )
            credited_label = f"{_format_minutes(credited)} Std"
        else:
            credited_label = "–"
        row = []
        if include_user:
            row.append(vacation.user.full_name if vacation.user else "Unbekannt")
        row.extend(
            [
                f"{overlap_start.strftime('%d.%m.%Y')} – {overlap_end.strftime('%d.%m.%Y')}",
                vacation_type,
                _vacation_status_label(vacation.status),
                str(days),
                credited_label,
                vacation.comment or "–",
            ]
        )
        rows.append(row)
    return rows


def _truncate_to_width(canvas, text: str, max_width: float, font: str, size: float) -> str:
    if canvas.stringWidth(text, font, size) <= max_width:
        return text
    while text and canvas.stringWidth(text + "…", font, size) > max_width:
        text = text[:-1]
    return text + "…"


def _page_footer(left_text: str, right_text: str):
    def draw(canvas, document):  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor(_COLOR_MUTED))
        y_position = 9 * mm
        # keep the left slot clear of the centred page number
        max_left = document.pagesize[0] / 2 - 14 * mm - document.leftMargin
        canvas.drawString(
            document.leftMargin,
            y_position,
            _truncate_to_width(canvas, left_text, max_left, "Helvetica", 7.5),
        )
        canvas.drawCentredString(document.pagesize[0] / 2, y_position, f"Seite {canvas.getPageNumber()}")
        canvas.drawRightString(document.pagesize[0] - document.rightMargin, y_position, right_text)
        canvas.restoreState()

    return draw


def _make_doc(buffer: BytesIO) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN_X * mm,
        rightMargin=_MARGIN_X * mm,
        topMargin=_MARGIN_TOP * mm,
        bottomMargin=_MARGIN_BOTTOM * mm,
    )


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
) -> BytesIO:
    _ensure_reportlab()

    buffer = BytesIO()
    doc = _make_doc(buffer)
    styles = _build_styles()
    story: List[object] = []

    month_start = selected_month.replace(day=1)
    month_end = date(
        selected_month.year,
        selected_month.month,
        monthrange(selected_month.year, selected_month.month)[1],
    )

    story.append(Paragraph(f"Arbeitszeitübersicht – {selected_month.strftime('%m/%Y')}", styles["title"]))
    meta_line = (
        f"Mitarbeiter: {escape(user.full_name)} ({escape(user.username)})"
        f" &nbsp;·&nbsp; Zeitraum: {month_start.strftime('%d.%m.%Y')} – {month_end.strftime('%d.%m.%Y')}"
        f" &nbsp;·&nbsp; Erstellt am: {date.today().strftime('%d.%m.%Y')}"
    )
    story.append(Paragraph(meta_line, styles["meta"]))
    story.append(Spacer(1, 3 * mm))

    summary_rows = [
        ["Monatliches Soll", f"{_format_minutes(target_minutes)} Std"],
        ["Ist-Stunden", f"{_format_minutes(total_work_minutes)} Std"],
        ["Urlaubsstunden", f"{_format_minutes(vacation_minutes)} Std"],
        ["Überstundenabbau", f"{_format_minutes(overtime_taken_minutes)} Std"],
        ["Überstunden (Monat)", f"{_format_minutes(total_overtime_minutes)} Std"],
    ]
    if overtime_limit_minutes:
        summary_rows.append(
            ["Überstundenlimit (Monat)", f"{_format_minutes(overtime_limit_minutes)} Std"]
        )
        if overtime_limit_exceeded:
            summary_rows.append(
                ["Limit überschritten", f"{_format_minutes(overtime_limit_excess_minutes)} Std"]
            )
        else:
            summary_rows.append(
                ["Verfügbar bis Limit", f"{_format_minutes(overtime_limit_remaining_minutes)} Std"]
            )
    if user.time_account_enabled:
        summary_rows.append(["Minusstunden", f"{_format_minutes(total_undertime_minutes)} Std"])

    vacation_kv_rows = [
        ["Gesamturlaub", f"{vacation_summary.total_days:.2f} Tage"],
        ["Verbraucht", f"{vacation_summary.used_days:.2f} Tage"],
        ["Geplant", f"{vacation_summary.planned_days:.2f} Tage"],
        ["Resturlaub", f"{vacation_summary.remaining_days:.2f} Tage"],
    ]
    if vacation_summary.carryover_days > 0:
        vacation_kv_rows.insert(1, ["Übertrag", f"{vacation_summary.carryover_days:.2f} Tage"])

    half_width = doc.width / 2 - 6
    story.append(Paragraph("Arbeitszeitkennzahlen & Urlaubskonto", styles["h2"]))
    story.append(
        _side_by_side(
            _kv_table(styles, summary_rows, half_width),
            _kv_table(styles, vacation_kv_rows, half_width),
            doc.width,
        )
    )

    if company_totals:
        story.append(Paragraph("Firmenübersicht (freigegeben)", styles["h2"]))
        story.append(
            _data_table(
                styles,
                header=["Firma", "Arbeitszeit", "Buchungen"],
                rows=[
                    [
                        str(record["name"]),
                        f"{_format_minutes(int(record['minutes']))} Std",
                        str(record["count"]),
                    ]
                    for record in company_totals
                ],
                fractions=[0.60, 0.22, 0.18],
                aligns=["L", "R", "R"],
                doc_width=doc.width,
            )
        )

    sorted_entries = sorted(entries, key=lambda item: (item.work_date, item.start_time))
    entry_rows: list[list[str]] = []
    total_minutes = 0
    for entry in sorted_entries:
        end_value = "läuft" if entry.is_open else entry.end_time.strftime("%H:%M")
        company_name = entry.company.name if entry.company else "Allgemeine Arbeitszeit"
        total_minutes += entry.worked_minutes
        entry_rows.append(
            [
                entry.work_date.strftime("%d.%m.%Y"),
                company_name,
                entry.start_time.strftime("%H:%M"),
                end_value,
                f"{_format_minutes(entry.worked_minutes)} Std",
                _status_label(entry.status),
                entry.notes or "–",
            ]
        )
    story.append(Paragraph("Zeitbuchungen (Monat)", styles["h2"]))
    story.append(
        _data_table(
            styles,
            header=["Datum", "Firma", "Start", "Ende", "Arbeitszeit", "Status", "Kommentar"],
            rows=entry_rows,
            fractions=[0.105, 0.205, 0.065, 0.065, 0.10, 0.14, 0.32],
            aligns=["L", "L", "C", "C", "R", "L", "L"],
            doc_width=doc.width,
            total_row=["Summe", "", "", "", f"{_format_minutes(total_minutes)} Std", "", ""],
            total_span=4,
        )
    )

    vacation_rows = _vacation_overview_rows(
        vacations or [], month_start, month_end, include_user=False
    )
    story.append(Paragraph("Urlaubsübersicht (Monat)", styles["h2"]))
    if vacation_rows:
        story.append(
            _data_table(
                styles,
                header=["Zeitraum", "Typ", "Status", "Tage", "Anzurechnung", "Kommentar"],
                rows=vacation_rows,
                fractions=[0.25, 0.15, 0.15, 0.07, 0.13, 0.25],
                aligns=["L", "L", "L", "C", "R", "L"],
                doc_width=doc.width,
            )
        )
    else:
        story.append(Paragraph("Keine Urlaubsanträge im Zeitraum.", styles["meta"]))

    footer = _page_footer(
        f"Mitarbeiter: {user.full_name} ({user.username})",
        f"Erstellt am: {date.today().strftime('%d.%m.%Y')}",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer


def export_user_summary_pdf(
    *,
    period_range: str,
    rows: Sequence[dict[str, object]],
    totals: dict[str, int],
) -> BytesIO:
    """Per-user evaluation: one row per selected user, layout consistent
    with the other reports (same style system)."""
    _ensure_reportlab()

    buffer = BytesIO()
    doc = _make_doc(buffer)
    styles = _build_styles()
    story: List[object] = []

    story.append(Paragraph("Benutzerauswertung – Zeitübersicht", styles["title"]))
    meta_line = (
        f"Zeitraum: {escape(period_range)}"
        f" &nbsp;·&nbsp; Benutzer: {len(rows)}"
        f" &nbsp;·&nbsp; Erstellt am: {date.today().strftime('%d.%m.%Y')}"
    )
    story.append(Paragraph(meta_line, styles["meta"]))
    story.append(Spacer(1, 3 * mm))

    table_rows: list[list[str]] = []
    for row in rows:
        row_user = row.get("user")
        full_name = str(getattr(row_user, "full_name", "")) or "–"
        username = str(getattr(row_user, "username", ""))
        label = f"{full_name} ({username})" if username else full_name
        table_rows.append(
            [
                label,
                str(row.get("count", 0)),
                f"{_format_minutes(int(row.get('work_minutes', 0)))} Std",
                f"{_format_minutes(int(row.get('break_minutes', 0)))} Std",
                f"{_format_minutes(int(row.get('target_minutes', 0)))} Std",
                f"{_format_minutes(int(row.get('vacation_minutes', 0)))} Std",
                f"{_format_signed_minutes(int(row.get('balance_minutes', 0)))} Std",
            ]
        )
    story.append(Paragraph("Übersicht je Benutzer", styles["h2"]))
    story.append(
        _data_table(
            styles,
            header=["Benutzer", "Buchungen", "Arbeitszeit", "Pausen", "Soll", "Urlaub", "Über-/Minusstd."],
            rows=table_rows,
            fractions=[0.285, 0.105, 0.13, 0.11, 0.12, 0.11, 0.14],
            aligns=["L", "R", "R", "R", "R", "R", "R"],
            doc_width=doc.width,
            total_row=[
                "Summe",
                str(totals.get("count", 0)),
                f"{_format_minutes(int(totals.get('work_minutes', 0)))} Std",
                f"{_format_minutes(int(totals.get('break_minutes', 0)))} Std",
                f"{_format_minutes(int(totals.get('target_minutes', 0)))} Std",
                f"{_format_minutes(int(totals.get('vacation_minutes', 0)))} Std",
                f"{_format_signed_minutes(int(totals.get('balance_minutes', 0)))} Std",
            ],
            total_span=1,
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "Arbeitszeit/Pausen aus freigegebenen Buchungen; Soll = Arbeitstage (Mo–Fr) × Tagessoll; "
            "Urlaub = angerechnete genehmigte Urlaubsstunden; Über-/Minusstunden = Arbeitszeit + Urlaub − Soll.",
            styles["meta"],
        )
    )

    footer = _page_footer(
        "Benutzerauswertung – Zeitübersicht",
        f"Erstellt am: {date.today().strftime('%d.%m.%Y')}",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
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
) -> BytesIO:
    _ensure_reportlab()

    buffer = BytesIO()
    doc = _make_doc(buffer)
    styles = _build_styles()
    story: List[object] = []

    story.append(Paragraph(f"Team-Zeitübersicht – {escape(period_label)}", styles["title"]))
    meta_line = (
        f"Zeitraum: {escape(period_range)}"
        f" &nbsp;·&nbsp; Erstellt am: {date.today().strftime('%d.%m.%Y')}"
    )
    story.append(Paragraph(meta_line, styles["meta"]))
    story.append(Spacer(1, 3 * mm))

    summary_rows = [
        ["Arbeitszeit (bewertet)", f"{_format_minutes(total_minutes)} Std"],
        ["Effektiv inkl. Urlaub", f"{_format_minutes(effective_minutes)} Std"],
        ["Urlaubsstunden", f"{_format_minutes(vacation_minutes_total)} Std"],
        ["Buchungen gesamt", str(total_entries)],
        ["Mitarbeitende", str(unique_users)],
    ]
    half_width = doc.width / 2 - 6
    summary_table = _kv_table(styles, summary_rows, half_width)
    if status_summary:
        status_table = _data_table(
            styles,
            header=["Status", "Anzahl"],
            rows=[
                [str(item.get("label", "")), str(item.get("count", 0))]
                for item in status_summary
            ],
            fractions=[0.34, 0.14],
            aligns=["L", "R"],
            doc_width=doc.width,
        )
        story.append(Paragraph("Zusammenfassung & Statusverteilung", styles["h2"]))
        story.append(_side_by_side(summary_table, status_table, doc.width))
    else:
        story.append(Paragraph("Zusammenfassung", styles["h2"]))
        story.append(summary_table)

    if company_totals:
        story.append(Paragraph("Firmenübersicht", styles["h2"]))
        story.append(
            _data_table(
                styles,
                header=["Firma", "Buchungen", "Arbeitszeit"],
                rows=[
                    [
                        str(record.get("name", "")),
                        str(record.get("count", 0)),
                        f"{_format_minutes(int(record.get('minutes', 0)))} Std",
                    ]
                    for record in company_totals
                ],
                fractions=[0.60, 0.18, 0.22],
                aligns=["L", "R", "R"],
                doc_width=doc.width,
            )
        )

    if user_totals:
        user_rows: list[list[object]] = []
        for record in user_totals:
            user_obj = record.get("user")
            companies = record.get("companies", [])
            company_lines = []
            for company in companies:
                label = escape(str(company.get("name", "")))
                minutes = _format_minutes(int(company.get("minutes", 0)))
                count = company.get("count", 0)
                company_lines.append(f"{label}: {minutes} Std ({count})")
            companies_text = "<br/>".join(company_lines) if company_lines else "–"
            user_rows.append(
                [
                    str(getattr(user_obj, "full_name", "")),
                    f"{_format_minutes(int(record.get('minutes', 0)))} Std",
                    str(record.get("count", 0)),
                    Paragraph(companies_text, styles["cell"]),
                    f"{_format_minutes(int(record.get('vacation_minutes', 0)))} Std",
                ]
            )
        story.append(Paragraph("Mitarbeiterübersicht", styles["h2"]))
        story.append(
            _data_table(
                styles,
                header=["Mitarbeiter", "Arbeitszeit", "Buchungen", "Firmen", "Urlaub"],
                rows=user_rows,
                fractions=[0.21, 0.12, 0.11, 0.43, 0.13],
                aligns=["L", "R", "C", "L", "R"],
                doc_width=doc.width,
            )
        )

    sorted_entries = sorted(
        entries,
        key=lambda item: (item.work_date, item.start_time, getattr(item.user, "full_name", "")),
    )
    entry_rows = []
    total_entry_minutes = 0
    for entry in sorted_entries:
        total_entry_minutes += entry.worked_minutes
        end_value = "läuft" if entry.is_open else entry.end_time.strftime("%H:%M")
        entry_rows.append(
            [
                entry.work_date.strftime("%d.%m.%Y"),
                entry.user.full_name if entry.user else "–",
                entry.company.name if entry.company else "Allgemeine Arbeitszeit",
                entry.start_time.strftime("%H:%M"),
                end_value,
                f"{_format_minutes(entry.worked_minutes)} Std",
                _status_label(entry.status),
                "Manuell" if entry.is_manual else "Automatisch",
                entry.notes or "–",
            ]
        )
    story.append(Paragraph("Einzelbuchungen", styles["h2"]))
    story.append(
        _data_table(
            styles,
            header=[
                "Datum", "Mitarbeiter", "Firma", "Start", "Ende",
                "Dauer", "Status", "Quelle", "Kommentar",
            ],
            rows=entry_rows,
            fractions=[0.095, 0.13, 0.13, 0.057, 0.057, 0.11, 0.105, 0.105, 0.211],
            aligns=["L", "L", "L", "C", "C", "R", "L", "L", "L"],
            doc_width=doc.width,
            total_row=[
                "Summe", "", "", "", "",
                f"{_format_minutes(total_entry_minutes)} Std", "", "", "",
            ],
            total_span=5,
        )
    )

    vacation_rows = _vacation_overview_rows(
        vacations or [], start_date, end_date, include_user=True
    )
    story.append(Paragraph("Urlaubsübersicht (Zeitraum)", styles["h2"]))
    if vacation_rows:
        story.append(
            _data_table(
                styles,
                header=["Mitarbeiter", "Zeitraum", "Typ", "Status", "Tage", "Anzurechnung", "Kommentar"],
                rows=vacation_rows,
                fractions=[0.16, 0.21, 0.12, 0.12, 0.06, 0.13, 0.20],
                aligns=["L", "L", "L", "L", "C", "R", "L"],
                doc_width=doc.width,
            )
        )
    else:
        story.append(Paragraph("Keine Urlaubsanträge im Zeitraum.", styles["meta"]))

    footer = _page_footer(
        f"Team-Zeitübersicht – {period_label}",
        f"Erstellt am: {date.today().strftime('%d.%m.%Y')}",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer
