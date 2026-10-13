"""Erros de domínio.

As mensagens são deliberadamente genéricas: nunca citam apartamento, código ou
morador de terceiros, nem detalhes de persistência (SQLAlchemy/SQLite).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base de todos os erros de regra de negócio."""


class StorageBusyError(DomainError):
    """Contenção temporária de armazenamento, distinta de área ocupada."""

    def __init__(self) -> None:
        super().__init__("Serviço temporariamente ocupado. Tente novamente em instantes.")


class ApartmentNotFoundError(DomainError):
    def __init__(self) -> None:
        super().__init__("Apartamento não encontrado.")


class AreaNotFoundError(DomainError):
    def __init__(self) -> None:
        super().__init__("Área comum não encontrada.")


class ReservationNotFoundError(DomainError):
    """Reserva inexistente OU pertencente a outro apartamento (indistinguíveis)."""

    def __init__(self) -> None:
        super().__init__("Reserva não encontrada.")


class AreaUnavailableError(DomainError):
    """Área já reservada na data. Não informa quem reservou nem o código."""

    def __init__(self) -> None:
        super().__init__("A área não está disponível na data solicitada.")


class ReservationCodeGenerationError(DomainError):
    def __init__(self) -> None:
        super().__init__("Não foi possível gerar um código único de reserva.")


class InvalidVisitorNameError(DomainError):
    def __init__(self) -> None:
        super().__init__("O nome do visitante não pode ser vazio.")


class RegulationUnavailableError(DomainError):
    """O arquivo do regulamento não pôde ser lido."""

    def __init__(self) -> None:
        super().__init__("Regulamento indisponível no momento.")


class SessionNotFoundError(DomainError):
    def __init__(self) -> None:
        super().__init__("Sessão não encontrada.")


class ConfirmationError(DomainError):
    """Base dos erros do ciclo de vida de confirmações."""


class ConfirmationNotPendingError(ConfirmationError):
    """Inexistente, de outra sessão ou já respondida: indistinguíveis de propósito."""

    def __init__(self) -> None:
        super().__init__("Confirmação não encontrada ou não está pendente.")


class ConfirmationResumeError(ConfirmationError):
    """Falha técnica ao retomar a invocation após o claim.

    ``released`` indica se a confirmação voltou a PENDING (nada foi executado e uma nova
    tentativa é segura). Se False, ela permanece PROCESSING para evitar execução duplicada.
    """

    def __init__(self, *, released: bool) -> None:
        self.released = released
        super().__init__(
            "Falha ao retomar a confirmação; tente novamente."
            if released
            else "Falha ao retomar a confirmação; o resultado precisa ser verificado."
        )
