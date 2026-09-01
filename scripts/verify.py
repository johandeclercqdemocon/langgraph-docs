"""Prove your environment works before you start Chapter 1.

    uv run python scripts/verify.py

Checks the Python version, the installed LangGraph version, that a graph can be
built and run, and that persistence works. Prints a clear pass/fail per item.
Needs no API key and makes no network calls.
"""

from __future__ import annotations

import operator
import sys
from pathlib import Path
from typing import Annotated

# Work whether you run `uv run python scripts/verify.py` (project installed) or
# plain `python scripts/verify.py` (it is not), by putting the repo root on the
# path either way.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Imported at module level on purpose: `from __future__ import annotations` makes
# TypedDict resolve its hints against module globals, so a name imported inside a
# function is invisible to it. Chapter 3 hits this exact error for real.
from typing_extensions import TypedDict

TICKS: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    TICKS.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}{'  ' + detail if detail else ''}")


def main() -> int:
    v = sys.version_info
    check(
        "Python >= 3.11",
        v >= (3, 11),
        f"found {v.major}.{v.minor}.{v.micro}",
    )

    try:
        import importlib.metadata as md

        for pkg, floor in (("langgraph", (1, 2)), ("langchain-core", (1, 0))):
            raw = md.version(pkg)
            parts = tuple(int(x) for x in raw.split(".")[:2])
            check(f"{pkg} >= {'.'.join(map(str, floor))}", parts >= floor, f"found {raw}")
    except Exception as exc:  # pragma: no cover - only on a broken install
        check("packages importable", False, str(exc))
        return report()

    # A graph you can read in one breath: one node, one edge.
    try:
        from langgraph.graph import END, START, StateGraph

        class S(TypedDict):
            n: int

        graph = (
            StateGraph(S)
            .add_node("double", lambda s: {"n": s["n"] * 2})
            .add_edge(START, "double")
            .add_edge("double", END)
            .compile()
        )
        check("build and run a graph", graph.invoke({"n": 21})["n"] == 42)
    except Exception as exc:
        check("build and run a graph", False, repr(exc))
        return report()

    # Persistence: the same thread must remember across two separate invokes.
    try:
        from langgraph.checkpoint.memory import InMemorySaver

        class C(TypedDict):
            log: Annotated[list, operator.add]

        g = (
            StateGraph(C)
            .add_node("step", lambda s: {"log": ["x"]})
            .add_edge(START, "step")
            .add_edge("step", END)
            .compile(checkpointer=InMemorySaver())
        )
        cfg = {"configurable": {"thread_id": "verify"}}
        g.invoke({"log": []}, cfg)
        out = g.invoke({"log": []}, cfg)
        check("state persists across runs", out["log"] == ["x", "x"], f"log={out['log']}")
    except Exception as exc:
        check("state persists across runs", False, repr(exc))

    # The book's running example.
    try:
        from examples.triage.graph import build_routed

        out = build_routed().invoke({"ticket_id": "T-1001", "body": "billing refund"})
        check("the triage example runs", out["trail"] == ["classify", "retrieve", "draft"])
    except Exception as exc:
        check("the triage example runs", False, repr(exc))

    return report()


def report() -> int:
    print()
    if all(TICKS):
        print(f"All {len(TICKS)} checks passed. You are ready for Chapter 1.")
        return 0
    failed = TICKS.count(False)
    print(f"{failed} of {len(TICKS)} checks failed. See README.md -> Before you begin.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
