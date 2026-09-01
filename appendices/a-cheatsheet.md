# Appendix A — API cheatsheet

Everything in this book, in one page. Verified against the versions on the cover.

## Building

```python
from typing import Annotated, Literal
from typing_extensions import TypedDict
import operator
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

class State(TypedDict, total=False):
    category: str                                # replace
    messages: Annotated[list, add_messages]      # append, replace by id
    trail: Annotated[list[str], operator.add]    # append

graph = (
    StateGraph(State)
    .add_node("classify", classify)              # name, function
    .add_node("sub", compiled_subgraph)          # a graph is a node
    .add_edge(START, "classify")                 # entry
    .add_conditional_edges("classify", route, ["a", "b"])   # ALWAYS pass the list
    .add_edge("a", END)
    .compile(checkpointer=saver, store=store, cache=cache)
)
```

| Call | Meaning |
|---|---|
| `add_node(name, fn)` | Add work. `fn` may be a function or a compiled graph. |
| `add_node(name, fn, retry_policy=...)` | With retries (Ch 21) |
| `add_node(name, fn, cache_policy=...)` | With caching (Ch 21) |
| `add_edge(a, b)` | Always go `a` → `b`. Two of these = **parallel**. |
| `add_conditional_edges(a, router, [dests])` | Branch. The list is not optional. |
| `compile(...)` | Blueprint → runnable |

## Nodes

```python
def plain(state): return {"field": value}
def with_config(state, config: RunnableConfig): ...
def with_runtime(state, runtime: Runtime[Ctx]): ...
async def async_node(state): ...
```

- Receives the **whole** state; returns **only what changed** (or `None`).
- Never mutate the input. Never `return state`.
- `runtime.context` for tenant/user/handles; `runtime.store` for the Store.

## Routing

```python
def route(state) -> Literal["a", "b"]:
    return "a" if state["confidence"] >= 0.5 else END

# update and route in one return
def node(state) -> Command[Literal["b", "__end__"]]:
    return Command(update={"x": 1}, goto="b")

# dynamic fan-out
def fan(state):
    return [Send("worker", {"item": i}) for i in state["items"]]
```

> `Command(goto=...)` **adds** an edge. Delete the node's `add_edge` or both run.

## Running

```python
graph.invoke(input, config)               # final state
graph.stream(input, stream_mode="values") # per superstep
await graph.ainvoke(input, config)
graph.invoke(None, config)                # resume from checkpoint
graph.invoke(Command(resume=value), config)  # resume from interrupt
```

Config keys:

```python
{
  "configurable": {"thread_id": "t1"},
  "recursion_limit": 25,        # DEFAULT IS 10007 -- always set this on cycles
  "max_concurrency": 5,
  "callbacks": [...],
}
```

Plus `durability="sync" | "async" | "exit"` as a keyword argument.

## Stream modes

| Mode | Yields |
|---|---|
| `"updates"` | `{node: update}` per node — **not** per superstep |
| `"values"` | whole state per superstep |
| `"messages"` | `(token, metadata)` — **includes tool output**, filter it |
| `"custom"` | whatever `get_stream_writer()` wrote |
| `"debug"` | detailed events |

```python
graph.stream(inp, stream_mode=["updates", "custom"])   # -> (mode, chunk)
graph.stream(inp, stream_mode="updates", subgraphs=True)  # -> (namespace, chunk)
```

## Persistence

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
# from langgraph.checkpoint.postgres import PostgresSaver   # production

with SqliteSaver.from_conn_string("db.sqlite") as saver:    # lifetime = the APP
    graph = builder.compile(checkpointer=saver)

config = {"configurable": {"thread_id": "t1"}}
snap = graph.get_state(config)
snap.values         # the state
snap.next           # () = done; non-empty = paused
snap.interrupts     # waiting on a human?
snap.config         # addresses THIS checkpoint

list(graph.get_state_history(config))          # newest first
graph.update_state(config, {"x": 1})           # goes THROUGH the reducers
graph.update_state(config, {...}, as_node="classify")
```

## Store

```python
from langgraph.store.memory import InMemoryStore

runtime.store.put(("prefs", user_id), "tone", {"value": "terse"})
runtime.store.get(("prefs", user_id), "tone")     # .value or None
runtime.store.search(("prefs", user_id), query="...")
runtime.store.delete(("prefs", user_id), "tone")
```

Tenant goes in the **namespace tuple**, derived from **context**.

## Human in the loop

```python
from langgraph.types import interrupt, Command

def review(state):
    decision = interrupt({"draft": state["draft"]})   # put this FIRST
    return {"approved": decision == "approve"}

out = graph.invoke(inp, config)
if "__interrupt__" in out: ...
graph.invoke(Command(resume="approve"), config)

builder.compile(checkpointer=saver, interrupt_before=["risky"])   # static
```

> The node **re-runs from the top** on resume. Keep side effects after `interrupt()`.

## Prebuilt agent

```python
from langchain.agents import create_agent     # NOT langgraph.prebuilt.create_react_agent
agent = create_agent(model, tools=[...], system_prompt="...", checkpointer=saver)

from langgraph.prebuilt import ToolNode
builder.add_node("tools", ToolNode(tools))    # handle_tool_errors=True by default
```

## Functional API

```python
from langgraph.func import entrypoint, task

@task
def step(x): return x.upper()

@entrypoint(checkpointer=saver)
def workflow(x):
    return step(x).result()
```

Completed tasks are not re-executed on resume; code outside a task is.

## Errors and caching

```python
from langgraph.types import RetryPolicy, CachePolicy
from langgraph.cache.memory import InMemoryCache

builder.add_node("n", fn, retry_policy=RetryPolicy(max_attempts=3, retry_on=(ConnectionError,)))
builder.add_node("m", fn, cache_policy=CachePolicy(ttl=60))
builder.compile(cache=InMemoryCache())
```

## Diagnostics

```python
print(graph.get_graph().draw_mermaid())                 # structure
for c in graph.stream(inp, stream_mode="updates"): ...  # which nodes ran
for c in graph.stream(inp, stream_mode="values"): ...   # how state evolved
Counter(k for c in graph.stream(inp, stream_mode="updates") for k in c)   # ran twice?
print(classify({"body": "..."}))                        # a node, alone
list(graph.get_graph().nodes)
```

## Numbers worth remembering

| | |
|---|---|
| Default `recursion_limit` | **10007** (not 25) |
| Overhead per node | ~0.23 ms |
| Overhead per superstep, in-memory checkpoint | ~0.9 ms |
| `compile()` | ~0.5 ms |
| Checkpoint frequency | one per **superstep**, not per node |

## The silent failures

1. A returned key not in the schema → **dropped, no warning** (Ch 2)
2. A router typo with no destination list → **skipped, run succeeds** (Ch 6)
3. A subgraph sharing a reducer key → **double-counts** (Ch 9)
4. Pydantic state → validates input, **not node writes** (Ch 23)

---

Next: [Appendix B — Glossary](b-glossary.md)
