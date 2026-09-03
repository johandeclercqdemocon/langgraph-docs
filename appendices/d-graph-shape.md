# Appendix D — What the graph's shape can tell you

Almost none of graph theory is useful here. Your graph has ten nodes; nobody needs
Dijkstra, max flow, or a planarity test to reason about it. A LangGraph graph is a wiring
diagram, not a data structure you run algorithms over.

But four questions about its shape do have mechanical answers, and each one corresponds to
a bug this book describes in prose. `scripts/analyze_graph.py` asks them:

```bash
python scripts/analyze_graph.py                              # the book's graphs
python scripts/analyze_graph.py examples.triage.graph:build_agent
```

Nothing in it runs your graph or calls a model. It is free, offline, and fast enough to put
in CI.

## The four questions

**Can every node be reached from START?** A node you added and cannot route to will never
run. LangGraph will not tell you: compiling succeeds, invoking succeeds, and the node is
simply absent from the trail. → Ch 6

**Does every conditional edge declare where it goes?** This is the one that matters most.
`add_conditional_edges("classify", route)` with no path map and no `Literal` return
annotation compiles happily, and the destinations do not exist as far as anything else is
concerned. A typo in the router then routes to nothing, and the run *succeeds* having
skipped the node. Either a path map or an annotation fixes it, and either one is enough:

```python
.add_conditional_edges("classify", route, ["retrieve", "escalate"])   # path map
def route(state) -> Literal["retrieve", "escalate"]: ...              # or annotation
```

→ Ch 6, Ch 32

**Is there a cycle, and can it reach END?** A cycle is not a fault — it is the reason to use
LangGraph rather than a chain. But a cycle from which END is unreachable cannot terminate.
It runs until `recursion_limit`, which defaults to **10007** supersteps, not the 25 that
gets repeated everywhere. → Ch 8, Ch 20

**Does any node build its edges at runtime?** A node using `Send` has no static edges to
check, so every answer above is incomplete for that graph. The analyser says so rather than
implying a completeness it does not have. → Ch 7

## The catch: the diagram is not the graph

The obvious way to read a graph's shape is `compiled.get_graph()` — it is what LangGraph
draws diagrams from, it resolves path maps, and it reads `Command[Literal[...]]`
annotations. It is also not a faithful rendering of what runs. Measured on langgraph 1.2.11:

**It invents an exit to END.** Take a loop with no way out:

```python
graph = (
    StateGraph(S).add_node("a", bump).add_node("b", bump)
    .add_edge(START, "a").add_edge("a", "b").add_edge("b", "a").compile()
)
```

Three edges were declared. `get_graph()` reports four, the extra one a conditional
`b → __end__`. The picture shows an escape hatch; running the graph raises
`GraphRecursionError`.

**It drops edges from nodes it cannot reach.** An `add_edge("c", END)` on a stranded `c`
disappears from the drawing, so `c` reads as a dead end when it has an outgoing edge.

Neither is unreasonable for a diagram. Both are fatal for analysis, and the second failure
mode is the more dangerous one, because it errs toward reassurance: the graph that cannot
terminate is drawn as though it can.

So the analyser reads `compiled.builder` instead, where three things create an edge:

| source | what it holds |
|---|---|
| `builder.edges` | every `add_edge`, START and END included |
| `builder.branches[n][name].ends` | resolved destinations of a conditional edge — `None` if undeclared |
| `builder.nodes[n].ends` | gotos read off a `Command[Literal[...]]` annotation |

That third row is worth sitting with. **A `Command` node's return annotation is not
documentation — it is the edge list.** Nothing called `add_edge` for those destinations;
the annotation is the only declaration there is. Widen it beyond what the code does and you
have added edges to your graph.

This book's own `review` node had exactly that problem. It was annotated
`Command[Literal["draft", "__end__"]]` while both of its branches returned `goto=END`, so
`draft → review → draft` was a cycle in the declared graph and not in the running one. The
analyser found it; the annotation is now `Literal["__end__"]`. → Ch 15

## What it will not tell you

Everything about state. The hard bugs in this book — a subgraph double-counting through a
shared reducer, parallel writes colliding, a Pydantic field constraint that node writes
ignore — are properties of the reducers, not the topology. Two graphs with identical shapes
behave differently depending on how their channels combine values. That is an algebra
question (is your reducer associative? commutative? idempotent?), and no amount of edge
inspection reaches it. → Ch 3, Ch 9, Ch 19

Shape analysis is cheap and catches a narrow, real class of faults. Treat it as a linter,
not as a proof.

## Wiring it into CI

The analyser exits non-zero when it finds a failure, so it drops straight in:

```bash
python scripts/analyze_graph.py && python -m pytest -q
```

`tests/test_graph_shape.py` covers the analyser itself, including the two `get_graph()`
discrepancies above. They are asserted rather than described, so if a future version of
LangGraph fixes them, the tests fail and this appendix gets shorter.
