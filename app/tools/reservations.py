"""Tools de reservas: adaptadores finos sobre ``ReservationService``.

O modelo informa apenas área, data e código. O apartamento vem do estado da
sessão; ``tool_context`` é injetado pelo ADK e não aparece no schema do modelo.
"""

from google.adk.tools import FunctionTool, ToolContext

from app.domain.errors import (
    ApartmentNotFoundError,
    AreaNotFoundError,
    AreaUnavailableError,
    DomainError,
    ReservationNotFoundError,
    StorageBusyError,
)
from app.domain.types import RequestStatus
from app.services.provider import get_reservation_service
from app.tools.context import (
    InvalidDateError,
    MissingSessionApartmentError,
    get_session_apartment,
    invalid_date,
    invalid_session,
    storage_busy,
    parse_date,
)


async def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do morador que está conversando."""
    try:
        apartment = get_session_apartment(tool_context)
        reservas = await get_reservation_service().list_active_reservations(apartment)
    except StorageBusyError:
        return storage_busy()
    except (MissingSessionApartmentError, ApartmentNotFoundError):
        return invalid_session()
    return {
        "status": "success",
        "reservas": [
            {"codigo": r.codigo, "area": r.area_id, "data": r.data.isoformat()}
            for r in reservas
        ],
    }


async def verificar_disponibilidade(
    area_id: str, data: str, tool_context: ToolContext
) -> dict:
    """Informa se uma área comum está disponível em uma data (AAAA-MM-DD).

    Args:
        area_id: Identificador da área comum (ex.: "quadra", "churrasqueira").
        data: Data desejada no formato AAAA-MM-DD.
    """
    try:
        get_session_apartment(tool_context)  # apenas valida que há sessão válida
        date = parse_date(data)
        disponivel = await get_reservation_service().is_available(area_id, date)
    except StorageBusyError:
        return storage_busy()
    except MissingSessionApartmentError:
        return invalid_session()
    except InvalidDateError:
        return invalid_date()
    except AreaNotFoundError:
        return {"status": "area_not_found", "message": "Área comum não encontrada."}
    return {"status": "success", "disponivel": disponivel}


async def solicitar_reserva(area_id: str, data: str, tool_context: ToolContext) -> dict:
    """Solicita a reserva de uma área comum para o morador que está conversando.

    Áreas gratuitas são reservadas imediatamente; áreas com taxa só informam o
    valor e dependem de uma etapa posterior, sem gravar nada agora.

    Args:
        area_id: Identificador da área comum.
        data: Data desejada no formato AAAA-MM-DD.
    """
    try:
        apartment = get_session_apartment(tool_context)
        date = parse_date(data)
        result = await get_reservation_service().request_reservation(apartment, area_id, date)
    except StorageBusyError:
        return storage_busy()
    except (MissingSessionApartmentError, ApartmentNotFoundError):
        return invalid_session()
    except InvalidDateError:
        return invalid_date()
    except AreaNotFoundError:
        return {"status": "area_not_found", "message": "Área comum não encontrada."}
    except AreaUnavailableError:
        return {
            "status": "unavailable",
            "message": "A área não está disponível na data solicitada.",
        }
    except DomainError:
        return {"status": "error", "message": "Não foi possível processar a reserva."}

    if result.status is RequestStatus.CREATED:
        return {
            "status": "created",
            "codigo": result.reservation_code,
            "area": result.area_id,
            "data": result.date.isoformat(),
        }
    return {
        "status": "requires_confirmation",
        "area": result.area_id,
        "data": result.date.isoformat(),
        "taxa_centavos": result.fee_cents,
    }


async def cancelar_minha_reserva(codigo: str, tool_context: ToolContext) -> dict:
    """Cancela uma reserva ativa do próprio morador, pelo código.

    Args:
        codigo: Código da reserva (ex.: "RSV-1377").
    """
    try:
        apartment = get_session_apartment(tool_context)
        view = await get_reservation_service().cancel_reservation(apartment, codigo)
    except StorageBusyError:
        return storage_busy()
    except (MissingSessionApartmentError, ApartmentNotFoundError):
        return invalid_session()
    except ReservationNotFoundError:
        return {"status": "not_found"}
    return {
        "status": "cancelled",
        "codigo": view.codigo,
        "area": view.area_id,
        "data": view.data.isoformat(),
    }


listar_minhas_reservas_tool = FunctionTool(func=listar_minhas_reservas)
verificar_disponibilidade_tool = FunctionTool(func=verificar_disponibilidade)
solicitar_reserva_tool = FunctionTool(func=solicitar_reserva)
cancelar_minha_reserva_tool = FunctionTool(func=cancelar_minha_reserva)

RESERVATION_TOOLS = [
    listar_minhas_reservas_tool,
    verificar_disponibilidade_tool,
    solicitar_reserva_tool,
    cancelar_minha_reserva_tool,
]
