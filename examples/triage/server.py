"""The graph, exported for the LangGraph API server. Chapter 26.

`langgraph.json` points at `graph` in this module. Note that it is compiled
*without* a checkpointer: the server supplies its own, backed by Postgres. Passing
one here would be overridden at best and confusing at worst.
"""

from .graph import build_routed

graph = build_routed()
