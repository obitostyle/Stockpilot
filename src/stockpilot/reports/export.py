"""Exportação de ReportData para Excel (.xlsx) e PDF."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .. import APP_NAME, __version__
from .model import ReportData, fmt

_SAFE = {"−": "-", "≤": "<=", "≥": ">=", "→": "->", "✔": "sim", "–": "-", "•": "-", "’": "'", "“": '"', "”": '"', "…": "..."}


def _safe(text) -> str:
    t = str(text)
    for a, b in _SAFE.items():
        t = t.replace(a, b)
    return t.encode("cp1252", "replace").decode("cp1252")


def generated_text(r: ReportData) -> str:
    return f"Gerado em {r.generated_at:%d/%m/%Y às %H:%M}"


def to_xlsx(r: ReportData, path: Path | str) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = _safe(r.title)[:31].replace("/", "-")
    ws.append([r.title])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([r.company or APP_NAME])
    ws.append([f"Período: {r.period}"])
    ws.append([generated_text(r)])
    ws.append(["Critérios e premissas de cálculo:"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for c in r.criteria:
        ws.append(["  • " + c])
    ws.append([])
    head_row = ws.max_row + 1
    ws.append([h for h, _ in r.columns])
    fill = PatternFill("solid", fgColor="0B2545")
    for c in ws[head_row]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def put(row_vals, bold=False):
        cells = []
        for v, (_, kind) in zip(row_vals, r.columns):
            if isinstance(v, Decimal):
                v = float(v)  # Excel só guarda ponto flutuante; os valores exatos continuam no banco
            cells.append(v)
        ws.append(cells)
        for idx, (v, (_, kind)) in enumerate(zip(row_vals, r.columns), start=1):
            cell = ws.cell(ws.max_row, idx)
            if kind == "money":
                cell.number_format = '"R$" #,##0.00'
            elif kind == "qty":
                cell.number_format = "#,##0.###"
            elif kind == "pct":
                cell.number_format = '0.0"%"'
            elif kind == "date":
                cell.number_format = "DD/MM/YYYY"
            elif kind == "int":
                cell.number_format = "#,##0"
            if bold:
                cell.font = Font(bold=True)
    for row in r.rows:
        put(row)
    if r.totals:
        put(r.totals, True)
    if r.notes:
        ws.append([])
        for n in r.notes:
            ws.append(["Obs.: " + n])
    ws.freeze_panes = ws.cell(head_row + 1, 1)
    for i, (h, kind) in enumerate(r.columns, start=1):
        width = max([len(h)] + [len(fmt(row[i - 1], kind)) for row in r.rows[:300] if i - 1 < len(row)] + [8])
        ws.column_dimensions[get_column_letter(i)].width = min(60, width + 2)
    ws.sheet_view.showGridLines = True
    p = Path(path)
    wb.save(p)
    return p


def to_pdf(r: ReportData, path: Path | str) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=7.5, leading=9)
    cell = ParagraphStyle("cell", parent=ss["Normal"], fontSize=7.5, leading=9)
    cell_r = ParagraphStyle("cell_r", parent=cell, alignment=TA_RIGHT)
    cell_b = ParagraphStyle("cell_b", parent=cell, fontName="Helvetica-Bold")
    cell_rb = ParagraphStyle("cell_rb", parent=cell_r, fontName="Helvetica-Bold")
    head = ParagraphStyle("head", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=15, alignment=0, spaceAfter=2, textColor=colors.HexColor("#0B2545"))

    ncols = len(r.columns)
    pagesize = landscape(A4) if ncols > 6 else A4
    doc = SimpleDocTemplate(str(path), pagesize=pagesize, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=16 * mm,
                            title=_safe(r.title), author=APP_NAME)
    story = [Paragraph(escape(_safe(r.title)), title),
             Paragraph(escape(_safe(r.company or "")) + "  |  <b>Período:</b> " + escape(_safe(r.period)) + "  |  " + escape(_safe(generated_text(r))), small),
             Spacer(1, 3), Paragraph("<b>Critérios e premissas:</b> " + escape(_safe("; ".join(r.criteria))), small), Spacer(1, 6)]

    def para(v, kind, bold=False):
        txt = escape(_safe(fmt(v, kind)))
        right = kind in ("money", "qty", "pct", "int")
        return Paragraph(txt, (cell_rb if bold else cell_r) if right else (cell_b if bold else cell))

    data = [[Paragraph(escape(_safe(h)), head) for h, _ in r.columns]]
    for row in r.rows:
        data.append([para(v, k) for v, (_, k) in zip(row, r.columns)])
    if r.totals:
        data.append([para(v, k, True) for v, (_, k) in zip(r.totals, r.columns)])
    if not r.rows:
        data.append([Paragraph("Nenhum registro para os filtros informados.", cell)] + [""] * (ncols - 1))
    avail = pagesize[0] - 24 * mm
    # largura: colunas de texto recebem mais espaço
    weights = [3.2 if k == "text" else 1.6 for _, k in r.columns]
    widths = [avail * w / sum(weights) for w in weights]
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2545")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FB")]),
             ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5DDE8")), ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if r.totals:
        style += [("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#0B2545")), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#DBEAFE"))]
    if not r.rows:
        style.append(("SPAN", (0, 1), (-1, 1)))
    t.setStyle(TableStyle(style))
    story.append(t)
    if r.notes:
        story.append(Spacer(1, 8))
        for n in r.notes:
            story.append(Paragraph("• " + escape(_safe(n)), small))

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(12 * mm, 9 * mm, _safe(f"{APP_NAME} {__version__} - documento gerencial, sem valor fiscal - {generated_text(r)}"))
        canvas.drawRightString(pagesize[0] - 12 * mm, 9 * mm, f"Página {d.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return Path(path)
