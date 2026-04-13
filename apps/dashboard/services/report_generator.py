"""
Report generator — produces PDF (WeasyPrint) and Excel (openpyxl) exports.
"""
from __future__ import annotations

import io
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone


def _feedback_to_rows(queryset: QuerySet) -> tuple[list[str], list[list[Any]]]:
    """Convert a Feedback queryset into (headers, rows) suitable for export."""
    headers = [
        "ID",
        "Channel",
        "Status",
        "Urgency",
        "Language",
        "Location",
        "Sentiment",
        "Submitted At",
        "Message (truncated)",
    ]
    rows = []
    for fb in queryset:
        rows.append([
            fb.feedback_id,
            fb.channel,
            fb.status,
            fb.urgency_level,
            fb.detected_language or "",
            fb.location_mentioned or "",
            fb.sentiment.sentiment_label if fb.sentiment else "",
            fb.submitted_at.strftime("%Y-%m-%d %H:%M UTC") if fb.submitted_at else "",
            (fb.message_original or "")[:200],
        ])
    return headers, rows


def generate_pdf_report(queryset: QuerySet, title: str) -> bytes:
    """Render a PDF report using WeasyPrint and return raw bytes."""
    from weasyprint import HTML  # deferred to avoid import error when WeasyPrint not installed

    headers, rows = _feedback_to_rows(queryset)

    rows_html = ""
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        rows_html += f"<tr>{cells}</tr>"

    header_cells = "".join(f"<th>{h}</th>" for h in headers)
    generated_at = timezone.now().strftime("%Y-%m-%d %H:%M UTC")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        body {{ font-family: sans-serif; font-size: 10px; }}
        h1 {{ font-size: 16px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1em; }}
        th, td {{ border: 1px solid #ccc; padding: 4px 6px; text-align: left; }}
        th {{ background: #f0f0f0; font-weight: bold; }}
        tr:nth-child(even) {{ background: #fafafa; }}
        .meta {{ color: #666; font-size: 9px; margin-bottom: 0.5em; }}
      </style>
    </head>
    <body>
      <h1>{title}</h1>
      <p class="meta">Generated: {generated_at} — Total records: {len(rows)}</p>
      <table>
        <thead><tr>{header_cells}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </body>
    </html>
    """

    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes


def generate_excel_report(queryset: QuerySet) -> bytes:
    """Build an Excel workbook and return raw bytes."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    headers, rows = _feedback_to_rows(queryset)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Feedback"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2E5090")

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill

    for row_idx, row in enumerate(rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-fit column widths
    for col in ws.columns:
        max_length = max((len(str(cell.value or "")) for cell in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = min(max_length + 4, 50)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
