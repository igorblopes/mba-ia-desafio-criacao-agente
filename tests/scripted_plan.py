"""Plano do ``ScriptedLlm`` compartilhado pelos testes (sem rede)."""

import re

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CODE = re.compile(r"RSV-\w+")

PAID = "Reserve o salão de festas para 2030-04-20."
PAID_0511 = "Reserve o salão de festas para 2030-05-11."
VISITOR = "Libere a entrada da Joana Ribeiro em 2030-04-21."
POOL = "Posso usar a piscina no domingo?"
_REGULATION_HINTS = ("piscina", "regulamento", "helicóptero", "regra")


def plan(kind: str, text: str):
    if kind == "concierge":
        if "Libere" in text:
            target = "visitor_agent"
        elif any(h in text.lower() for h in _REGULATION_HINTS):
            target = "regulation_agent"
        else:
            target = "reservation_agent"
        return "transfer_to_agent", {"agent_name": target}
    if kind == "regulation":
        return "consultar_regulamento", {"pergunta": text}
    if kind == "reservation":
        if "Cancele" in text:
            return "cancelar_minha_reserva", {"codigo": _CODE.search(text).group(0)}
        if "Mostre minhas reservas" in text:
            return "listar_minhas_reservas", {}
        found = _DATE.search(text)
        data = found.group(0) if found else "2030-04-20"
        area = "quadra" if "quadra" in text.lower() else "salao-de-festas"
        return "solicitar_reserva", {"area_id": area, "data": data}
    return "solicitar_autorizacao_visitante", {"nome": "Joana Ribeiro", "data": "2030-04-21"}
