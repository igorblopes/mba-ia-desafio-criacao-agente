"""Valida constraints do banco de domínio (sem LLM).

    uv run python -m scripts.check_constraints

Limpa o que criou chamando ``reset`` no final.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database.connection import create_domain_engine, create_session_factory
from app.database.models import STATUS_ATIVA, STATUS_CANCELADA, Reserva
from app.repositories.reservation_repository import ReservationRepository
from scripts.reset import reset_domain

DIA = dt.date(2035, 1, 1)


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def nova(codigo: str, apto: str = "102", area: str = "quadra", status: str = STATUS_ATIVA) -> Reserva:
    return Reserva(codigo=codigo, apartamento=apto, area=area, data=DIA, status=status)


async def expect_integrity_error(factory, reserva: Reserva) -> None:
    async with factory() as s:
        repo = ReservationRepository(s)
        try:
            await repo.insert(reserva)
            await s.commit()
        except IntegrityError:
            # o repository já fez rollback: a sessão deve continuar utilizável
            assert (await s.execute(text("SELECT 1"))).scalar() == 1
            return
    raise AssertionError(f"esperava IntegrityError para {reserva.codigo}")


async def main() -> None:
    await reset_domain()
    engine = create_domain_engine()
    factory = create_session_factory(engine)
    try:
        async with engine.connect() as c:
            assert (await c.execute(text("PRAGMA foreign_keys"))).scalar() == 1
            assert (await c.execute(text("PRAGMA journal_mode"))).scalar() == "wal"
            assert (await c.execute(text("PRAGMA busy_timeout"))).scalar() == 5000
        ok("PRAGMAs: foreign_keys=1, journal_mode=wal, busy_timeout=5000")

        # ATIVA + ATIVA (mesma área/data) -> bloqueado pelo banco
        async with factory.begin() as s:
            await ReservationRepository(s).insert(nova("RSV-TESTE-1"))
        await expect_integrity_error(factory, nova("RSV-TESTE-2"))
        ok("ATIVA + ATIVA na mesma área/data: BLOQUEADO (IntegrityError do índice parcial)")

        # CANCELADA + ATIVA -> permitido
        async with factory.begin() as s:
            assert await ReservationRepository(s).set_status("RSV-TESTE-1", STATUS_CANCELADA)
        async with factory.begin() as s:
            await ReservationRepository(s).insert(nova("RSV-TESTE-2"))
        ok("RSV-TESTE-1 CANCELADA, depois RSV-TESTE-2 ATIVA na mesma área/data: PERMITIDO")

        # cancelada + cancelada também não conflita
        async with factory.begin() as s:
            await ReservationRepository(s).insert(nova("RSV-TESTE-3", status=STATUS_CANCELADA))
        ok("múltiplas CANCELADAS na mesma área/data: permitido")

        # reativar RSV-TESTE-1 (-> ATIVA) conflitaria com RSV-TESTE-2 ativa
        async with factory() as s:
            try:
                await ReservationRepository(s).set_status("RSV-TESTE-3", STATUS_ATIVA)
                raise AssertionError("reativação deveria conflitar")
            except IntegrityError:
                pass
        ok("reativar reserva em área/data já ocupada: BLOQUEADO")

        # código único mesmo após cancelamento
        await expect_integrity_error(factory, nova("RSV-TESTE-1", area="churrasqueira"))
        ok("código RSV-TESTE-1 (CANCELADA) não pode ser reutilizado: BLOQUEADO")

        # FKs
        await expect_integrity_error(factory, nova("RSV-TESTE-FK1", apto="999", area="quadra"))
        ok("FK apartamento inexistente: BLOQUEADO")
        await expect_integrity_error(factory, nova("RSV-TESTE-FK2", area="inexistente"))
        ok("FK área inexistente: BLOQUEADO")

        # status inválido
        await expect_integrity_error(factory, nova("RSV-TESTE-ST", status="EXCLUIDA"))
        ok("status fora de ATIVA/CANCELADA: BLOQUEADO (CHECK)")
    finally:
        await engine.dispose()
        await reset_domain()
        ok("reset executado: registros de teste removidos")


if __name__ == "__main__":
    asyncio.run(main())
