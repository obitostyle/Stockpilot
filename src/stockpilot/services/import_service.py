"""Importação de produtos por planilha (.xlsx) e inventário em lote.

Importação é TUDO-OU-NADA: se qualquer linha tiver erro, nada é gravado e o relatório de erros diz a linha e o motivo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from ..domain.enums import UnitOfMeasure
from ..domain.errors import BusinessError, ValidationError
from . import product_service, stock_service
from .schemas import ProductInput, build

TEMPLATE_HEADERS = ["Nome*", "Preço de venda*", "Custo", "Estoque inicial", "Estoque mínimo", "Unidade", "SKU",
                    "Código de barras", "Categoria", "Marca", "Localização"]
_ALIASES = {"nome": "name", "nome*": "name", "produto": "name", "preço de venda*": "sale_price", "preço de venda": "sale_price",
            "preco de venda": "sale_price", "preço": "sale_price", "preco": "sale_price", "custo": "cost_price", "custo médio": "cost_price",
            "estoque inicial": "qty", "estoque": "qty", "quantidade": "qty", "estoque mínimo": "min_stock", "estoque minimo": "min_stock",
            "unidade": "unit", "sku": "sku", "código de barras": "barcode", "codigo de barras": "barcode", "ean": "barcode",
            "categoria": "category_name", "marca": "brand", "localização": "location", "localizacao": "location"}


@dataclass
class ImportReport:
    total_rows: int = 0
    created: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def write_template(path: Path | str) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Produtos"
    ws.append(TEMPLATE_HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.append(["Exemplo: Arroz 5kg", 27.90, 18.00, 20, 5, "UN", "ARROZ5", "7891234567895", "Mercearia", "Marca X", "Corredor 2"])
    ws2 = wb.create_sheet("Instruções")
    for line in ["Preencha uma linha por produto na aba 'Produtos' e apague a linha de exemplo.",
                 "Obrigatórios: Nome e Preço de venda. Use ponto OU vírgula decimal (27,90 ou 27.90).",
                 "Unidade: UN, PAR, CX, PCT, KG, G, L, ML ou M (vazio = UN).",
                 "Código de barras: só números (4 a 14 dígitos). SKU e código de barras não podem repetir.",
                 "A importação é tudo-ou-nada: se houver erro, nenhuma linha é gravada e você recebe a lista dos erros."]:
        ws2.append([line])
    ws.column_dimensions["A"].width = 32
    wb.save(path)
    return Path(path)


def _num(v, label: str, line: int) -> Decimal:
    if v is None or str(v).strip() == "":
        return Decimal("0")
    t = str(v).strip().replace("R$", "").strip()
    if isinstance(v, (int, float)):
        t = repr(v)
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise ValidationError(f"linha {line}: {label} inválido ('{v}')")
    if d < 0:
        raise ValidationError(f"linha {line}: {label} não pode ser negativo")
    return d


def import_products(session: Session, path: Path | str, user_id: int | None, dry_run: bool = False) -> ImportReport:
    from openpyxl import load_workbook
    rep = ImportReport()
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        raise BusinessError("Não foi possível abrir a planilha. Use um arquivo .xlsx (Excel).")
    ws = wb["Produtos"] if "Produtos" in wb.sheetnames else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise BusinessError("A planilha está vazia.")
    cols = {}
    for i, h in enumerate(rows[0]):
        k = _ALIASES.get(str(h or "").strip().lower())
        if k:
            cols[k] = i
    if "name" not in cols or "sale_price" not in cols:
        raise BusinessError("A planilha precisa ter as colunas 'Nome' e 'Preço de venda' na primeira linha. Baixe o modelo para ver o formato.")
    sp = session.begin_nested()
    seen_sku, seen_bar = set(), set()
    try:
        for n, row in enumerate(rows[1:], start=2):
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            if str(row[cols["name"]] or "").strip().lower().startswith("exemplo:"):
                continue
            rep.total_rows += 1

            def get(k):
                i = cols.get(k)
                return None if i is None or i >= len(row) else row[i]
            try:
                unit_raw = str(get("unit") or "UN").strip().upper()
                try:
                    unit = UnitOfMeasure(unit_raw)
                except ValueError:
                    raise ValidationError(f"linha {n}: unidade inválida '{unit_raw}'")
                sku, bar = (str(get("sku") or "").strip() or None), (str(get("barcode") or "").strip().removesuffix(".0") or None)
                if sku and sku in seen_sku:
                    raise ValidationError(f"linha {n}: SKU '{sku}' repetido na planilha")
                if bar and bar in seen_bar:
                    raise ValidationError(f"linha {n}: código de barras '{bar}' repetido na planilha")
                seen_sku.add(sku)
                seen_bar.add(bar)
                price = _num(get("sale_price"), "preço de venda", n)
                data = build(ProductInput, name=str(get("name") or "").strip(), sale_price=price, cost_price=_num(get("cost_price"), "custo", n),
                             min_stock=_num(get("min_stock"), "estoque mínimo", n), unit=unit, sku=sku, barcode=bar,
                             category_name=str(get("category_name") or "").strip() or None, brand=str(get("brand") or "").strip() or None,
                             location=str(get("location") or "").strip() or None)
                qty = _num(get("qty"), "estoque inicial", n)
                with session.begin_nested():
                    product_service.create_product(session, data, qty, user_id)
                rep.created += 1
            except ValidationError as exc:
                rep.errors += [m if m.startswith("linha") else f"linha {n}: {m}" for m in exc.messages]
            except BusinessError as exc:
                rep.errors.append(f"linha {n}: {exc}")
        if rep.errors or dry_run:
            sp.rollback()
            if rep.errors:
                rep.created = 0
        else:
            sp.commit()
    except BaseException:
        if sp.is_active:
            sp.rollback()
        raise
    wb.close()
    return rep


def batch_inventory(session: Session, counts: dict[int, Decimal], user_id: int | None, reason: str = "Inventário em lote") -> int:
    """Aplica contagens físicas (produto -> quantidade contada). Só gera movimentação onde a contagem difere do saldo."""
    if not counts:
        raise ValidationError("Informe ao menos uma contagem.")
    n = 0
    with session.begin_nested():
        for pid, qty in counts.items():
            p = product_service.get_product(session, pid)
            if qty != p.quantity_on_hand:
                stock_service.inventory_count(session, pid, qty, reason, user_id)
                n += 1
    return n
