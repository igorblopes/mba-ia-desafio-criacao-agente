"""Plano do ``ScriptedLlm`` compartilhado pelos testes do Passo 8 (sem rede)."""

PAID = "Reserve o salão de festas para 2030-04-20."
PAID_0511 = "Reserve o salão de festas para 2030-05-11."
VISITOR = "Libere a entrada da Joana Ribeiro em 2030-04-21."


def plan(kind: str, text: str):
    if kind == "concierge":
        return "transfer_to_agent", {
            "agent_name": "visitor_agent" if "Libere" in text else "reservation_agent"}
    if kind == "reservation":
        data = "2030-05-11" if "2030-05-11" in text else "2030-04-20"
        return "solicitar_reserva", {"area_id": "salao-de-festas", "data": data}
    return "solicitar_autorizacao_visitante", {"nome": "Joana Ribeiro", "data": "2030-04-21"}
