"""Auxiliares dos testes de Tools (sem Gemini, Agent ou Runner)."""

from __future__ import annotations

from types import SimpleNamespace


def ctx(apartamento: str | None = "101", confirmation=None, **extra) -> SimpleNamespace:
    """ToolContext simulado: ``state``, ``tool_confirmation`` e ``request_confirmation``.

    ``requests`` acumula as chamadas a ``request_confirmation`` (hint/payload).
    """
    state = dict(extra)
    if apartamento is not None:
        state["apartamento"] = apartamento
    requests: list[dict] = []

    def request_confirmation(*, hint=None, payload=None):
        requests.append({"hint": hint, "payload": payload})

    return SimpleNamespace(
        state=state,
        tool_confirmation=confirmation,
        request_confirmation=request_confirmation,
        requests=requests,
    )


def confirmation(confirmed: bool, payload=None) -> SimpleNamespace:
    """Equivalente mínimo de ``ToolConfirmation`` injetado pelo ADK na retomada."""
    return SimpleNamespace(confirmed=confirmed, payload=payload, hint="")
