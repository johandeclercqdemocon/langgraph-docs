# Chapter 17 — When the graph won't build or run

Layer 1 of Chapter 16's list: the graph does not have the shape you think it has. These
failures are the friendliest kind, because most are caught at `compile()` — before a model
is called and before any money is spent.

This chapter is a catalogue. Every message here is copied from a real run against the
versions on the cover.

## Caught at build time

**Duplicate node name**

```
ValueError: Node `a` already present.
```

Usually a copy-paste, or a loop adding nodes with a name that does not vary.

**Edge to a node that does not exist**

```
ValueError: Found edge ending at unknown node `ghost`
```

Either a typo, or the `add_node` call comes *after* the `add_edge` that references it in a
conditionally-built graph. Order matters when you build with `if` statements.

**Reserved node name**

```
ValueError: Node `__start__` is reserved.
```

`__start__` and `__end__` belong to the framework. Import `START` and `END` and use those.

**No entry point**

```
ValueError: Graph must have an entrypoint: add at least one edge from START to another node
```

Nodes exist but nothing connects `START` to them.

## Not caught at build time

This section matters more, because these compile cleanly and fail — or silently misbehave —
later.

**A node with no path to `END`.** This compiles *and runs*:

```python
StateGraph(S).add_node("a", ...).add_edge(START, "a").compile().invoke({"x": 0})
```

```
-> OK: {'x': 1}
```

No error. LangGraph does not require a path to `END`; a graph simply stops when nothing more
is ready. That is deliberate — it is what makes `Command`-driven graphs work — but it means
"my graph ends early" will never be reported as a structural error. Draw the graph.

**A router returning an unknown node.** Chapter 6 measured both forms: with a destination
list you get `KeyError: 'retrive'`; without one you get a stderr warning and a successful run
that skipped the node. Always pass the list.

**A node returning an unknown key.** Chapter 2: dropped silently. This is the single most
common cause of "my node does nothing".

## Caught at run time

**No input**

```
EmptyInputError: Received no input for __start__
```

You called `invoke(None, ...)` on a graph that has nothing to resume. `None` means "continue
from the checkpoint" (Chapter 14) — legitimate only when a checkpoint exists.

**A state key that is not there**

```
KeyError: 'missing'
```

A plain Python `KeyError` from inside your node. Note it is *your* error, not LangGraph's —
the bottom of the trace names the node.

The usual cause is a field never written because an earlier branch did not run. This is why
`TicketState` uses `total=False` and nodes use `state.get("evidence", [])` rather than
`state["evidence"]`: on a branch where `retrieve` was skipped, the key genuinely does not
exist.

**A dict where a node was expected**

```
InvalidUpdateError: Expected dict, got oops
```

The node returned a string, a list, or a model object rather than a dict of updates. A
common version: returning `model.invoke(...)` directly rather than
`{"messages": [model.invoke(...)]}`.

**Two writers, one key, one step**

```
InvalidUpdateError: At key 'out': Can receive only one value per step.
Use an Annotated key to handle multiple values.
```

Chapters 3 and 7. Parallel branches writing a field with no reducer. The fix is a reducer,
not serialising the branches.

**Recursion limit**

```
GraphRecursionError: Recursion limit of 10007 reached without hitting a stop condition.
```

Chapter 8 — and note the number. If you see `25` here, something in your stack passed a
config; if you see `10007`, you passed none and the loop ran ten thousand times.

**Missing thread id**

```
ValueError: Checkpointer requires one or more of the following 'configurable' keys:
thread_id, checkpoint_ns, checkpoint_id
```

A checkpointer is compiled in but the invoke had no `thread_id`.

## Reading the diagram

`draw_mermaid()` is the layer-1 tool, and there are four specific things to look for:

- **Edges you did not intend.** The classic is a solid line out of a node that also returns
  `Command(goto=...)` — both fire.
- **Missing dotted lines.** A conditional edge without its destination list draws nothing.
  If a branch is missing from the diagram, that is why.
- **Orphans.** A node with no inbound edge never runs and produces no error.
- **Missing `__end__`.** If nothing reaches it, the graph stops wherever it runs out.

```python
print(graph.get_graph().draw_mermaid())
```

For a graph built conditionally, print it in the environment where it misbehaves. A graph
assembled by `if` statements over feature flags is frequently not the graph you have in your
editor.

## A checklist

When a graph will not build or run, in order:

1. Read the **bottom two lines** of the traceback — your file, then the node name.
2. If it is a `ValueError` naming a node, it is one of the build-time errors above.
3. If it is `InvalidUpdateError`, decide which kind: wrong return type, or concurrent write.
4. If there is **no error but nothing happened**, check the three silent failures from
   Chapter 16.
5. Draw the graph.
6. Stub the suspect node to a constant and see whether the failure moves.

## Try it

Collect the messages in one go, so they are familiar rather than alarming:

```bash
uv run python -c "
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
class S(TypedDict): x: int
def show(label, fn):
    try: print(f'{label:34} -> OK: {fn()}')
    except Exception as e: print(f'{label:34} -> {type(e).__name__}: {str(e).splitlines()[0][:60]}')

show('duplicate node', lambda: StateGraph(S).add_node('a',lambda s:{}).add_node('a',lambda s:{}))
show('edge to unknown node', lambda: StateGraph(S).add_node('a',lambda s:{}).add_edge(START,'a').add_edge('a','ghost').compile())
show('reserved name', lambda: StateGraph(S).add_node('__start__', lambda s:{}))
show('no path to END', lambda: StateGraph(S).add_node('a',lambda s:{'x':1}).add_edge(START,'a').compile().invoke({'x':0}))
show('missing state key', lambda: StateGraph(S).add_node('a',lambda s:{'x':s['nope']}).add_edge(START,'a').add_edge('a',END).compile().invoke({'x':0}))
show('no input', lambda: StateGraph(S).add_node('a',lambda s:{'x':1}).add_edge(START,'a').add_edge('a',END).compile().invoke(None))
"
```

Note which line says `OK`. The "no path to END" case is the one that will cost you an
afternoon precisely because it does not complain.

## Takeaways

- Build-time `ValueError`s — duplicate node, unknown edge target, reserved name, no entry
  point — are the friendly ones. Read the message; it names the node.
- **A node with no path to `END` compiles and runs without complaint.** Graphs simply stop
  when nothing is ready. Only the diagram will tell you.
- `EmptyInputError` means `invoke(None, ...)` with no checkpoint to resume.
- A `KeyError` inside a node usually means a field was never written because a branch did not
  run. Use `total=False` and `state.get(...)` for optional fields.
- `InvalidUpdateError` is two different bugs: a non-dict return, or concurrent writes to a
  key with no reducer.
- A `GraphRecursionError` mentioning **10007** means no `recursion_limit` was passed.
- In `draw_mermaid()`, look for unintended edges, missing dotted branches, orphan nodes, and
  a missing `__end__` — and draw it in the environment where it actually misbehaves.

---

Previous: [Chapter 16 — The debugging mindset](16-debugging-mindset.md) ·
Next: [Chapter 18 — Streaming and observing](18-streaming.md)
