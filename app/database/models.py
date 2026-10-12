"""Modelos SQLAlchemy 2.x do domínio do condomínio (``condominio.db``).

Nada aqui conhece regras de negócio: apenas estrutura e integridade.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.types import ConfirmationStatus

STATUS_ATIVA = "ATIVA"
STATUS_CANCELADA = "CANCELADA"
STATUS_RESERVA = (STATUS_ATIVA, STATUS_CANCELADA)


class Base(DeclarativeBase):
    pass


class Apartamento(Base):
    __tablename__ = "apartamentos"

    # Textual de propósito: identificador, nunca valor numérico.
    numero: Mapped[str] = mapped_column(String, primary_key=True)
    morador: Mapped[str] = mapped_column(String, nullable=False)


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nome: Mapped[str] = mapped_column(String, nullable=False)
    # Dinheiro em centavos inteiros (R$ 150,00 -> 15000). Sem FLOAT.
    taxa_centavos: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (CheckConstraint("taxa_centavos >= 0", name="ck_areas_taxa_nao_negativa"),)


class Reserva(Base):
    __tablename__ = "reservas"

    # PK permanente: reservas canceladas NÃO são apagadas, então o código
    # nunca pode ser reutilizado.
    codigo: Mapped[str] = mapped_column(String, primary_key=True)
    apartamento: Mapped[str] = mapped_column(
        String, ForeignKey("apartamentos.numero"), nullable=False, index=True
    )
    area: Mapped[str] = mapped_column(String, ForeignKey("areas.id"), nullable=False)
    data: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=STATUS_ATIVA)

    __table_args__ = (
        CheckConstraint(
            "status IN ('ATIVA', 'CANCELADA')", name="ck_reservas_status_valido"
        ),
        # Garantia 5: no máximo UMA reserva ATIVA por área/data, imposta pelo
        # banco no instante da gravação. Reservas CANCELADAS não participam.
        Index(
            "uq_reservas_area_data_ativa",
            "area",
            "data",
            unique=True,
            sqlite_where=text("status = 'ATIVA'"),
        ),
    )


class Visitante(Base):
    __tablename__ = "visitantes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    apartamento: Mapped[str] = mapped_column(
        String, ForeignKey("apartamentos.numero"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dt.date] = mapped_column(Date, nullable=False)


_CONFIRMATION_STATUSES = ", ".join(f"'{s.value}'" for s in ConfirmationStatus)


class Confirmacao(Base):
    """Estado PÚBLICO de uma confirmação (o ADK guarda sessão/eventos em outro banco).

    ``id`` é o ``function_call_id`` da chamada ``adk_request_confirmation``. Não guarda
    apartamento: a identidade vem sempre de ``session.state``. Datas em UTC.
    """

    __tablename__ = "confirmacoes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    invocation_id: Mapped[str] = mapped_column(String, nullable=False)
    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    acao: Mapped[str] = mapped_column(String, nullable=False)
    detalhes_json: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=ConfirmationStatus.PENDING.value
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    responded_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"status IN ({_CONFIRMATION_STATUSES})", name="ck_confirmacoes_status_valido"
        ),
        Index("ix_confirmacoes_session_status", "session_id", "status"),
    )
