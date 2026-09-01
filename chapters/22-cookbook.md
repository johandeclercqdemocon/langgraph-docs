# Chapter 22 — Cookbook: symptom → cause → fix

Indexed by what you see, not by what is wrong. Every message here was produced by running
code against the versions on the cover.

## Exceptions

### `AttributeError: 'StateGraph' object has no attribute 'invoke'`

You are holding a builder, not a graph. Add `.compile()`. → Ch 2

### `ValueError: Graph must have an entrypoint: add at least one edge from START to another node`

No `add_edge(START, ...)`. → Ch 17

### ``ValueError: Node `a` already present.``

Duplicate `add_node` name — often a loop building nodes with a constant name. → Ch 17

### ``ValueError: Found edge ending at unknown node `ghost` ``

Typo, or `add_edge` referencing a node added later in a conditionally-built graph. → Ch 17

### ``ValueError: Node `__start__` is reserved.``

Use the imported `START` / `END` sentinels. → Ch 17

### `ValueError: no signature found for builtin <built-in function max>`

A C builtin used as a reducer. Wrap it: `def keep_max(a, b): return max(a, b)`. → Ch 3

### `InvalidUpdateError: Expected dict, got ...`

A node returned a non-dict — commonly `model.invoke(...)` instead of
`{"messages": [model.invoke(...)]}`. → Ch 2, 5

### `InvalidUpdateError: At key 'x': Can receive only one value per step.`

Two parallel branches wrote a field with no reducer. Add
`Annotated[list, operator.add]` and have each branch return a list. Do **not** serialise the
branches to avoid it. → Ch 3, 7

### `TypeError: can only concatenate list (not "str") to list`

A node returned `X` where the field wants `[X]` — `{"trail": "draft"}` instead of
`{"trail": ["draft"]}`. The error comes from the reducer, so it does not name the field. → Ch 3

### `GraphRecursionError: Recursion limit of 10007 reached ...`

No `recursion_limit` was passed and a cycle never terminated. **10007 is the LangGraph
default**, not 25. → Ch 8, 20

### `GraphRecursionError: Recursion limit of 25 reached ...`

A limit *was* passed (or inherited from `langchain_core`) and the loop legitimately needs
more — or is broken. Check the message list before raising it. → Ch 20

### `ValueError: Checkpointer requires one or more of the following 'configurable' keys: thread_id, ...`

A checkpointer is compiled in but the invoke had no `thread_id`. → Ch 11

### `EmptyInputError: Received no input for __start__`

`invoke(None, ...)` on a thread with nothing to resume. → Ch 14, 17

### `KeyError: 'somefield'` inside a node

A field was never written, usually because the branch that writes it did not run. Use
`total=False` on the state and `state.get("field", default)`. → Ch 17

### `KeyError: 'retrive'` from a conditional edge

A router returned a name not in the destination list. → Ch 6

## No exception, but wrong

### A node runs but state does not change

1. **A typo in the returned key** — dropped silently, no warning. Check it against the schema
   first, every time.
2. The node returned `None` or `{}`.
3. The node mutated `state` and returned it instead of returning changes.
→ Ch 2, 19

### A node did not run at all, and nothing complained

A router typo with **no destination list** logs to stderr and skips the node; the run
succeeds. Always pass the list to `add_conditional_edges`. → Ch 6

```
Task a ... wrote to unknown channel branch:to:retrive, ignoring it.
RESULT: {'x': 1}
```

### A list contains everything twice

Parent and subgraph share a reducer key. The subgraph gets the parent's accumulated value and
returns the whole thing, which the reducer appends again:

```
{'log': ['before', 'before', 'inner', 'after']}
```

Rename the subgraph's field, or wrap the subgraph in a node. → Ch 9

### A list grows absurdly; values repeat and multiply

A node is mutating state in place and returning it. Measured: four entries from one node, ten
after a second run on the same thread. `return state` is the bug. → Ch 19

### A node ran twice

Two branches of **unequal length** join at it. It fires on the first arrival with partial
data, then again. Equalise the branches, gate on completeness, or use `Send`. → Ch 7

```python
from collections import Counter
Counter(k for c in graph.stream(inp, stream_mode="updates") for k in c)
```

### A node sees an old value another node just wrote

They are in the same superstep and both received the pre-step snapshot. Add an edge to force
ordering — file order is not execution order. → Ch 4, 19

### Both branches ran when I wanted one

Either two static edges from one node (that means parallel, not choice), or a
`Command(goto=...)` with a leftover `add_edge`. → Ch 6

```
{'log': ['a', 'b', 'c']}    # asked for c, got b and c
```

### The graph stops early with no error

Nothing was ready to run. A graph with no path to `END` compiles and runs fine. Draw it. → Ch 17

### Values reset between calls

No checkpointer, or a different `thread_id` each time. → Ch 11

### Memory does not carry to a new conversation

That is the checkpointer working as designed — it is per thread. Cross-thread facts need the
Store. → Ch 13

### The reviewer's side effect happens twice

Code **before** `interrupt()` re-runs on resume. Measured: twice for one review. Put
`interrupt()` first. → Ch 15

### A cached node's side effect stopped happening

A cache hit means the node did not run. Only cache pure, time-independent work. → Ch 21

### The chat UI shows raw tool output

`stream_mode="messages"` includes `ToolMessage`s. Filter on
`metadata["langgraph_node"]`. → Ch 18

### Parallel branches are not actually parallel

A blocking call inside an `async def` node stalls the event loop. Symptom: wall clock equals
the sum, not the max. Use plain `def` or `asyncio.to_thread`. → Ch 4

### The agent calls the same tool forever

The tool's result does not permit stopping. `"No matching article."` invites another attempt.
Return something conclusive. → Ch 20

### The agent ignores a tool, or calls it wrongly

The docstring and signature are what the model sees. Write them as specifications. → Ch 10

### A resumed thread behaves strangely after a deploy

It is running against today's code with yesterday's state. Renamed nodes and changed schemas
break live threads. → Ch 14, 26

## Fast diagnostics

```python
# structure
print(graph.get_graph().draw_mermaid())

# which nodes ran, in order
for c in graph.stream(inp, stream_mode="updates"): print(c)

# how state evolved (real superstep boundaries)
for c in graph.stream(inp, stream_mode="values"): print(c)

# did a node run twice?
from collections import Counter
print(Counter(k for c in graph.stream(inp, stream_mode="updates") for k in c))

# inside subgraphs
for c in graph.stream(inp, stream_mode="updates", subgraphs=True): print(c)

# a node, with no framework at all
print(classify({"body": "I want a refund"}))

# after the fact, with a checkpointer
for h in graph.get_state_history(config): print(h.metadata["step"], h.next, h.values)

# is it paused, and on what?
snap = graph.get_state(config); print(snap.next, snap.interrupts)
```

## Reading a traceback

Read the **bottom two lines**. Everything between `pregel/main.py` and your file is plumbing.

```
File "<stdin>", line 6, in boom            <- your code
ZeroDivisionError: division by zero
During task with name 'boom' and id '...'  <- the node
```

→ Ch 16

---

Previous: [Chapter 21 — Errors, retries and caching](21-errors-retries-caching.md) ·
Next: [Chapter 23 — Structuring a real project](23-project-structure.md)
