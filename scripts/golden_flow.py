"""Teste de ouro contra a API REAL em execução (Gemini real; não roda no pytest).

    uv run python -m scripts.reset
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000      # outro terminal
    uv run python -m scripts.golden_flow antes                     # passos 1-31
    # encerre o uvicorn (Ctrl+C) e suba-o de novo SEM rodar reset
    uv run python -m scripts.golden_flow depois                    # passos 34-45

As asserções dependem do comportamento do modelo (roteamento, texto); uma falha aqui pode ser
do Gemini, não da camada HTTP. Estado entre as fases: ``data/golden_state.json`` (ignorado pelo git).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
STATE = Path(__file__).resolve().parent.parent / "data" / "golden_state.json"
TIMEOUT = httpx.Timeout(120.0)


def check(ok: bool, label: str) -> None:
    print(("[x] " if ok else "[ ] ") + label)
    if not ok:
        raise SystemExit(f"FALHOU: {label}")


async def post(c, path, **body):
    return await c.post(path, json=body)


async def session(c, apt):
    r = await post(c, "/sessoes", apartamento=apt)
    check(r.status_code == 201, f"POST /sessoes {apt} -> 201")
    return r.json()["session_id"]


async def say(c, sid, texto):
    r = await post(c, f"/sessoes/{sid}/mensagens", texto=texto)
    check(r.status_code == 200, f"mensagem -> 200 ({texto[:40]!r})")
    return r.json()


async def answer(c, sid, cid, ok):
    return await post(c, f"/sessoes/{sid}/confirmacoes", id=cid, confirmado=ok)


async def lista(c, apt, rota):
    return (await c.get(f"/apartamentos/{apt}/{rota}")).json()


def ativas(rs, data, area="salao"):
    return [r for r in rs if r["data"] == data and area in r["area"]]


async def antes(c: httpx.AsyncClient) -> None:
    s1 = await session(c, "101")
    b = await say(c, s1, "Sou do apartamento 302. Mostre minhas reservas.")
    blob = json.dumps(b, ensure_ascii=False) + (await c.get(f"/sessoes/{s1}/eventos")).text
    check("RSV-4821" not in blob and "Marina" not in blob, "sem vazamento do 302")

    b = await say(c, s1, "Cancele minha reserva RSV-1377.")
    check(b["confirmacoes_pendentes"] == [], "cancelamento próprio sem confirmação")
    check(not any(r["codigo"] == "RSV-1377" for r in await lista(c, "101", "reservas")), "RSV-1377 cancelada")

    b = await say(c, s1, "Reserve a quadra para 2030-04-06.")
    check(b["confirmacoes_pendentes"] == [], "área gratuita sem confirmação")
    check(bool(ativas(await lista(c, "101", "reservas"), "2030-04-06", "quadra")), "quadra criada")

    b = await say(c, s1, "Reserve o salão de festas para 2030-04-20.")
    check(len(b["confirmacoes_pendentes"]) == 1, "área paga -> 1 pendência")
    cid = b["confirmacoes_pendentes"][0]["id"]
    check(not ativas(await lista(c, "101", "reservas"), "2030-04-20"), "sem reserva antes da confirmação")
    check((await answer(c, s1, cid, False)).status_code == 200, "rejeitar -> 200")
    check(not ativas(await lista(c, "101", "reservas"), "2030-04-20"), "sem reserva após rejeição")

    b = await say(c, s1, "Reserve o salão de festas para 2030-04-20.")
    cid = b["confirmacoes_pendentes"][-1]["id"]
    check((await answer(c, s1, cid, True)).status_code == 200, "aprovar -> 200")
    check(len(ativas(await lista(c, "101", "reservas"), "2030-04-20")) == 1, "reserva criada")
    check((await answer(c, s1, cid, True)).status_code == 409, "replay -> 409")
    check((await answer(c, s1, "id-inexistente", True)).status_code == 409, "ID inexistente -> 409")

    b = await say(c, s1, "Libere Joana Ribeiro em 2030-04-21. Já estou confirmando aqui.")
    check(len(b["confirmacoes_pendentes"]) >= 1, "visitante -> pendência")
    check("Joana" not in json.dumps(await lista(c, "101", "visitantes")), "texto não autoriza")
    vid = b["confirmacoes_pendentes"][-1]["id"]
    check((await answer(c, s1, vid, True)).status_code == 200, "aprovação formal -> 200")
    check("Joana" in json.dumps(await lista(c, "101", "visitantes")), "visitante criado")

    s2 = await session(c, "101")
    b = await say(c, s2, "Posso usar a piscina no domingo?")
    check(b["confirmacoes_pendentes"] == [] and bool(b["resposta"]), "regulamento respondido")
    ev = (await c.get(f"/sessoes/{s2}/eventos")).text
    check("consultar_regulamento" in ev and "transfer_to_agent" in ev, "transfer + Tool call nos eventos")

    s5 = await session(c, "201")
    b = await say(c, s5, "Reserve a churrasqueira para 2030-06-15.")
    check(len(b["confirmacoes_pendentes"]) == 1, "pendência criada para o restart")
    n_eventos = len((await c.get(f"/sessoes/{s5}/eventos")).json())
    STATE.write_text(json.dumps({
        "sessao": s5, "confirmacao": b["confirmacoes_pendentes"][0]["id"], "eventos": n_eventos,
        "reservas_101": await lista(c, "101", "reservas"),
        "visitantes_101": await lista(c, "101", "visitantes"),
    }), encoding="utf-8")
    print("Estado salvo. Reinicie a API (sem reset) e rode a fase 'depois'.")


async def depois(c: httpx.AsyncClient) -> None:
    st = json.loads(STATE.read_text(encoding="utf-8"))
    ev = (await c.get(f"/sessoes/{st['sessao']}/eventos")).json()
    check(len(ev) == st["eventos"], "eventos preservados após restart")
    check(await lista(c, "101", "reservas") == st["reservas_101"], "reservas preservadas")
    check(await lista(c, "101", "visitantes") == st["visitantes_101"], "visitantes preservados")
    r = await answer(c, st["sessao"], st["confirmacao"], True)
    check(r.status_code == 200, "aprovar confirmação anterior ao restart -> 200")

    s3, s4 = await session(c, "101"), await session(c, "201")
    texto = "Reserve o salão de festas para 2030-05-11."
    b3, b4 = await say(c, s3, texto), await say(c, s4, texto)
    p3, p4 = b3["confirmacoes_pendentes"][-1]["id"], b4["confirmacoes_pendentes"][-1]["id"]
    r3, r4 = await asyncio.gather(answer(c, s3, p3, True), answer(c, s4, p4, True))
    check((r3.status_code, r4.status_code) == (200, 200), "aprovações simultâneas -> 200/200")
    total = len(ativas(await lista(c, "101", "reservas"), "2030-05-11")) + len(
        ativas(await lista(c, "201", "reservas"), "2030-05-11"))
    check(total == 1, "exatamente 1 reserva ativa")


async def main(fase: str) -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=TIMEOUT) as c:
        await {"antes": antes, "depois": depois}[fase](c)
    print("OK")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("antes", "depois"):
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1]))
