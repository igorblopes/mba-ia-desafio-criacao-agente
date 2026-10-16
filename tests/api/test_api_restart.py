"""Restart REAL: dois processos uvicorn distintos sobre os mesmos arquivos SQLite."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.adversarial.realserver import Server as ProcessServer
from tests.scripted_plan import PAID, VISITOR

ROOT = Path(__file__).resolve().parents[2]


class Server(ProcessServer):
    def __init__(self, env: dict[str, str], log: Path) -> None:
        super().__init__(env, log, app="tests.api_server:app")


@pytest.fixture
def env(tmp_path):
    e = dict(os.environ)
    e["DOMAIN_DATABASE_URL"] = f"sqlite+aiosqlite:///{(tmp_path / 'condominio.db').as_posix()}"
    e["ADK_SESSION_DATABASE_URL"] = f"sqlite+aiosqlite:///{(tmp_path / 'adk_sessions.db').as_posix()}"
    subprocess.run(
        [sys.executable, "-m", "tests.restart_worker", "setup"],
        cwd=ROOT, env=e, check=True, capture_output=True,
    )
    return e


def _say(base, sid, texto):
    r = httpx.post(f"{base}/sessoes/{sid}/mensagens", json={"texto": texto}, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_state_and_pending_confirmation_survive_api_restart(env, tmp_path):
    log = tmp_path / "server.log"
    a = Server(env, log)
    try:
        a.wait_ready()
        sid = httpx.post(f"{a.base}/sessoes", json={"apartamento": "101"}).json()["session_id"]
        [paid] = _say(a.base, sid, PAID)["confirmacoes_pendentes"]  # fica sem resposta
        _say(a.base, sid, "Reserve a quadra para 2030-04-06.")  # reserva gratuita
        sid2 = httpx.post(f"{a.base}/sessoes", json={"apartamento": "101"}).json()["session_id"]
        [vis] = _say(a.base, sid2, VISITOR)["confirmacoes_pendentes"]
        assert httpx.post(f"{a.base}/sessoes/{sid2}/confirmacoes",
                          json={"id": vis["id"], "confirmado": True}).status_code == 200
        events_before = httpx.get(f"{a.base}/sessoes/{sid}/eventos").json()
        reservas_before = httpx.get(f"{a.base}/apartamentos/101/reservas").json()
        visitors_before = httpx.get(f"{a.base}/apartamentos/101/visitantes").json()
        assert events_before and len(reservas_before) == 2 and len(visitors_before) == 1
    finally:
        a.stop()

    b = Server(env, log)  # processo novo, mesmos arquivos
    try:
        b.wait_ready()
        assert httpx.get(f"{b.base}/sessoes/{sid}/eventos").json() == events_before
        assert httpx.get(f"{b.base}/apartamentos/101/reservas").json() == reservas_before
        assert httpx.get(f"{b.base}/apartamentos/101/visitantes").json() == visitors_before
        # a sessão antiga continua utilizável e a pendência continua listada
        again = _say(b.base, sid, "Mostre minhas reservas.")
        assert [p["id"] for p in again["confirmacoes_pendentes"]] == [paid["id"]]
        # aprovar após o restart funciona e é idempotente
        ok = httpx.post(f"{b.base}/sessoes/{sid}/confirmacoes",
                        json={"id": paid["id"], "confirmado": True}, timeout=60)
        assert ok.status_code == 200
        assert any(r["data"] == "2030-04-20"
                   for r in httpx.get(f"{b.base}/apartamentos/101/reservas").json())
        replay = httpx.post(f"{b.base}/sessoes/{sid}/confirmacoes",
                            json={"id": paid["id"], "confirmado": True})
        assert replay.status_code == 409
        # startup não fez reset: dados criados no processo A seguem aqui
        assert any(r["data"] == "2030-04-06"
                   for r in httpx.get(f"{b.base}/apartamentos/101/reservas").json())
    finally:
        b.stop()


def test_startup_without_initialized_database_fails_and_does_not_reset(tmp_path):
    e = dict(os.environ)
    e["DOMAIN_DATABASE_URL"] = f"sqlite+aiosqlite:///{(tmp_path / 'vazio.db').as_posix()}"
    e["ADK_SESSION_DATABASE_URL"] = f"sqlite+aiosqlite:///{(tmp_path / 's.db').as_posix()}"
    s = Server(e, tmp_path / "log.txt")
    try:
        deadline = time.monotonic() + 60
        while s.proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.3)
        assert s.proc.poll() not in (None, 0)
        assert "scripts.reset" in (tmp_path / "log.txt").read_text(errors="replace")
    finally:
        s.stop()
