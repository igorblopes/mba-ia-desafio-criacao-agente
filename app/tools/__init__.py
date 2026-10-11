"""Fronteiras entre os agentes e as operações permitidas pela aplicação."""

from app.tools.reservations import RESERVATION_TOOLS
from app.tools.visitors import VISITOR_TOOLS

PUBLIC_TOOLS = [*RESERVATION_TOOLS, *VISITOR_TOOLS]

__all__ = ["PUBLIC_TOOLS", "RESERVATION_TOOLS", "VISITOR_TOOLS"]
