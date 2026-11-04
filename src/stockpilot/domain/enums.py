from __future__ import annotations

import enum


class TaxRegime(str, enum.Enum):
    MEI = "MEI"
    SIMPLES_NACIONAL = "SIMPLES_NACIONAL"
    LUCRO_PRESUMIDO = "LUCRO_PRESUMIDO"
    LUCRO_REAL = "LUCRO_REAL"

    @property
    def label(self) -> str:
        return {
            "MEI": "MEI",
            "SIMPLES_NACIONAL": "Simples Nacional",
            "LUCRO_PRESUMIDO": "Lucro Presumido",
            "LUCRO_REAL": "Lucro Real",
        }[self.value]


class UnitOfMeasure(str, enum.Enum):
    UN = "UN"
    PAR = "PAR"
    CX = "CX"
    PCT = "PCT"
    KG = "KG"
    G = "G"
    L = "L"
    ML = "ML"
    M = "M"

    @property
    def label(self) -> str:
        return {
            "UN": "Unidade (UN)", "PAR": "Par (PAR)", "CX": "Caixa (CX)", "PCT": "Pacote (PCT)",
            "KG": "Quilograma (KG)", "G": "Grama (G)", "L": "Litro (L)",
            "ML": "Mililitro (ML)", "M": "Metro (M)",
        }[self.value]

    @property
    def fractional_by_default(self) -> bool:
        return self.value in {"KG", "G", "L", "ML", "M"}


class MovementType(str, enum.Enum):
    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"
    AJUSTE = "AJUSTE"
    INVENTARIO = "INVENTARIO"
    ESTORNO = "ESTORNO"

    @property
    def label(self) -> str:
        return {
            "ENTRADA": "Entrada", "SAIDA": "Saída", "AJUSTE": "Ajuste",
            "INVENTARIO": "Inventário", "ESTORNO": "Estorno",
        }[self.value]


class MovementOrigin(str, enum.Enum):
    MANUAL = "MANUAL"
    CADASTRO = "CADASTRO"      # saldo inicial no cadastro do produto
    COMPRA = "COMPRA"          # Fase 3
    VENDA = "VENDA"            # Fase 3
    DEVOLUCAO = "DEVOLUCAO"    # Fase 3
    INVENTARIO = "INVENTARIO"
    ESTORNO = "ESTORNO"

    @property
    def label(self) -> str:
        return {
            "MANUAL": "Manual", "CADASTRO": "Cadastro", "COMPRA": "Compra", "VENDA": "Venda",
            "DEVOLUCAO": "Devolução", "INVENTARIO": "Inventário", "ESTORNO": "Estorno",
        }[self.value]


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    GERENTE = "GERENTE"
    OPERADOR = "OPERADOR"


_LABELS = {
    "PaymentMethod": {"DINHEIRO": "Dinheiro", "PIX": "Pix", "DEBITO": "Cartão de débito",
                      "CREDITO": "Cartão de crédito", "OUTRO": "Outro", "A_PRAZO": "A prazo (fiado)"},
    "PurchaseStatus": {"RASCUNHO": "Rascunho", "CONFIRMADA": "Confirmada", "CANCELADA": "Cancelada"},
    "SaleStatus": {"CONCLUIDA": "Concluída", "CANCELADA": "Cancelada"},
    "BillStatus": {"ABERTA": "Em aberto", "PAGA": "Quitada", "CANCELADA": "Cancelada"},
    "FinKind": {"ENTRADA": "Entrada", "SAIDA": "Saída"},
    "FinGroup": {"RECEITA_VENDAS": "Receita de vendas", "OUTRA_RECEITA": "Outras receitas",
                 "DESPESA_FIXA": "Despesa fixa", "DESPESA_VARIAVEL": "Despesa variável",
                 "COMPRA_MERCADORIA": "Compra de mercadorias", "DEVOLUCAO_VENDA": "Devolução de venda"},
    "AccountType": {"CAIXA": "Caixa", "BANCO": "Conta bancária"},
    "FinOrigin": {"MANUAL": "Manual", "VENDA": "Venda", "COMPRA": "Compra", "PAGAMENTO": "Pagamento",
                  "RECEBIMENTO": "Recebimento", "DEVOLUCAO": "Devolução", "ESTORNO": "Estorno"},
    "AssessmentStatus": {"ESTIMATIVA": "Estimativa", "INCOMPLETA": "Incompleta — dados faltando"},
    "EmployeeStatus": {"ATIVO": "Ativo", "FERIAS": "Em férias", "AFASTADO": "Afastado", "DESLIGADO": "Desligado"},
}


class _L(str, enum.Enum):
    @property
    def label(self) -> str:
        return _LABELS[type(self).__name__][self.value]


class PaymentMethod(_L):
    DINHEIRO = "DINHEIRO"
    PIX = "PIX"
    DEBITO = "DEBITO"
    CREDITO = "CREDITO"
    OUTRO = "OUTRO"
    A_PRAZO = "A_PRAZO"


class PurchaseStatus(_L):
    RASCUNHO = "RASCUNHO"
    CONFIRMADA = "CONFIRMADA"
    CANCELADA = "CANCELADA"


class SaleStatus(_L):
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"


class BillStatus(_L):
    ABERTA = "ABERTA"
    PAGA = "PAGA"
    CANCELADA = "CANCELADA"


class FinKind(_L):
    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"


class FinGroup(_L):
    RECEITA_VENDAS = "RECEITA_VENDAS"
    OUTRA_RECEITA = "OUTRA_RECEITA"
    DESPESA_FIXA = "DESPESA_FIXA"
    DESPESA_VARIAVEL = "DESPESA_VARIAVEL"
    COMPRA_MERCADORIA = "COMPRA_MERCADORIA"
    DEVOLUCAO_VENDA = "DEVOLUCAO_VENDA"


class AccountType(_L):
    CAIXA = "CAIXA"
    BANCO = "BANCO"


class FinOrigin(_L):
    MANUAL = "MANUAL"
    VENDA = "VENDA"
    COMPRA = "COMPRA"
    PAGAMENTO = "PAGAMENTO"
    RECEBIMENTO = "RECEBIMENTO"
    DEVOLUCAO = "DEVOLUCAO"
    ESTORNO = "ESTORNO"


class AssessmentStatus(_L):
    ESTIMATIVA = "ESTIMATIVA"
    INCOMPLETA = "INCOMPLETA"


class EmployeeStatus(_L):
    ATIVO = "ATIVO"
    FERIAS = "FERIAS"
    AFASTADO = "AFASTADO"
    DESLIGADO = "DESLIGADO"


OPERATING_EXPENSE_GROUPS = (FinGroup.DESPESA_FIXA, FinGroup.DESPESA_VARIAVEL)
