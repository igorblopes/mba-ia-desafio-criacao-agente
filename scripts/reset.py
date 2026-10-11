"""Restaura ``condominio.db`` ao estado inicial a partir de ``dados/``.

    uv run python -m scripts.reset             # só o banco de domínio
    uv run python -m scripts.reset --sessions  # também apaga adk_sessions.db

Fluxo permitido: dados/ -> leitura -> condominio.db. ``dados/`` nunca é escrito.
Idempotente: o esquema é recriado do zero e os dados reimportados a cada execução.
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
        "--sessions",
        action="store_true",
        help="apaga também adk_sessions.db (apenas desenvolvimento)",
    )
    args = parser.parse_args()

    settings = get_settings()
    db_file = _sqlite_file(settings.domain_database_url)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    counts = asyncio.run(reset_domain())
    print(f"condominio.db restaurado em {db_file}")
    for tabela, n in counts.items():
        print(f"  {tabela}: {n}")

    if args.sessions:
        removed = delete_sessions_db()
        print(f"adk_sessions.db removido ({len(removed)} arquivo(s))")
    else:
        print("adk_sessions.db preservado")


if __name__ == "__main__":
    main()
