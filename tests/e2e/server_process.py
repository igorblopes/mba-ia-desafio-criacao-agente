"""Processo uvicorn REAL em 127.0.0.1:8000, exatamente como o avaliador sobe a API.

Equivale a ``uv run uvicorn app.main:app --host 127.0.0.1 --port 8000``: usa o interpretador do
ambiente ``uv`` (``sys.executable``) e o CLI oficial do uvicorn, sem app de teste nem rotas extras.
O encerramento é o mesmo de um Ctrl+C (SIGINT; no Windows, CTRL_BREAK no grupo do processo),
com lifespan shutdown real. Prontidão por polling de uma rota existente (``/openapi.json``).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
HOST, PORT = "127.0.0.1", 8000
BASE_URL = f"http://{HOST}:{PORT}"
COMMAND = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", str(PORT)]


def port_in_use() -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((HOST, PORT)) == 0


def run_reset() -> str:
    """O mesmo comando do avaliador: ``uv run python -m scripts.reset``."""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "scripts.reset"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


class ApiProcess:
    def __init__(self, log_path: Path):
        assert not port_in_use(), f"porta {PORT} já ocupada: encerre outro servidor antes do ensaio"
        self.log_path = log_path
        self._log = log_path.open("ab")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            COMMAND, cwd=ROOT, stdout=self._log, stderr=subprocess.STDOUT, creationflags=flags)
        self.pid = self.proc.pid

    def wait_ready(self, timeout: float = 90, interval: float = 0.5) -> "ApiProcess":
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"uvicorn terminou ao subir (código {self.proc.returncode}); "
                                     f"veja {self.log_path}")
            try:
                if httpx.get(f"{BASE_URL}/openapi.json", timeout=2).status_code == 200:
                    return self
            except httpx.TransportError:
                pass
            time.sleep(interval)
        self.kill()
        raise AssertionError(f"API não respondeu em {timeout}s")

    def stop(self, timeout: float = 30) -> int:
        """Encerramento cooperativo (Ctrl+C). Falha se o processo não terminar sozinho."""
        try:
            if self.proc.poll() is None:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
                try:
                    self.proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self.kill()
                    raise AssertionError("uvicorn não encerrou após o sinal de parada")
            return self.proc.returncode
        finally:
            self._log.close()

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        if not self._log.closed:
            self._log.close()

    def log_text(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")
