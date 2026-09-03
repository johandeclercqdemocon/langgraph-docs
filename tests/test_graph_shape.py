"""Tests for the static analyser in `scripts/analyze_graph.py`. Appendix D.

Two halves, and the second is the one that matters:

  - the book's own graphs must report no failures, so the analyser stays usable;
  - graphs that are broken on purpose must report the *right* failure, so a
    check that silently stops working gets caught.

The second half exists because the first version of the analyser passed the
`trap` fixture. It was reading `compiled.get_graph()`, which draws an exit to
END that the graph does not have. A check that cannot fail is not a check.
"""

from __future__ import annotations

import operator
import pathlib
import sys
from typing import Annotated

import pytest
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import analyze_graph as ag  # noqa: E402


class S(TypedDict, total=False):
    n: Annotated[int, operator.add]
    items: Annotated[list, operator.add]


def bump(state: S) -> dict:
    return {"n": 1}


def failures(compiled) -> list[str]:
    return [m for severity, m in ag.analyse(compiled) if severity == "fail"]


def notes(compiled) -> list[str]:
    return [m for severity, m in ag.analyse(compiled) if severity == "note"]


# --- the book's graphs ------------------------------------------------------


@pytest.mark.parametrize("target", ag.DEFAULT_TARGETS)
def test_the_books_graphs_are_clean(target: str) -> None:
    assert failures(ag.load(target)) == []


def test_the_agent_loop_is_reported_as_a_cycle() -> None:
    # Not a fault: it is why the chapter uses a graph at all. But it is what
    # makes recursion_limit live, so the analyser must not stay quiet about it.
    found = notes(ag.load("examples.triage.graph:build_agent"))
    assert any(m.startswith("cycle") and "model" in m and "tools" in m for m in found)


def test_the_hitl_review_node_is_not_in_a_cycle() -> None:
    # `review` is annotated Command[Literal["__end__"]]. Widening that to include
    # "draft" would declare an edge the code never takes, and this would fail.
    assert not any(m.startswith("cycle") for m in notes(ag.load("examples.triage.graph:build_hitl")))


# --- graphs that are wrong on purpose ---------------------------------------


def test_router_without_destinations_is_caught() -> None:
    def route(state: S) -> str:  # no path map, no Literal annotation
        return "b"

    graph = (
        StateGraph(S).add_node("a", bump).add_node("b", bump).add_node("c", bump)
        .add_edge(START, "a").add_conditional_edges("a", route)
        .add_edge("b", END).add_edge("c", END).compile()
    )
    found = failures(graph)
    assert any(m.startswith("unresolved") and "'a'" in m for m in found)
    # The destinations are unknowable, so they are also unreachable.
    assert any(m.startswith("orphan") and "'b'" in m for m in found)
    assert any(m.startswith("orphan") and "'c'" in m for m in found)


def test_a_loop_with_no_exit_is_caught_and_really_does_not_terminate() -> None:
    graph = (
        StateGraph(S).add_node("a", bump).add_node("b", bump)
        .add_edge(START, "a").add_edge("a", "b").add_edge("b", "a").compile()
    )
    assert any(m.startswith("trap") for m in failures(graph))

    # The claim in the message, checked rather than asserted. A low limit keeps
    # this fast; the real default is 10007.
    with pytest.raises(GraphRecursionError):
        graph.invoke({"n": 0}, {"recursion_limit": 8})


def test_unreachable_node_is_caught() -> None:
    graph = (
        StateGraph(S).add_node("a", bump).add_node("b", bump).add_node("c", bump)
        .add_edge(START, "a").add_edge("a", "b").add_edge("b", END)
        .add_edge("c", END).compile()
    )
    assert failures(graph) == ["orphan      'c' is unreachable from START"]


def test_send_is_reported_as_dynamic_not_as_a_failure() -> None:
    def fan(state: S) -> list[Send]:
        return [Send("worker", {"n": i}) for i in range(3)]

    def worker(state: S) -> dict:
        return {"items": [1]}

    graph = (
        StateGraph(S).add_node("fan", fan).add_node("worker", worker)
        .add_edge(START, "fan").add_conditional_edges("fan", fan, ["worker"])
        .add_edge("worker", END).compile()
    )
    assert failures(graph) == []
    assert any(m.startswith("dynamic") and "'fan'" in m for m in notes(graph))


# --- why the analyser reads the builder and not the drawing -----------------


def test_get_graph_invents_an_edge_to_end() -> None:
    """The measurement behind `topology()`. If this ever fails, simplify it."""
    graph = (
        StateGraph(S).add_node("a", bump).add_node("b", bump)
        .add_edge(START, "a").add_edge("a", "b").add_edge("b", "a").compile()
    )
    assert ("b", END) not in graph.builder.edges
    drawn = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("b", END) in drawn  # the diagram shows an exit the graph does not have


def test_get_graph_drops_edges_from_unreachable_nodes() -> None:
    graph = (
        StateGraph(S).add_node("a", bump).add_node("c", bump)
        .add_edge(START, "a").add_edge("a", END)
        .add_edge("c", END).compile()
    )
    assert ("c", END) in graph.builder.edges
    drawn = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("c", END) not in drawn
