"""Processo uvicorn REAL (localhost) para restart, concorrência HTTP e crash: nada em memória."""

from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["DOMAIN_DATABASE_URL"] = f"sqlite+aiosqlite:///{(tmp_path / 'condominio.db').as_posix()}"
    env["ADK_SESSION_DATABASE_URL"] = f"sqlite+aiosqlite:///{(tmp_path / 'adk_sessions.db').as_posix()}"
    env.update(extra)
    return env


def reset_db(env: dict[str, str]) -> None:
    """Reset REAL via ``python -m scripts.reset`` (o mesmo comando do usuário)."""
    subprocess.run([sys.executable, "-m", "scripts.reset"], cwd=ROOT, env=env, check=True,
                   capture_output=True)


class Server:
    def __init__(self, env: dict[str, str], log: Path, app: str = "tests.adversarial.server:app"):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.log_path = log
        self._log = log.open("ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tests.uvicorn_worker", app, str(self.port)],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=self._log, stderr=subprocess.STDOUT)

    def wait_ready(self, timeout: float = 90) -> "Server":
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"uvicorn terminou ({self.proc.returncode})")
            try:
                if httpx.get(f"{self.base}/openapi.json", timeout=2).status_code == 200:
                    return self
            except httpx.TransportError:
                time.sleep(0.3)
        raise TimeoutError("servidor não ficou pronto")

    def stop(self) -> None:
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write(b"stop\n")
                    self.proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    if self.proc.poll() is None:
                        raise
                try:
                    self.proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
                    raise AssertionError("uvicorn não encerrou cooperativamente")
        finally:
            if self.proc.stdin:
                self.proc.stdin.close()
            self._log.close()

    def wait_exit(self, timeout: float = 30) -> int:
        self.proc.wait(timeout=timeout)
        return self.proc.returncode

    def log_text(self) -> str:
        return self.log_path.read_text(errors="replace")

    # ---- helpers HTTP síncronos
    def session(self, apartamento: str) -> str:
        r = httpx.post(f"{self.base}/sessoes", json={"apartamento": apartamento}, timeout=60)
        assert r.status_code == 201, r.text
        return r.json()["session_id"]

    def say(self, sid: str, texto: str) -> dict:
        r = httpx.post(f"{self.base}/sessoes/{sid}/mensagens", json={"texto": texto}, timeout=120)
        assert r.status_code == 200, r.text
        return r.json()

    def answer(self, sid: str, cid: str, confirmado: bool) -> httpx.Response:
        return httpx.post(f"{self.base}/sessoes/{sid}/confirmacoes",
                          json={"id": cid, "confirmado": confirmado}, timeout=120)

    def get(self, path: str):
        r = httpx.get(f"{self.base}{path}", timeout=60)
        assert r.status_code == 200, (path, r.status_code, r.text)
        return r.json()


def domain_rows(tmp_path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    """Leitura direta e controlada de ``condominio.db`` (evidência independente do app)."""
    con = sqlite3.connect(tmp_path / "condominio.db")
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()
