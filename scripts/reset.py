"""Restaura ``condominio.db`` ao estado inicial a partir de ``dados/``.

    uv run python -m scripts.reset                  # condominio.db + confirmações + adk_sessions.db
    uv run python -m scripts.reset --keep-sessions  # só condominio.db (cuidado: confirmações PENDING somem)

RESET apaga estado de execução e volta ao ambiente inicial. RESTART (reiniciar o processo) não
apaga nada. Fluxo permitido: dados/ -> leitura -> condominio.db. ``dados/`` nunca é escrito.
Idempotente: o esquema é recriado do zero (inclui ``confirmacoes``) e os dados reimportados.
Sessões ADK são apagadas por padrão porque confirmações vivem em ``condominio.db``: manter
sessões com pedidos pendentes e zerar a tabela deixaria o ADK e a aplicação inconsistentes.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

from app.config import DADOS_DIR, get_settings
from app.database.connection import create_domain_engine, create_session_factory
from app.database.models import (
    STATUS_ATIVA,
    Apartamento,
    Area,
    Reserva,
    Visitante,
)
from app.database.schema import create_schema, drop_schema


def _load(name: str) -> list[dict]:
    return json.loads((DADOS_DIR / name).read_text(encoding="utf-8"))


def to_centavos(valor: int | float | str) -> int:
    """Converte reais em centavos sem erro de ponto flutuante (150.0 -> 15000)."""
    return int((Decimal(str(valor)) * 100).to_integral_value())


def _sqlite_file(url: str) -> Path:
    return Path(url.split(":///", 1)[1])


async def reset_domain(url: str | None = None) -> dict[str, int]:
    engine = create_domain_engine(url)
    try:
        await drop_schema(engine)
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory.begin() as session:
            session.add_all(
                Apartamento(numero=str(a["numero"]), morador=a["morador"])
                for a in _load("apartamentos.json")
            )
            session.add_all(
                Area(id=a["id"], nome=a["nome"], taxa_centavos=to_centavos(a["taxa"]))
                for a in _load("areas.json")
            )
            await session.flush()  # apartamentos/áreas antes das FKs de reservas/visitantes
            session.add_all(
                Reserva(
                    codigo=r["codigo"],
                    apartamento=str(r["apartamento"]),
                    area=r["area"],
                    data=dt.date.fromisoformat(r["data"]),
                    status=r.get("status", STATUS_ATIVA),
                )
                for r in _load("reservas.json")
            )
            session.add_all(
                Visitante(
                    apartamento=str(v["apartamento"]),
                    nome=v["nome"],
                    data=dt.date.fromisoformat(v["data"]),
                )
                for v in _load("visitantes.json")
            )
        return {
            "apartamentos": len(_load("apartamentos.json")),
            "areas": len(_load("areas.json")),
            "reservas": len(_load("reservas.json")),
            "visitantes": len(_load("visitantes.json")),
        }
    finally:
        await engine.dispose()


def delete_sessions_db() -> list[Path]:
    base = _sqlite_file(get_settings().adk_session_database_url)
    removed = []
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(base) + suffix)
        if p.exists():
            p.unlink()
            removed.append(p)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--keep-sessions",
        action="store_true",
        help="preserva adk_sessions.db (padrão: apagar, para um ambiente totalmente inicial)",
    )
    parser.add_argument(
        "--sessions",
        action="store_true",
        help="obsoleto: apagar sessões já é o padrão (aceito por compatibilidade)",
    )
    args = parser.parse_args()

    settings = get_settings()
    db_file = _sqlite_file(settings.domain_database_url)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    counts = asyncio.run(reset_domain())
    print(f"condominio.db restaurado em {db_file}")
    for tabela, n in counts.items():
        print(f"  {tabela}: {n}")

    if args.keep_sessions:
        print("adk_sessions.db preservado")
    else:
        removed = delete_sessions_db()
        print(f"adk_sessions.db removido ({len(removed)} arquivo(s)); recriado no próximo uso")


if __name__ == "__main__":
    main()
