"""The test strategy from Chapter 24, applied to the book's running example.

Four layers, cheapest first. Run with:

    uv run --extra dev pytest -q
"""

from __future__ import annotations

import operator
from typing import Annotated

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict

from examples.triage.graph import (
    build_agent,
    build_hitl,
    build_routed,
    classify,
    draft,
    route,
)

# --- Layer 1: nodes, as plain functions. No graph, no model, no I/O. --------


@pytest.mark.parametrize(
    "body,expected",
    [
        ("I want a refund", "billing"),
        ("403 on register", "sip-registration"),
        ("choppy audio", "packet-loss"),
        ("locked out", "password"),
        ("my toaster is sentient", "unknown"),
    ],
)
def test_classify(body: str, expected: str) -> None:
    assert classify({"body": body})["category"] == expected


def test_draft_uses_evidence() -> None:
    out = draft({"ticket_id": "T-1", "evidence": ["Refunds take 5 days."]})
    assert "Refunds take 5 days." in out["draft"]


def test_draft_without_evidence_does_not_crash() -> None:
    # The escalate branch never runs `retrieve`, so `evidence` is absent.
    assert "no supporting article" in draft({"ticket_id": "T-1"})["draft"]


# --- Layer 2: routers. Every branch, with a dict. ---------------------------


def test_route_covers_both_branches() -> None:
    assert route({"confidence": 0.9}) == "retrieve"
    assert route({"confidence": 0.2}) == "escalate"


def test_route_boundary() -> None:
    assert route({"confidence": 0.5}) == "retrieve"


# --- Layer 3: the graph, asserted on `trail`. -------------------------------


def test_confident_ticket_takes_the_retrieve_path() -> None:
    out = build_routed().invoke({"ticket_id": "T-1001", "body": "billing refund"})
    assert out["trail"] == ["classify", "retrieve", "draft"]
    assert out.get("escalated") is None


def test_unknown_ticket_escalates() -> None:
    out = build_routed().invoke({"ticket_id": "T-1002", "body": "my toaster is sentient"})
    assert out["trail"] == ["classify", "escalate"]
    assert out["escalated"] is True


def test_no_node_runs_twice() -> None:
    """Guards against Chapter 7's unequal-branch trap."""
    from collections import Counter

    graph = build_routed()
    seen = Counter(
        node
        for chunk in graph.stream({"ticket_id": "T-1", "body": "billing refund"}, stream_mode="updates")
        for node in chunk
    )
    assert all(count == 1 for count in seen.values()), seen


# --- Layer 4: the model loop, with a scripted model. ------------------------


def test_agent_calls_a_tool_then_answers() -> None:
    script = [
        {"text": "Checking.", "tool_calls": [{"name": "search_kb", "args": {"query": "billing"}}]},
        {"text": "Refunds take five working days."},
    ]
    out = build_agent(script=script).invoke(
        {"ticket_id": "T-1001", "body": "billing", "messages": [HumanMessage("refund?")]}
    )
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]


def test_agent_stops_when_no_tool_is_called() -> None:
    out = build_agent(script=["Answered directly."]).invoke(
        {"ticket_id": "T-1", "body": "x", "messages": [HumanMessage("hi")]}
    )
    assert [type(m).__name__ for m in out["messages"]] == ["HumanMessage", "AIMessage"]


def test_agent_respects_recursion_limit() -> None:
    """A model that always calls a tool must not run away. Chapter 20."""
    from langgraph.errors import GraphRecursionError

    forever = [{"text": "again", "tool_calls": [{"name": "search_kb", "args": {"query": "x"}}]}]
    with pytest.raises(GraphRecursionError):
        build_agent(script=forever).invoke(
            {"ticket_id": "T-1", "body": "x", "messages": [HumanMessage("hi")]},
            {"recursion_limit": 6},
        )


# --- Human in the loop ------------------------------------------------------


def test_interrupt_pauses_then_resumes() -> None:
    graph = build_hitl(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}

    out = graph.invoke({"ticket_id": "T-1001", "body": "billing refund"}, config)
    assert "__interrupt__" in out
    assert graph.get_state(config).next == ("review",)

    final = graph.invoke(Command(resume="approve"), config)
    assert final["trail"][-1] == "approved"
    assert graph.get_state(config).next == ()


def test_reviewer_can_edit_the_draft() -> None:
    graph = build_hitl(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke({"ticket_id": "T-1001", "body": "billing refund"}, config)

    final = graph.invoke(Command(resume="Rewritten by a human."), config)
    assert final["draft"] == "Rewritten by a human."
    assert final["trail"][-1] == "edited"


# --- Persistence ------------------------------------------------------------


def test_threads_are_isolated() -> None:
    # The routed graph has no checkpointer, so use a tiny one here.
    class S(TypedDict):
        log: Annotated[list, operator.add]

    g = (
        StateGraph(S)
        .add_node("step", lambda s: {"log": ["x"]})
        .add_edge(START, "step")
        .add_edge("step", END)
        .compile(checkpointer=InMemorySaver())
    )
    a = {"configurable": {"thread_id": "a"}}
    b = {"configurable": {"thread_id": "b"}}
    g.invoke({"log": []}, a)
    g.invoke({"log": []}, a)
    g.invoke({"log": []}, b)
    assert g.get_state(a).values["log"] == ["x", "x"]
    assert g.get_state(b).values["log"] == ["x"]


# --- The regression test for a silent failure -------------------------------


def test_every_node_writes_only_known_keys() -> None:
    """Chapter 2: an unknown key is dropped silently. Catch it in CI instead."""
    graph = build_routed()
    allowed = set(graph.get_input_jsonschema()["properties"])
    for chunk in graph.stream({"ticket_id": "T-1", "body": "billing refund"}, stream_mode="updates"):
        for node, update in chunk.items():
            unknown = set(update or {}) - allowed
            assert not unknown, f"node {node!r} wrote unknown keys: {unknown}"
