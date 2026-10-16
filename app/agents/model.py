"""Modelo Gemini compartilhado pelos agentes (nome vem de ``GEMINI_MODEL``).

Falhas transitórias do Gemini (429 por cota por minuto, 503 "high demand") são repetidas com
backoff exponencial pelo próprio cliente ``google-genai``. Sem isso, uma única recusa momentânea
do provedor virava HTTP 500 no meio do fluxo do morador.
"""

from __future__ import annotations

from google.adk.models import Gemini
from google.genai import types

from app.config import get_settings

RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=8,
    initial_delay=2.0,
    max_delay=60.0,
    exp_base=2.0,
    jitter=1.0,
    http_status_codes=[408, 429, 500, 502, 503, 504],
)


def gemini_model() -> Gemini:
    return Gemini(model=get_settings().gemini_model, retry_options=RETRY_OPTIONS)
