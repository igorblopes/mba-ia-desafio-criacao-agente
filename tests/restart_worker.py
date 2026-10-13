"""Processo de trabalho para o teste de restart REAL (um processo Python por fase).

    python -m tests.restart_worker <fase> [opções]      (DOMAIN_DATABASE_URL e
    ADK_SESSION_DATABASE_URL vêm do ambiente; o LLM é roteirizado, sem rede)

Fases: ``setup`` (reset do domínio) | ``create`` | ``inspect`` | ``resume`` | ``count``.
Cada fase constrói do zero engine, DatabaseSessionService, App, Runner e AdkRuntime e imprime
UMA linha JSON no stdout. Nada é compartilhado entre fases além dos arquivos SQLite.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from sqlalchemy import func, select

from app.database.connection import create_domain_engine, create_session_factory
from app.database.models import Confirmacao, Reserva, Visitante
from app.domain.errors import ConfirmationNotPendingError
from app.runtime.adk_runtime import build_adk_runtime
from scripts.reset import reset_domain
from tests.fake_llm import ScriptedLlm
from tests.scripted_plan import plan


async def _counts(factory) -> dict:
    async with factory() as s:
        reservas = list(await s.scalars(select(Reserva)))
        joanas = (await s.scalar(select(func.count()).select_from(Visitante).where(
            Visitante.nome.like("Joana%")))) or 0
        confs = {c.id: c.status for c in await s.scalars(select(Confirmacao))}
    return {
        "reservas_salao_0420": len([r for r in reservas
                                    if r.area == "salao-de-festas" and r.data.isoformat() == "2030-04-20"]),
        "joana": joanas,
        "confirmacoes": confs,
    }


async def main(args: argparse.Namespace) -> dict:
    if args.phase == "setup":
        await reset_domain()
        return {"ok": True}

    engine = create_domain_engine()
    factory = create_session_factory(engine)
    runtime = build_adk_runtime(domain_session_factory=factory, llm=ScriptedLlm(plan=plan))
    try:
        if args.phase == "count":
            return await _counts(factory)
        if args.phase == "create":
            info = await runtime.create_session(args.apartment)
            result = await runtime.send_message(info.id, args.message)
            [p] = result.pending_confirmations
            return {
                "session_id": info.id, "confirmation_id": p.id, "invocation_id": p.invocation_id,
                "agent_name": p.agent_name, "status": p.status.value,
                "events": await runtime.get_events(info.id), "event_count": result.event_count, "counts": await _counts(factory),
            }
        session = await runtime.get_session(args.session_id)
        if args.phase == "inspect":
            pend = await runtime.list_pending_confirmations(args.session_id)
            events = await runtime.get_event_views(args.session_id)
            return {
                "apartment": session.apartment, "event_count": session.event_count,
                "events": await runtime.get_events(args.session_id),
                "event_kinds": [e.kind for e in events],
                "pending": [{"id": p.id, "invocation_id": p.invocation_id, "status": p.status.value}
                            for p in pend],
                "counts": await _counts(factory),
            }
        if args.phase == "resume":
            seen: list[str] = []  # apartamento que as Tools realmente leram do ToolContext
            import app.tools.reservations as _res
            import app.tools.visitors as _vis

            for mod in (_res, _vis):
                original = mod.get_session_apartment
                mod.get_session_apartment = (
                    lambda ctx, _o=original: (seen.append(_o(ctx)) or seen[-1]))
            try:
                res = await runtime.resume_confirmation(
                    args.session_id, args.confirmation_id, args.confirmed == "true")
            except ConfirmationNotPendingError as exc:
                return {"error": type(exc).__name__, "counts": await _counts(factory),
                        "event_count": (await runtime.get_session(args.session_id)).event_count}
            return {
                "status": res.status.value, "tool_result": res.tool_result,
                "invocation_id": res.invocation_id, "agent_name": res.agent_name,
                "apartment": session.apartment, "tool_context_apartment": seen,
                "events": await runtime.get_events(args.session_id), "event_count_after": res.event_count,
                "event_kinds": [e.kind for e in res.new_events], "counts": await _counts(factory),
            }
        raise SystemExit(f"fase desconhecida: {args.phase}")
    finally:
        await runtime.close()
        await engine.dispose()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["setup", "create", "inspect", "resume", "count"])
    parser.add_argument("--apartment", default="101")
    parser.add_argument("--message", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--confirmation-id", default="")
    parser.add_argument("--confirmed", default="true")
    out = asyncio.run(main(parser.parse_args()))
    sys.stdout.write("RESULT " + json.dumps(out, default=str) + "\n")
