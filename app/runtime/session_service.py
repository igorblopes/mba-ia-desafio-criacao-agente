"""Fábrica do serviço de sessões persistentes do ADK (``adk_sessions.db``).

Banco separado do domínio (ADR-006): o esquema é gerenciado pelo ADK.
"""

from __future__ import annotations

from google.adk.sessions import DatabaseSessionService

from app.config import get_settings


def create_session_service(url: str | None = None) -> DatabaseSessionService:
    return DatabaseSessionService(db_url=url or get_settings().adk_session_database_url)
