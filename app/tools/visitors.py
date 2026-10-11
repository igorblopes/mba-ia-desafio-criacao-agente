"""Tools de visitantes: adaptadores finos sobre ``VisitorService``."""

from google.adk.tools import FunctionTool, ToolContext

from app.domain.errors import ApartmentNotFoundError, InvalidVisitorNameError, StorageBusyError
from app.services.provider import get_visitor_service
from app.tools.context import (
    InvalidDateError,
    MissingSessionApartmentError,
    get_session_apartment,
    invalid_date,
    invalid_session,
    storage_busy,
    parse_date,
)


async def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados do morador que está conversando."""
    try:
        apartment = get_session_apartment(tool_context)
        visitantes = await get_visitor_service().list_visitors(apartment)
    except StorageBusyError:
        return storage_busy()
    except (MissingSessionApartmentError, ApartmentNotFoundError):
        return invalid_session()
    return {
        "status": "success",
        "visitantes": [{"nome": v.nome, "data": v.data.isoformat()} for v in visitantes],
    }


async def solicitar_autorizacao_visitante(
    nome: str, data: str, tool_context: ToolContext
) -> dict:
    """Solicita a autorização de um visitante. Depende de etapa posterior e nada é gravado agora.

    Args:
        nome: Nome completo do visitante.
        data: Data da visita no formato AAAA-MM-DD.
    """
    try:
        apartment = get_session_apartment(tool_context)
        date = parse_date(data)
        result = await get_visitor_service().request_authorization(apartment, nome, date)
    except StorageBusyError:
        return storage_busy()
    except (MissingSessionApartmentError, ApartmentNotFoundError):
        return invalid_session()
    except InvalidDateError:
        return invalid_date()
    except InvalidVisitorNameError:
        return {"status": "invalid_input", "message": "O nome do visitante não pode ser vazio."}
    return {
        "status": "requires_confirmation",
        "nome": result.visitor_name,
        "data": result.date.isoformat(),
    }


listar_meus_visitantes_tool = FunctionTool(func=listar_meus_visitantes)
solicitar_autorizacao_visitante_tool = FunctionTool(func=solicitar_autorizacao_visitante)

VISITOR_TOOLS = [listar_meus_visitantes_tool, solicitar_autorizacao_visitante_tool]
