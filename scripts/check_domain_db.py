"""Valida o estado inicial e o histórico de cancelamento (sem LLM).

    uv run python -m scripts.check_domain_db

Os valores esperados são lidos de ``dados/*.json`` (nada hardcoded).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json

from app.config import DADOS_DIR
from app.database.connection import create_domain_engine, create_session_factory
from app.database.models import STATUS_ATIVA, STATUS_CANCELADA
from app.repositories.apartment_repository import ApartmentRepository
from app.repositories.area_repository import AreaRepository
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.visitor_repository import VisitorRepository
from scripts.reset import reset_domain, to_centavos


def _json(name: str) -> list[dict]:
    return json.loads((DADOS_DIR / name).read_text(encoding="utf-8"))


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


async def main() -> None:
    engine = create_domain_engine()
    factory = create_session_factory(engine)
    try:
        # --- estado inicial vs JSONs ---------------------------------------
        async with factory() as s:
            apts = {a.numero: a.morador for a in await ApartmentRepository(s).list_all()}
            areas = {a.id: (a.nome, a.taxa_centavos) for a in await AreaRepository(s).list_all()}
            reservas = {r.codigo: r for r in await ReservationRepository(s).list_all()}
            visitantes = await VisitorRepository(s).list_all()

        assert apts == {a["numero"]: a["morador"] for a in _json("apartamentos.json")}
        ok(f"apartamentos importados ({len(apts)})")
        assert areas == {a["id"]: (a["nome"], to_centavos(a["taxa"])) for a in _json("areas.json")}
        ok(f"áreas importadas com taxa em centavos {({k: v[1] for k, v in areas.items()})}")
        assert len(reservas) == len(_json("reservas.json"))
        assert all(r.status == STATUS_ATIVA for r in reservas.values())
        ok(f"reservas importadas ({len(reservas)}), todas ATIVA")
        assert len(visitantes) == len(_json("visitantes.json"))
        ok(f"visitantes importados ({len(visitantes)})")

        # --- 101 / RSV-1377 e 302 / Marina Duarte, a partir dos JSONs --------
        esperado_r = next(r for r in _json("reservas.json") if r["codigo"] == "RSV-1377")
        async with factory() as s:
            do_101 = await ReservationRepository(s).list_by_apartment("101")
            do_302 = await VisitorRepository(s).list_by_apartment("302")
        r = next(r for r in do_101 if r.codigo == "RSV-1377")
        assert (r.apartamento, r.area, r.data) == (
            esperado_r["apartamento"], esperado_r["area"], dt.date.fromisoformat(esperado_r["data"])
        )
        ok(f"apto 101 possui {r.codigo} / {r.area} / {r.data}")
        esperado_v = next(v for v in _json("visitantes.json") if v["nome"] == "Marina Duarte")
        v = next(v for v in do_302 if v.nome == "Marina Duarte")
        assert (v.apartamento, v.data) == (esperado_v["apartamento"], dt.date.fromisoformat(esperado_v["data"]))
        ok(f"apto 302 possui visitante {v.nome} em {v.data}")

        # --- cancelamento != exclusão ----------------------------------------
        async with factory.begin() as s:
            assert await ReservationRepository(s).set_status("RSV-1377", STATUS_CANCELADA)
        async with factory() as s:
            c = await ReservationRepository(s).get("RSV-1377")
            total = len(await ReservationRepository(s).list_all())
        assert c is not None and c.status == STATUS_CANCELADA
        assert (c.apartamento, c.area, c.data) == (r.apartamento, r.area, r.data)
        assert total == len(reservas)
        ok("RSV-1377 -> CANCELADA: registro preservado, só o status mudou")

        # --- reset restaura ---------------------------------------------------
        await reset_domain()
        async with factory() as s:
            c = await ReservationRepository(s).get("RSV-1377")
        assert c is not None and c.status == STATUS_ATIVA
        assert (c.apartamento, c.area, c.data) == (r.apartamento, r.area, r.data)
        ok("reset restaurou RSV-1377 ao estado original (ATIVA)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
