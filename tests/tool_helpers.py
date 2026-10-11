"""Auxiliares dos testes de Tools (sem Gemini, Agent ou Runner)."""

from __future__ import annotations

from types import SimpleNamespace


def ctx(apartamento: str | None = "101", **extra) -> SimpleNamespace:
    """ToolContext simulado: só o ``state`` importa para as Tools."""
    state = dict(extra)
    if apartamento is not None:
        state["apartamento"] = apartamento
    return SimpleNamespace(state=state)
