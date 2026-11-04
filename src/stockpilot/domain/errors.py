"""Erros de negócio. As mensagens são exibidas ao usuário, então ficam em português."""
from __future__ import annotations


class StockPilotError(Exception):
    """Base de todos os erros esperados do sistema."""


class BusinessError(StockPilotError):
    pass


class ValidationError(BusinessError):
    def __init__(self, messages: list[str] | str):
        self.messages = [messages] if isinstance(messages, str) else list(messages)
        super().__init__("\n".join(self.messages))


class NotFoundError(BusinessError):
    pass


class DuplicateError(BusinessError):
    pass


class InsufficientStockError(BusinessError):
    pass


class DatabaseIncompatibleError(StockPilotError):
    """Banco criado por versão mais nova do programa ou corrompido."""


class DiscountNotAuthorizedError(BusinessError):
    pass


class MissingRuleError(BusinessError):
    """Tabela legal (INSS, IRRF, Simples...) não cadastrada para a competência."""


class PermissionDeniedError(BusinessError):
    pass
