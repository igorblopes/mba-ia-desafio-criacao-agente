"""Tools de visitantes: adaptadores finos sobre ``VisitorService``."""

from google.adk.tools import FunctionTool, ToolContext

from app.domain.errors import ApartmentNotFoundError, InvalidVisitorNameError, StorageBusyError
from app.runtime.actions import ACTION_AUTHORIZE_VISITOR
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
    """Solicita a autorização de um visitante. Sempre exige confirmação formal; nada é gravado antes dela.

    Args:
        nome: Nome completo do visitante.
        data: Data da visita no formato AAAA-MM-DD.
    """
    try:
        apartment = get_session_apartment(tool_context)
        date = parse_date(data)
        service = get_visitor_service()
        result = await service.request_authorization(apartment, nome, date)

        details = {
            "acao": ACTION_AUTHORIZE_VISITOR,
            "nome": result.visitor_name,
            "data": result.date.isoformat(),
        }
        # Confirmação somente via tool_context.tool_confirmation (resposta formal ao ADK).
        confirmation = getattr(tool_context, "tool_confirmation", None)
        if confirmation is None:
            tool_context.request_confirmation(
                hint="A autorização libera a entrada de um visitante e precisa de confirmação.",
                payload=details,
            )
            return {"status": "pending_confirmation", **details}
        if not confirmation.confirmed:
            return {"status": "rejected"}
        view = await service.create_confirmed_authorization(
            apartment, result.visitor_name, result.date
        )
    except StorageBusyError:
        return storage_busy()
    except (MissingSessionApartmentError, ApartmentNotFoundError):
        return invalid_session()
    except InvalidDateError:
        return invalid_date()
    except InvalidVisitorNameError:
        return {"status": "invalid_input", "message": "O nome do visitante não pode ser vazio."}
    return {"status": "authorized", "nome": view.nome, "data": view.data.isoformat()}


listar_meus_visitantes_tool = FunctionTool(func=listar_meus_visitantes)
solicitar_autorizacao_visitante_tool = FunctionTool(func=solicitar_autorizacao_visitante)

VISITOR_TOOLS = [listar_meus_visitantes_tool, solicitar_autorizacao_visitante_tool]
