"""Prova que sessão + state + evento do ADK sobrevivem a um reinício de processo.

    uv run python -m scripts.check_session_persistence

O orquestrador dispara DOIS processos Python distintos:
  1. ``--phase create``: abre DatabaseSessionService, cria a sessão com
     state["apartamento"] = "101", anexa um evento mínimo e encerra.
  2. ``--phase read``: novo processo, novo serviço, mesmo ``adk_sessions.db``;
     recupera a sessão e confere state e evento.
Sem agente e sem LLM. A sessão de teste é removida ao final (use --keep para manter).
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys

from google.adk.events import Event
from google.genai import types

from app.runtime.session_service import create_session_service

APP_NAME = "residencial-aurora-check"
USER_ID = "usuario-check"
SESSION_ID = "sessao-persistencia-passo2"
APARTAMENTO = "101"
TEXTO = "evento minimo de persistencia"


async def phase_create() -> None:
    service = create_session_service()
    try:
        await service.delete_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
        session = await service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=SESSION_ID,
            state={"apartamento": APARTAMENTO},
        )
        event = Event(
            author="user",
            content=types.Content(role="user", parts=[types.Part(text=TEXTO)]),
        )
        await service.append_event(session, event)
        print(f"[create] sessão criada: id={session.id} state={dict(session.state)}")
    finally:
        await service.close()


async def phase_read(keep: bool) -> None:
    service = create_session_service()  # serviço NOVO, processo NOVO
    try:
        session = await service.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
        )
        assert session is not None, "sessão não encontrada após reinício"
        assert session.state.get("apartamento") == APARTAMENTO, session.state
        textos = [
            p.text for e in session.events if e.content for p in (e.content.parts or []) if p.text
        ]
        assert TEXTO in textos, f"evento não persistiu: {textos}"
        print(
            f"[read] sessão recuperada: id={session.id} "
            f"state={dict(session.state)} eventos={len(session.events)}"
        )
        if not keep:
            await service.delete_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
            print("[read] sessão de teste removida")
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["create", "read"])
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    if args.phase == "create":
        asyncio.run(phase_create())
    elif args.phase == "read":
        asyncio.run(phase_read(args.keep))
    else:
        base = [sys.executable, "-m", "scripts.check_session_persistence"]
        subprocess.run([*base, "--phase", "create"], check=True)
        print("--- processo 1 encerrado; abrindo novo processo ---")
        subprocess.run([*base, "--phase", "read", *(["--keep"] if args.keep else [])], check=True)
        print("[OK] sessão, state['apartamento']=='101' e evento persistiram fisicamente")


if __name__ == "__main__":
    main()
