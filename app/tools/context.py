"""Identidade confiável da sessão e helpers comuns das Tools.

O apartamento vem EXCLUSIVAMENTE de ``tool_context.state["apartamento"]``.
Não há valor padrão nem fallback: sessão sem apartamento falha de forma controlada.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

APARTMENT_STATE_KEY = "apartamento"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MissingSessionApartmentError(Exception):
    """A sessão não possui um apartamento válido em ``state``."""

    def __init__(self) -> None:
        super().__init__("Sessão sem apartamento identificado.")


class InvalidDateError(ValueError):
    def __init__(self) -> None:
        super().__init__("Data inválida. Use o formato AAAA-MM-DD.")


def get_session_apartment(tool_context: Any) -> str:
    state = getattr(tool_context, "state", None)
    if state is None:
        raise MissingSessionApartmentError()
    try:
        present = APARTMENT_STATE_KEY in state
        value = state[APARTMENT_STATE_KEY] if present else None
    except (KeyError, TypeError):
        raise MissingSessionApartmentError() from None
    if not isinstance(value, str | int) or isinstance(value, bool):
        raise MissingSessionApartmentError()
    apartment = str(value).strip()
    if not apartment:
        raise MissingSessionApartmentError()
    return apartment


def parse_date(value: Any) -> dt.date:
    """Aceita somente ``AAAA-MM-DD``."""
    if not isinstance(value, str) or not _ISO_DATE.match(value.strip()):
        raise InvalidDateError()
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidDateError() from None


def invalid_session() -> dict:
    return {"status": "invalid_session", "message": "Sessão sem apartamento identificado."}


def invalid_date() -> dict:
    return {"status": "invalid_input", "message": "Data inválida. Use o formato AAAA-MM-DD."}


def storage_busy() -> dict:
    return {
        "status": "temporarily_unavailable",
        "message": "Serviço temporariamente ocupado. Tente novamente em instantes.",
    }
