#!/usr/bin/env python3
"""Gera os PDFs de venda (manual, termos de uso, política de privacidade) a partir dos .md de docs/.

Uso:  python tools/build_docs_pdf.py [pasta_de_saida]      (padrão: docs/pdf)
Só ferramenta do fabricante; não faz parte do programa instalado.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INK, MUTED, ACCENT, LINE = colors.HexColor("#1B2230"), colors.HexColor("#5A6679"), colors.HexColor("#2F6FE8"), colors.HexColor("#D5DBE5")


def _fonts() -> tuple[str, str, str]:
    cands = [("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
             ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/consola.ttf")]
    for reg, bold, mono in cands:
        if Path(reg).exists() and Path(bold).exists() and Path(mono).exists():
            pdfmetrics.registerFont(TTFont("Body", reg))
            pdfmetrics.registerFont(TTFont("Body-Bold", bold))
            pdfmetrics.registerFont(TTFont("Mono", mono))
            pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body", boldItalic="Body-Bold")
            return "Body", "Body-Bold", "Mono"
    raise SystemExit("Nenhuma fonte Unicode encontrada (instale DejaVu Sans ou use o Windows).")


F, FB, FM = _fonts()
ST = {
    "p": ParagraphStyle("p", fontName=F, fontSize=10, leading=14.5, textColor=INK, spaceAfter=5, alignment=TA_LEFT),
    "h1": ParagraphStyle("h1", fontName=FB, fontSize=24, leading=28, textColor=INK, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName=FB, fontSize=15, leading=19, textColor=INK, spaceBefore=14, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName=FB, fontSize=11.5, leading=15, textColor=ACCENT, spaceBefore=9, spaceAfter=4),
    "cell": ParagraphStyle("cell", fontName=F, fontSize=8.8, leading=11.5, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName=FB, fontSize=8.8, leading=11.5, textColor=INK),
    "cap": ParagraphStyle("cap", fontName=F, fontSize=8, leading=10, textColor=MUTED, spaceAfter=8),
}


def inline(t: str) -> str:
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"`([^`]+)`", rf'<font name="{FM}" size="9">\1</font>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<link href="\2" color="#2F6FE8">\1</link>', t)
    t = re.sub(r"(\[(?:PREENCHER|NOME|CPF|E-MAIL|DATA|CIDADE)[^\]]*\])", r'<font backColor="#FFF3C4">\1</font>', t)
    return t


def table(rows: list[list[str]], width: float):
    n = len(rows[0])
    data = [[Paragraph(inline(c), ST["cellb" if i == 0 else "cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[width / n] * n, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F8")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def build(md: Path, out: Path, title: str) -> None:
    width = A4[0] - 40 * mm
    flow, lines, i = [], md.read_text(encoding="utf-8").splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
        elif ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            txt = inline(ln[lvl:].strip())
            if lvl == 2 and flow and not isinstance(flow[-1], Spacer) and len(flow) > 6 and md.name.startswith("MANUAL") and txt.startswith(("1.", "2.")):
                flow.append(PageBreak())
            flow.append(Paragraph(txt, ST[f"h{min(lvl, 3)}"]))
            i += 1
        elif ln.startswith("!["):
            m = re.match(r"!\[(.*?)\]\((.*?)\)", ln)
            img = md.parent / m.group(2)
            if img.exists():
                from PIL import Image as PI
                w, h = PI.open(img).size
                iw = min(width, 150 * mm)
                flow.append(KeepTogether([Image(str(img), width=iw, height=iw * h / w), Paragraph(inline(m.group(1)) + " (dados de exemplo)", ST["cap"])]))
            i += 1
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            flow += [table(rows, width), Spacer(1, 8)]
        elif re.match(r"\s*(-|\d+\.)\s", ln):
            ordered = bool(re.match(r"\s*\d+\.", ln))
            items = []
            while i < len(lines) and re.match(r"\s*(-|\d+\.)\s", lines[i]):
                items.append(ListItem(Paragraph(inline(re.sub(r"^\s*(-|\d+\.)\s+", "", lines[i])), ST["p"]), leftIndent=14))
                i += 1
                # linhas de continuação com recuo (sub-itens): anexa ao item anterior como texto
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
                    sub = re.sub(r"^\s*(-|\d+\.)\s+", "", lines[i])
                    items.append(ListItem(Paragraph("– " + inline(sub), ST["p"]), leftIndent=26, bulletType="bullet", value=" "))
                    i += 1
            flow += [ListFlowable(items, bulletType="1" if ordered else "bullet", start=1 if ordered else "•", leftIndent=14,
                                  bulletFontName=F, bulletFontSize=9), Spacer(1, 4)]
        else:
            para = [ln.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"(#|\||!\[|\s*(-|\d+\.)\s)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            flow.append(Paragraph(inline(" ".join(para)), ST["p"]))

    def deco(c, d):
        c.saveState()
        c.setFont(F, 8)
        c.setFillColor(MUTED)
        c.drawString(20 * mm, 11 * mm, f"StockPilot — {title}")
        c.drawRightString(A4[0] - 20 * mm, 11 * mm, f"Página {d.page}")
        c.restoreState()

    out.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                      title=f"StockPilot — {title}", author="StockPilot").build(flow, onFirstPage=deco, onLaterPages=deco)
    print("gerado:", out)


if __name__ == "__main__":
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else DOCS / "pdf"
    for name, title, md in [("Manual-StockPilot.pdf", "Manual do usuário", "MANUAL_DO_USUARIO.md"),
                            ("Termos-de-Uso-StockPilot.pdf", "Termos de Uso", "TERMOS_DE_USO.md"),
                            ("Politica-de-Privacidade-StockPilot.pdf", "Política de Privacidade", "POLITICA_DE_PRIVACIDADE.md")]:
        build(DOCS / md, outdir / name, title)
