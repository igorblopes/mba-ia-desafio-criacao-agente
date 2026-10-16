"""Regressão (Passo 12): a chave só no ``.env`` precisa chegar ao ``google-genai``.

O ensaio do avaliador com ``uv run uvicorn`` devolvia HTTP 500 em toda mensagem: ``Settings`` lia
``GOOGLE_API_KEY`` do ``.env``, mas o cliente do Gemini só consulta ``os.environ``.
"""

from __future__ import annotations

import os
from unittest import mock

from app.config import Settings, export_genai_environment


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, gemini_model="m", **kw)


def test_key_from_settings_is_exported():
    with mock.patch.dict(os.environ, clear=True):
        export_genai_environment(_settings(google_api_key="chave-do-env-file"))
        assert os.environ["GOOGLE_API_KEY"] == "chave-do-env-file"
        assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "FALSE"


def test_existing_environment_wins():
    with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "do-shell"}, clear=True):
        export_genai_environment(_settings(google_api_key="do-arquivo"))
        assert os.environ["GOOGLE_API_KEY"] == "do-shell"


def test_empty_key_is_not_exported():
    with mock.patch.dict(os.environ, clear=True):
        export_genai_environment(_settings(google_api_key=""))
        assert "GOOGLE_API_KEY" not in os.environ


def test_real_runtime_exports_key_but_scripted_runtime_does_not(session_factory, tmp_path):
    from app.runtime import adk_runtime
    from app.services.provider import reset_services
    from tests.fake_llm import ScriptedLlm

    url = f"sqlite+aiosqlite:///{(tmp_path / 's.db').as_posix()}"
    fake = _settings(google_api_key="chave-do-env-file")
    with mock.patch.dict(os.environ, clear=True), \
            mock.patch("app.config.get_settings", return_value=fake):
        try:
            adk_runtime.build_adk_runtime(domain_session_factory=session_factory,
                                          session_db_url=url, llm=ScriptedLlm())
            assert "GOOGLE_API_KEY" not in os.environ
            adk_runtime.build_adk_runtime(domain_session_factory=session_factory, session_db_url=url)
            assert os.environ["GOOGLE_API_KEY"] == "chave-do-env-file"
        finally:
            reset_services()
