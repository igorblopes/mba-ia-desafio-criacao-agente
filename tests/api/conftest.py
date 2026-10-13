"""Cliente HTTP em memória (httpx + ASGI) sobre o app real, com LLM roteirizado e bancos temporários."""

from __future__ import annotations

import httpx
import pytest_asyncio

from app.main import create_app


@pytest_asyncio.fixture
async def client(session_factory, tmp_path):
    from app.runtime.adk_runtime import build_adk_runtime
    from tests.fake_llm import ScriptedLlm
    from tests.scripted_plan import plan

    url = f"sqlite+aiosqlite:///{(tmp_path / 'adk_sessions.db').as_posix()}"

    def factory():
        return build_adk_runtime(
            domain_session_factory=session_factory, session_db_url=url, llm=ScriptedLlm(plan=plan)
        )

    app = create_app(factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # acesso ao app.state nos testes
            yield c


async def new_session(client, apartamento: str = "101") -> str:
    r = await client.post("/sessoes", json={"apartamento": apartamento})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def calls_and_responses(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """function_calls e function_responses (dicts) de todos os eventos, em ordem."""
    calls, responses = [], []
    for ev in events:
        for part in (ev.get("content") or {}).get("parts") or []:
            if part.get("function_call"):
                calls.append(part["function_call"])
            if part.get("function_response"):
                responses.append(part["function_response"])
    return calls, responses


async def reservas(client, apartamento: str) -> list[dict]:
    r = await client.get(f"/apartamentos/{apartamento}/reservas")
    assert r.status_code == 200, r.text
    return r.json()


async def visitantes(client, apartamento: str) -> list[dict]:
    r = await client.get(f"/apartamentos/{apartamento}/visitantes")
    assert r.status_code == 200, r.text
    return r.json()


async def say(client, session_id: str, texto: str) -> dict:
    r = await client.post(f"/sessoes/{session_id}/mensagens", json={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


async def answer(client, session_id: str, confirmation_id: str, confirmado: bool):
    return await client.post(
        f"/sessoes/{session_id}/confirmacoes", json={"id": confirmation_id, "confirmado": confirmado}
    )
