"""Fixtures da suíte adversarial. Cada teste: SQLite temporário recriado de ``dados/``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest_asyncio
from sqlalchemy import func, select

from app.database.models import Confirmacao, Reserva, Visitante
from app.main import create_app

# Texto que NUNCA pode aparecer em saída conversacional/erro de quem não é dono do dado.
OWNER_SECRETS_302 = ("302", "Rafael", "Moreira", "Marina", "Duarte")
INTERNALS = ("Traceback", "sqlite", "SELECT ", "INSERT ", "UNIQUE", "IntegrityError",
             "OperationalError", ".db", "database is locked", "constraint", "File \"")


@dataclass
class World:
    client: httpx.AsyncClient
    factory: Any
    app: Any

    async def session(self, apartamento: str = "101") -> str:
        r = await self.client.post("/sessoes", json={"apartamento": apartamento})
        assert r.status_code == 201, r.text
        return r.json()["session_id"]

    async def say(self, sid: str, texto: str) -> httpx.Response:
        return await self.client.post(f"/sessoes/{sid}/mensagens", json={"texto": texto})

    async def ok(self, sid: str, texto: str) -> dict:
        r = await self.say(sid, texto)
        assert r.status_code == 200, f"{texto!r} -> {r.status_code} {r.text}"
        return r.json()

    async def answer(self, sid: str, cid: str, confirmado: Any) -> httpx.Response:
        return await self.client.post(
            f"/sessoes/{sid}/confirmacoes", json={"id": cid, "confirmado": confirmado})

    async def events(self, sid: str) -> list[dict]:
        r = await self.client.get(f"/sessoes/{sid}/eventos")
        assert r.status_code == 200, r.text
        return r.json()

    # ---- evidência no banco (nunca texto do modelo)
    async def active(self, area: str, data: str) -> list[Reserva]:
        import datetime as dt
        async with self.factory() as s:
            return list(await s.scalars(select(Reserva).where(
                Reserva.area == area, Reserva.data == dt.date.fromisoformat(data),
                Reserva.status == "ATIVA")))

    async def reserva(self, codigo: str) -> Reserva | None:
        async with self.factory() as s:
            return await s.scalar(select(Reserva).where(Reserva.codigo == codigo))

    async def all_codes(self) -> list[str]:
        async with self.factory() as s:
            return list(await s.scalars(select(Reserva.codigo)))

    async def count_reservas(self) -> int:
        async with self.factory() as s:
            return await s.scalar(select(func.count()).select_from(Reserva))

    async def visitors(self, apartamento: str) -> list[str]:
        async with self.factory() as s:
            return list(await s.scalars(
                select(Visitante.nome).where(Visitante.apartamento == apartamento)))

    async def confirmation_status(self, cid: str) -> str | None:
        async with self.factory() as s:
            return await s.scalar(select(Confirmacao.status).where(Confirmacao.id == cid))


def calls_and_responses(events: list[dict]) -> tuple[list[dict], list[dict]]:
    calls, responses = [], []
    for ev in events:
        for part in (ev.get("content") or {}).get("parts") or []:
            if part.get("function_call"):
                calls.append(part["function_call"])
            if part.get("function_response"):
                responses.append(part["function_response"])
    return calls, responses


def non_user_output(events: list[dict]) -> str:
    """O que o SISTEMA devolveu: texto do modelo + respostas de Tool.

    Exclui a fala do usuário e os ARGUMENTOS das chamadas (são as tentativas do modelo hostil,
    não dados devolvidos). Vazamento = dado privado em texto ou em function_response.
    """
    chunks = []
    for ev in events:
        if ev.get("author") == "user":
            continue
        for part in (ev.get("content") or {}).get("parts") or []:
            if part.get("text"):
                chunks.append(part["text"])
            if part.get("function_response"):
                fr = part["function_response"]  # sem o ``id`` (UUID aleatório pode conter "302")
                chunks.append(json.dumps({"name": fr.get("name"), "response": fr.get("response")},
                                         ensure_ascii=False))
    return "\n".join(chunks)


def tool_responses(events: list[dict], name: str) -> list[dict]:
    return [r["response"] for r in calls_and_responses(events)[1] if r.get("name") == name]


@pytest_asyncio.fixture
async def world(session_factory, tmp_path):
    from app.runtime.adk_runtime import build_adk_runtime
    from tests.adversarial.hostile_plan import plan
    from tests.fake_llm import ScriptedLlm

    url = f"sqlite+aiosqlite:///{(tmp_path / 'adk_sessions.db').as_posix()}"

    def factory():
        return build_adk_runtime(
            domain_session_factory=session_factory, session_db_url=url, llm=ScriptedLlm(plan=plan))

    app = create_app(factory)
    async with app.router.lifespan_context(app):
        # raise_app_exceptions=False: um 500 aparece como resposta (evidência), não como exceção.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as c:
            yield World(c, session_factory, app)
