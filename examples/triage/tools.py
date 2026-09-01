"""Tools for the triage agent.

Deliberately deterministic and in-memory: a tool that reaches the network makes
a chapter's output unreproducible. `flaky_lookup` is the exception -- Chapter 21
needs something that fails on purpose.
"""

from __future__ import annotations

from langchain_core.tools import tool

KB = {
    "billing": "Refunds are issued to the original payment method within 5 working days.",
    "sip-registration": "A 403 on REGISTER is almost always a realm or credential mismatch.",
    "packet-loss": "Check for CPU throttling on the media node before blaming the network.",
    "password": "Password resets are self-service at /account/reset.",
}

CUSTOMERS = {
    "T-1001": {"name": "Aria Okonkwo", "plan": "enterprise", "open_tickets": 2},
    "T-1002": {"name": "Rune Halvorsen", "plan": "free", "open_tickets": 0},
}


@tool
def search_kb(query: str) -> str:
    """Search the support knowledge base for an article matching the query."""
    for key, article in KB.items():
        if key in query.lower():
            return article
    return "No matching article."


@tool
def lookup_customer(ticket_id: str) -> str:
    """Look up the customer and plan attached to a ticket id."""
    row = CUSTOMERS.get(ticket_id)
    if row is None:
        return f"No customer found for {ticket_id}."
    return f"{row['name']} on the {row['plan']} plan, {row['open_tickets']} other open tickets."


@tool
def escalate(reason: str) -> str:
    """Escalate the ticket to a human engineer, with a reason."""
    return f"Escalated: {reason}"


_attempts: dict[str, int] = {}


@tool
def flaky_lookup(ticket_id: str) -> str:
    """Look up a ticket in a service that fails the first two times. Chapter 21."""
    _attempts[ticket_id] = _attempts.get(ticket_id, 0) + 1
    if _attempts[ticket_id] < 3:
        raise ConnectionError(f"upstream timeout (attempt {_attempts[ticket_id]})")
    return f"{ticket_id} resolved after {_attempts[ticket_id]} attempts"


def reset_flaky() -> None:
    """Reset the failure counter so a chapter's output is reproducible."""
    _attempts.clear()


ALL_TOOLS = [search_kb, lookup_customer, escalate]
