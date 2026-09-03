"""The triage graph, in the four shapes the book builds it in.

Each builder is the end state of a chapter, kept runnable so you can go back to
an earlier one and compare:

    build_linear()  -- Chapter 2. Two nodes, one edge. No branching.
    build_routed()  -- Chapter 6. A conditional edge picks the path.
    build_agent()   -- Chapter 10. A model/tool loop that runs until it stops.
    build_hitl()    -- Chapter 15. The same loop, pausing for a human.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from .fakes import ScriptedModel
from .state import TicketState
from .tools import ALL_TOOLS, KB

# --- plain nodes ------------------------------------------------------------


# Words that imply a category without naming it. A real system would use a model
# here; a lookup table keeps the book's output reproducible and free.
ALIASES = {
    "billing": ("billing", "refund", "invoice", "charged", "payment"),
    "sip-registration": ("sip registration", "register", "403", "realm"),
    "packet-loss": ("packet loss", "packet-loss", "jitter", "choppy", "audio drop"),
    "password": ("password", "reset", "locked out", "sign in"),
}


def classify(state: TicketState) -> dict:
    """Pick a category with a keyword rule. No model needed, and none used."""
    body = state["body"].lower()
    for category, words in ALIASES.items():
        if any(word in body for word in words):
            return {"category": category, "confidence": 0.9, "trail": ["classify"]}
    return {"category": "unknown", "confidence": 0.2, "trail": ["classify"]}


def retrieve(state: TicketState) -> dict:
    article = KB.get(state["category"], "No matching article.")
    return {"evidence": [article], "trail": ["retrieve"]}


def draft(state: TicketState) -> dict:
    evidence = " ".join(state.get("evidence", [])) or "no supporting article"
    return {
        "draft": f"Thanks for reporting {state['ticket_id']}. {evidence}",
        "trail": ["draft"],
    }


def escalate_node(state: TicketState) -> dict:
    return {
        "escalated": True,
        "draft": f"Ticket {state['ticket_id']} escalated to a human ({state['category']}).",
        "trail": ["escalate"],
    }


# --- Chapter 2: linear ------------------------------------------------------


def build_linear():
    return (
        StateGraph(TicketState)
        .add_node("classify", classify)
        .add_node("draft", draft)
        .add_edge(START, "classify")
        .add_edge("classify", "draft")
        .add_edge("draft", END)
        .compile()
    )


# --- Chapter 6: conditional routing -----------------------------------------


def route(state: TicketState) -> Literal["retrieve", "escalate"]:
    """Confident enough to answer, or hand it to a human."""
    return "retrieve" if state["confidence"] >= 0.5 else "escalate"


def build_routed():
    return (
        StateGraph(TicketState)
        .add_node("classify", classify)
        .add_node("retrieve", retrieve)
        .add_node("draft", draft)
        .add_node("escalate", escalate_node)
        .add_edge(START, "classify")
        .add_conditional_edges("classify", route, ["retrieve", "escalate"])
        .add_edge("retrieve", "draft")
        .add_edge("draft", END)
        .add_edge("escalate", END)
        .compile()
    )


# --- Chapter 10: the model/tool loop ----------------------------------------

DEFAULT_SCRIPT = [
    {"text": "Looking that up.", "tool_calls": [{"name": "search_kb", "args": {"query": "billing"}}]},
    {"text": "Refunds take five working days and go back to the original card."},
]


def build_agent(script: list | None = None, checkpointer=None):
    """A hand-written agent loop. Chapter 10 also shows the prebuilt equivalent.

    Swap `ScriptedModel` for a real one to spend money:

        from langchain.chat_models import init_chat_model
        model = init_chat_model("claude-sonnet-5").bind_tools(ALL_TOOLS)
    """
    model = ScriptedModel(script=script or DEFAULT_SCRIPT).bind_tools(ALL_TOOLS)

    def call_model(state: TicketState) -> dict:
        reply = model.invoke(state["messages"])
        return {"messages": [reply], "trail": ["model"]}

    def should_continue(state: TicketState) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    return (
        StateGraph(TicketState)
        .add_node("model", call_model)
        .add_node("tools", ToolNode(ALL_TOOLS))
        .add_edge(START, "model")
        .add_conditional_edges("model", should_continue, ["tools", END])
        .add_edge("tools", "model")
        .compile(checkpointer=checkpointer)
    )


# --- Chapter 15: human in the loop ------------------------------------------


def build_hitl(checkpointer=None):
    """Every draft is shown to a human before it counts as done."""

    # The annotation is the whole destination list. Widening it to include
    # "draft" would declare an edge the code never takes -- and a declared edge
    # is a real edge: it would put this node in a cycle for anything reading the
    # graph's shape. See scripts/analyze_graph.py.
    def review(state: TicketState) -> Command[Literal["__end__"]]:
        decision = interrupt({"draft": state["draft"], "ticket": state["ticket_id"]})
        if decision == "approve":
            return Command(update={"trail": ["approved"]}, goto=END)
        return Command(update={"draft": str(decision), "trail": ["edited"]}, goto=END)

    return (
        StateGraph(TicketState)
        .add_node("classify", classify)
        .add_node("retrieve", retrieve)
        .add_node("draft", draft)
        .add_node("review", review)
        .add_edge(START, "classify")
        .add_edge("classify", "retrieve")
        .add_edge("retrieve", "draft")
        .add_edge("draft", "review")
        .compile(checkpointer=checkpointer)
    )
