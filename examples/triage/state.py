"""The state schema for the triage graph.

State is the only thing nodes share. Everything a node needs to read must be a
field here, and everything it wants to hand on must be in the dict it returns.
"""

from __future__ import annotations

import operator
from typing import Annotated

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class TicketState(TypedDict, total=False):
    # --- inputs -------------------------------------------------------------
    ticket_id: str
    body: str

    # --- conversation with the model ----------------------------------------
    # `add_messages` appends, and replaces messages that share an id. Chapter 3
    # explains why plain `operator.add` is the wrong choice here.
    messages: Annotated[list, add_messages]

    # --- derived, last write wins -------------------------------------------
    category: str
    confidence: float
    draft: str
    escalated: bool

    # --- accumulated across nodes and across parallel branches ---------------
    # Every node appends one line. With no reducer, each would erase the last.
    trail: Annotated[list[str], operator.add]
    evidence: Annotated[list[str], operator.add]
