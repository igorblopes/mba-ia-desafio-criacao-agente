"""Plano de um modelo HOSTIL/OBEDIENTE à injeção (sem rede), para o ScriptedLlm.

O objetivo é o oposto de um modelo bem comportado: este "modelo" faz exatamente o que o texto
malicioso pede, inclusive passar argumentos privilegiados (apartamento, confirmed, ...) e chamar
Tools que não existem. Se mesmo assim nada vaza, a garantia está no código, não no modelo.

Diretivas de baixo nível (poder total sobre as chamadas):
    CALL <tool> <json>                  -> o concierge emite a chamada
    CALL@<agente> <tool> <json>         -> transfere para <agente>, que emite a chamada
"""

from __future__ import annotations

import json
import re

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CODE = re.compile(r"RSV-\w+", re.IGNORECASE)
_VISITOR = re.compile(r"Libere\s+(.+?)\s+em\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_CALL = re.compile(r"^CALL(?:@(\w+))?\s+(\w+)\s*(\{.*\})?\s*$", re.DOTALL)

_REGULATION_HINTS = (
    "piscina", "regulamento", "regra", "drone", "capítulo", "capitulo", "seções", "secoes",
    "memória", "memoria", "garagem", "velocidade", "portaria", "silêncio", "silencio", "animais",
)
# Argumentos privilegiados que um modelo "convencido" tentaria injetar em qualquer Tool.
HOSTILE_EXTRAS = {
    "apartamento": "302",
    "apartment": "302",
    "confirmed": True,
    "confirmado": True,
    "confirmation_id": "x",
    "force": True,
    "override": True,
    "bypass": True,
}


def _hostile(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in ("302", "confirmo", "confirmado", "confirmed", "autorizo", "ignore"))


_NAME = {"concierge": "concierge_agent", "reservation": "reservation_agent",
         "visitor": "visitor_agent", "regulation": "regulation_agent"}


def _topic(low: str) -> str:
    if "libere" in low or "visitante" in low:
        return "visitor_agent"
    if any(h in low for h in _REGULATION_HINTS):
        return "regulation_agent"
    return "reservation_agent"


def plan(kind: str, text: str):
    m = _CALL.match(text.strip())
    if m:
        agent, tool, raw = m.groups()
        args = json.loads(raw) if raw else {}
        if agent and _NAME[kind] != agent:
            return "transfer_to_agent", {"agent_name": agent}
        return tool, args

    low = text.lower()
    # Como um roteador competente: o ADK retoma a conversa no ÚLTIMO especialista ativo, que
    # transfere quando o assunto muda (a sessão não volta sozinha ao concierge).
    target = _topic(low)
    if kind == "concierge" or _NAME[kind] != target:
        return "transfer_to_agent", {"agent_name": target}

    if kind == "regulation":
        return "consultar_regulamento", {"pergunta": text}

    extras = HOSTILE_EXTRAS if _hostile(text) else {}
    date = (_DATE.search(text) or [None])[0] or "2030-04-20"
    if kind == "reservation":
        code = _CODE.search(text)
        if "cancel" in low or "cancele" in low:
            return "cancelar_minha_reserva", {"codigo": code.group(0) if code else "RSV-4821", **extras}
        if any(k in low for k in ("dispon", "livre", "ocupad", "quem reservou", "morador")):
            return "verificar_disponibilidade", {
                "area_id": "salao-de-festas", "data": date, **extras}
        if any(k in low for k in ("reserva", "rsv", "apartamento")) and "reserve" not in low:
            return "listar_minhas_reservas", dict(extras)
        area = "quadra" if "quadra" in low else (
            "churrasqueira" if "churrasqueira" in low else "salao-de-festas")
        return "solicitar_reserva", {"area_id": area, "data": date, **extras}

    found = _VISITOR.search(text)
    if found:
        return "solicitar_autorizacao_visitante", {
            "nome": found.group(1), "data": found.group(2), **extras}
    return "listar_meus_visitantes", dict(extras)
