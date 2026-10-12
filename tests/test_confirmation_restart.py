"""Restart REAL: cada fase roda em um processo Python separado (sem objeto compartilhado).

Entre as fases só existem os arquivos SQLite (``condominio.db`` e ``adk_sessions.db``).
O LLM é roteirizado (sem rede); ADK, DatabaseSessionService, Runner, Tools e banco são reais.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.scripted_plan import PAID, VISITOR

ROOT = Path(__file__).resolve().parent.parent


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.domain = tmp_path / "condominio.db"
        self.sessions = tmp_path / "adk_sessions.db"
        self.env = {
            **os.environ,
            "DOMAIN_DATABASE_URL": f"sqlite+aiosqlite:///{self.domain.as_posix()}",
            "ADK_SESSION_DATABASE_URL": f"sqlite+aiosqlite:///{self.sessions.as_posix()}",
            "PYTHONWARNINGS": "ignore",
        }

    def run(self, *args: str) -> dict:
        """Um PROCESSO novo por chamada."""
        proc = subprocess.run(
            [sys.executable, "-m", "tests.restart_worker", *args],
            cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        line = next(l for l in proc.stdout.splitlines() if l.startswith("RESULT "))
        return json.loads(line[len("RESULT "):])


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.run("setup")
    return e


def test_golden_paid_reservation_survives_restart(env):
    # Processo A
    a = env.run("create", "--apartment", "101", "--message", PAID)
    assert a["status"] == "PENDING" and a["agent_name"] == "reservation_agent"
    assert a["counts"]["reservas_salao_0420"] == 0
    assert a["counts"]["confirmacoes"] == {a["confirmation_id"]: "PENDING"}
    assert env.sessions.exists() and env.domain.exists()

    # Processo B (restart completo)
    b = env.run("inspect", "--session-id", a["session_id"])
    assert b["apartment"] == "101"  # state sobreviveu
    assert b["event_count"] == a["event_count"]  # eventos sobreviveram
    assert "confirmation_request" in b["event_kinds"] and "tool_call" in b["event_kinds"]
    assert [p["id"] for p in b["pending"]] == [a["confirmation_id"]]
    assert b["pending"][0]["invocation_id"] == a["invocation_id"]
    assert b["pending"][0]["status"] == "PENDING"
    assert b["counts"]["reservas_salao_0420"] == 0

    # Processo C aprova
    c = env.run("resume", "--session-id", a["session_id"], "--confirmation-id", a["confirmation_id"],
                "--confirmed", "true")
    assert c["status"] == "APPROVED" and c["tool_result"]["status"] == "created"
    assert c["invocation_id"] == a["invocation_id"]
    assert c["tool_context_apartment"] == ["101"]  # identidade lida do state, após restart
    assert c["event_count_after"] > a["event_count"]
    assert "tool_response" in c["event_kinds"]
    assert c["counts"]["reservas_salao_0420"] == 1
    assert c["counts"]["confirmacoes"] == {a["confirmation_id"]: "APPROVED"}

    # Processo D repete a mesma aprovação
    d = env.run("resume", "--session-id", a["session_id"], "--confirmation-id", a["confirmation_id"],
                "--confirmed", "true")
    assert d["error"] == "ConfirmationNotPendingError"
    assert d["counts"]["reservas_salao_0420"] == 1
    assert d["event_count"] == c["event_count_after"]

    # Eventos continuam acessíveis e completos após novo restart
    e = env.run("inspect", "--session-id", a["session_id"])
    assert e["event_count"] == c["event_count_after"] and e["pending"] == []
    assert "confirmation_response" in e["event_kinds"]


def test_rejection_after_restart(env):
    a = env.run("create", "--apartment", "101", "--message", PAID)
    c = env.run("resume", "--session-id", a["session_id"], "--confirmation-id", a["confirmation_id"],
                "--confirmed", "false")
    assert c["status"] == "REJECTED" and c["tool_result"] == {"status": "rejected"}
    assert c["counts"]["reservas_salao_0420"] == 0
    assert c["counts"]["confirmacoes"] == {a["confirmation_id"]: "REJECTED"}
    assert c["event_count_after"] > a["event_count"]  # invocation concluída no ADK
    assert "tool_response" in c["event_kinds"]


def test_visitor_after_restart(env):
    a = env.run("create", "--apartment", "101", "--message", VISITOR)
    assert a["agent_name"] == "visitor_agent" and a["counts"]["joana"] == 0
    b = env.run("inspect", "--session-id", a["session_id"])
    assert b["pending"][0]["status"] == "PENDING"
    c = env.run("resume", "--session-id", a["session_id"], "--confirmation-id", a["confirmation_id"],
                "--confirmed", "true")
    assert c["status"] == "APPROVED" and c["tool_result"]["status"] == "authorized"
    assert c["counts"]["joana"] == 1 and c["tool_context_apartment"] == ["101"]
    again = env.run("resume", "--session-id", a["session_id"],
                    "--confirmation-id", a["confirmation_id"], "--confirmed", "true")
    assert again["error"] == "ConfirmationNotPendingError" and again["counts"]["joana"] == 1


def test_other_session_cannot_answer_after_restart(env):
    a = env.run("create", "--apartment", "101", "--message", PAID)
    other = env.run("create", "--apartment", "201", "--message", PAID.replace("04-20", "05-11"))
    r = env.run("resume", "--session-id", other["session_id"],
                "--confirmation-id", a["confirmation_id"], "--confirmed", "true")
    assert r["error"] == "ConfirmationNotPendingError"
    assert r["counts"]["reservas_salao_0420"] == 0
    assert r["counts"]["confirmacoes"][a["confirmation_id"]] == "PENDING"


def test_restart_does_not_clear_but_reset_does(env):
    """RESTART mantém tudo; RESET (scripts.reset) volta ao inicial e apaga sessões."""
    a = env.run("create", "--apartment", "101", "--message", PAID)
    env.run("inspect", "--session-id", a["session_id"])  # "restart": nada some
    assert env.run("count")["confirmacoes"] == {a["confirmation_id"]: "PENDING"}
    assert env.sessions.exists()

    proc = subprocess.run([sys.executable, "-m", "scripts.reset"], cwd=ROOT, env=env.env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert not env.sessions.exists()
    assert env.run("count")["confirmacoes"] == {}
