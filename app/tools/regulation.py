"""Tool de consulta ao regulamento: adaptador fino sobre ``RegulationService`` (somente leitura)."""

from google.adk.tools import FunctionTool

from app.domain.errors import RegulationUnavailableError
from app.services.provider import get_regulation_service


async def consultar_regulamento(pergunta: str) -> dict:
    """Recupera os trechos do regulamento do condomínio relevantes para a pergunta.

    Args:
        pergunta: A dúvida do morador, em linguagem natural, sobre uma regra ou norma.
    """
    try:
        result = get_regulation_service().search(pergunta)
    except RegulationUnavailableError:
        return {"status": "temporarily_unavailable", "trechos": []}
    response: dict = {
        "status": result.status,
        "trechos": [{"secao": e.section, "conteudo": e.content} for e in result.excerpts],
    }
    if result.unmatched_terms:
        response["termos_nao_localizados"] = list(result.unmatched_terms)
    return response


consultar_regulamento_tool = FunctionTool(func=consultar_regulamento)

REGULATION_TOOLS = [consultar_regulamento_tool]
