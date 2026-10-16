"""Configuração centralizada da aplicação.

Toda leitura de variáveis de ambiente passa por aqui (``pydantic-settings``);
o restante do projeto importa ``get_settings()`` em vez de usar ``os.getenv()``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DADOS_DIR = BASE_DIR / "dados"  # fonte original e IMUTÁVEL do estado inicial
DATA_DIR = BASE_DIR / "data"  # bancos SQLite em tempo de execução

_SQLITE_PREFIX = "sqlite+aiosqlite:///"


def _anchor_sqlite_url(url: str) -> str:
    """Torna caminhos SQLite relativos independentes do diretório de execução.

    ``sqlite+aiosqlite:///./data/x.db`` é resolvido a partir da raiz do projeto,
    para que scripts, API e testes enxerguem sempre o mesmo arquivo.
    """
    if not url.startswith(_SQLITE_PREFIX):
        return url
    raw = url[len(_SQLITE_PREFIX) :]
    if raw.startswith(":memory:") or Path(raw).is_absolute():
        return url
    return f"{_SQLITE_PREFIX}{(BASE_DIR / raw).resolve().as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    google_api_key: str = ""
    google_genai_use_vertexai: bool = False
    gemini_model: str = ""

    domain_database_url: str = "sqlite+aiosqlite:///./data/condominio.db"
    adk_session_database_url: str = "sqlite+aiosqlite:///./data/adk_sessions.db"

    @field_validator("domain_database_url", "adk_session_database_url")
    @classmethod
    def _resolve_sqlite_path(cls, value: str) -> str:
        return _anchor_sqlite_url(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def export_genai_environment(settings: Settings | None = None) -> None:
    """Entrega a credencial do ``.env`` ao ``google-genai``, que só lê ``os.environ``.

    Sem isso, ``uv run uvicorn app.main:app`` com a chave apenas no ``.env`` falha em toda
    chamada ao Gemini ("No API key was provided"). Variáveis já definidas no ambiente vencem.
    """
    settings = settings or get_settings()
    if settings.google_api_key:
        os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)
    os.environ.setdefault(
        "GOOGLE_GENAI_USE_VERTEXAI", "TRUE" if settings.google_genai_use_vertexai else "FALSE"
    )
