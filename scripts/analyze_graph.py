"""Read the shape of a compiled graph and report what it can prove about it.

    python scripts/analyze_graph.py                              # the book's graphs
    python scripts/analyze_graph.py examples.triage.graph:build_agent

A target is `module:attr`. If the attribute is a compiled graph it is used as
is; if it is a builder function it is called with no arguments.

Nothing here runs your graph, calls a model, or costs anything. It reads
`compiled.builder` -- not `get_graph()`, which is built for diagrams and is not
faithful; see `topology()` -- and asks questions that have mechanical answers:

  unresolved   a conditional edge that declares no destinations. LangGraph then
               cannot know where the router goes: the branch targets are absent
               from the compiled topology, a typo in the router routes to
               nothing, and the drawn diagram shows an edge to END that the code
               does not have. A path map or a `Literal[...]` return annotation
               fixes it, and either one is enough.
  orphan       a node passed to `add_node` that no edge can reach from START.
               It will never run.
  trap         a node on a cycle from which END is not reachable. Once entered,
               the loop cannot terminate: it runs until `recursion_limit`, which
               defaults to 10007 supersteps -- not the 25 that gets repeated.
  cycle        a cycle that can still reach END. Not a fault -- it is the reason
               to use LangGraph rather than a chain -- but it is what makes the
               recursion limit live, so it is worth naming.
  dead end     a node with no outgoing edge. Valid: that branch simply stops.
               Reported so you can confirm you meant it.
  dynamic      a node whose source mentions `Send`. Its edges are created at
               runtime, so the static topology below is incomplete by
               construction, and this tool says less about that graph than it
               appears to.

Only the first three are failures. Cycles, dead ends and `Send` are facts about
a design, not defects, and a checker that calls them errors is one you learn to
ignore.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

START, END = "__start__", "__end__"

DEFAULT_TARGETS = [
    "examples.triage.graph:build_linear",
    "examples.triage.graph:build_routed",
    "examples.triage.graph:build_agent",
    "examples.triage.graph:build_hitl",
    "examples.triage.server:graph",
]


# --- loading ----------------------------------------------------------------


def load(target: str):
    """Import `module:attr`, calling it if it is a builder rather than a graph."""
    module_name, _, attr = target.partition(":")
    if not attr:
        raise ValueError(f"target must be module:attr, got {target!r}")
    obj = getattr(importlib.import_module(module_name), attr)
    if hasattr(obj, "get_graph"):
        return obj
    if callable(obj):
        return obj()
    raise TypeError(f"{target} is neither a compiled graph nor a builder")


# --- topology ---------------------------------------------------------------


def topology(compiled) -> tuple[set[str], dict[str, set[str]]]:
    """Nodes and outgoing edges, read from the builder rather than the drawing.

    `compiled.get_graph()` is the tempting source and the wrong one: it is built
    for diagrams, and it is not a faithful rendering of what runs. Measured on
    langgraph 1.2.11, it does both of these:

      - drops edges leaving a node that nothing can reach, so a stranded node
        looks like a dead end when it has an outgoing edge;
      - adds a conditional edge to END from the last node of a terminating-looking
        path even when no such edge was declared. A two-node loop with no exit is
        drawn with an escape to END, then raises GraphRecursionError when run.

    The builder is ground truth. Three things create an edge:

      `builder.edges`       everything `add_edge` declared, START and END included
      `branches[n].ends`    the resolved destinations of a conditional edge
      `nodes[n].ends`       gotos read off a `Command[Literal[...]]` annotation
    """
    out: dict[str, set[str]] = {}
    for source, target in compiled.builder.edges:
        out.setdefault(source, set()).add(target)

    for source, branches in compiled.builder.branches.items():
        for branch in branches.values():
            if branch.ends:
                out.setdefault(source, set()).update(branch.ends.values())

    for name, spec in compiled.builder.nodes.items():
        for target in getattr(spec, "ends", None) or ():
            out.setdefault(name, set()).add(target)

    nodes = set(compiled.builder.nodes) | {START, END}
    nodes.update(out)
    nodes.update(t for targets in out.values() for t in targets)
    return nodes, out


def reachable(out: dict[str, set[str]], source: str) -> set[str]:
    """Every node reachable from `source` by one or more edges.

    `source` is in the result only if it lies on a cycle, which is what makes
    the cycle test below a one-liner.
    """
    seen: set[str] = set()
    stack = list(out.get(source, ()))
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(out.get(node, ()))
    return seen


def components(nodes: set[str], out: dict[str, set[str]]) -> list[list[str]]:
    """Cycles, grouped by mutual reachability.

    This is O(n^3) where Tarjan is O(n+e). A graph you can draw on a slide has
    ten nodes, so the obvious answer is the better one.
    """
    reach = {n: reachable(out, n) for n in nodes}
    groups: list[list[str]] = []
    for node in sorted(n for n in nodes if n in reach[n]):
        for group in groups:
            if node in reach[group[0]] and group[0] in reach[node]:
                group.append(node)
                break
        else:
            groups.append([node])
    return groups


def dynamic_nodes(compiled) -> list[str]:
    """Nodes whose own source mentions `Send`, so their edges are runtime-made.

    Library code is skipped: `ToolNode` is not your dynamic edge.
    """
    hits = []
    for name, spec in compiled.builder.nodes.items():
        func = getattr(getattr(spec, "runnable", None), "func", None)
        if func is None:
            continue
        try:
            source = inspect.getsource(inspect.unwrap(func))
            path = inspect.getsourcefile(func) or ""
        except (TypeError, OSError):
            continue
        if "site-packages" in path:
            continue
        if "Send(" in source:
            hits.append(name)
    return sorted(hits)


# --- checks -----------------------------------------------------------------


def analyse(compiled) -> list[tuple[str, str]]:
    """Return (severity, message) pairs. Severity is 'fail' or 'note'."""
    nodes, out = topology(compiled)
    found: list[tuple[str, str]] = []

    unresolved: set[str] = set()
    for source, branches in compiled.builder.branches.items():
        for name, branch in branches.items():
            if branch.ends is None:
                unresolved.add(source)
                found.append((
                    "fail",
                    f"unresolved  '{source}' branches through {name}() with no declared "
                    f"destinations; give it a path map or a Literal return annotation",
                ))

    # START and END are excluded: they are not nodes anyone added, and an
    # unreachable END is already said better by the trap check below.
    live = reachable(out, START) | {START, END}
    for name in sorted(nodes - live):
        found.append(("fail", f"orphan      '{name}' is unreachable from START"))

    cycles = components(nodes, out)
    for group in cycles:
        members = " -> ".join(group)
        if END in reachable(out, group[0]):
            found.append((
                "note",
                f"cycle       {members} (can still reach END; recursion_limit applies, "
                f"default 10007)",
            ))
        else:
            found.append((
                "fail",
                f"trap        {members} cannot reach END; entering this loop guarantees "
                f"a GraphRecursionError",
            ))

    for name in sorted(n for n in nodes - unresolved if n != END and not out.get(n)):
        found.append(("note", f"dead end    '{name}' has no outgoing edge; that branch stops here"))

    for name in dynamic_nodes(compiled):
        found.append((
            "note",
            f"dynamic     '{name}' uses Send; its edges are made at runtime and are not "
            f"in the topology above",
        ))

    return found


# --- reporting --------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Report what a compiled graph's shape proves.")
    parser.add_argument("targets", nargs="*", default=None, help="module:attr (default: the book's graphs)")
    args = parser.parse_args()

    targets = args.targets or DEFAULT_TARGETS
    failures = 0

    for target in targets:
        try:
            compiled = load(target)
        except Exception as exc:  # a target that will not import is itself the finding
            print(f"\n{target}\n  fail  could not load: {type(exc).__name__}: {exc}")
            failures += 1
            continue

        nodes, out = topology(compiled)
        edges = sum(len(v) for v in out.values())
        print(f"\n{target}")
        print(f"  {len(nodes)} nodes, {edges} edges")

        found = analyse(compiled)
        failures += sum(1 for severity, _ in found if severity == "fail")
        for severity, message in found:
            print(f"  {'FAIL' if severity == 'fail' else '    '}  {message}")
        if not found:
            print("  ok, nothing to report")

    print()
    if failures:
        print(f"{failures} problem(s) found.")
        return 1
    print("No problems found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
