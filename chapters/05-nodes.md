# Chapter 5 — Nodes

A node is a function. That is the whole idea, and it is worth defending, because the
temptation when learning a framework is to assume there must be more to it.

There is not. `def classify(state): return {"category": "billing"}` is a complete,
production-legitimate node. It has no base class, no decorator, and no framework import.

## The contract

Every node obeys the same two-line contract:

> **In:** the entire current state.
> **Out:** a dict of the fields it changed — or `None` to change nothing.

Returning `None` is legal and useful: a node that only logs, emits a metric, or writes to an
external system has nothing to contribute to state.

```python
def audit(state: TicketState) -> None:
    logger.info("ticket %s classified as %s", state["ticket_id"], state["category"])
```

## The three signatures

Nodes may take one, two, or three parameters. LangGraph inspects the signature and passes
what you asked for.

```python
def plain(state): ...
def with_config(state, config: RunnableConfig): ...
def with_runtime(state, runtime: Runtime[Context]): ...
```

**`state` alone** covers most nodes. Prefer it — it is the easiest to test, because calling
it is just `classify({"body": "..."})` with no framework involved.

**`config: RunnableConfig`** gives you the per-run configuration, most usefully the thread
id:

```python
def with_cfg(state, config: RunnableConfig):
    return {"out": [f"thread={config['configurable'].get('thread_id')}"]}
```

**`runtime: Runtime[Context]`** gives you typed, per-run context that is *not* state —
things like the tenant, the user id, or a database handle. Declare its shape and pass it at
invoke time:

```python
@dataclass
class Ctx:
    tenant: str

def with_rt(state, runtime: Runtime[Ctx]):
    return {"out": [f"tenant={runtime.context.tenant}"]}

graph = StateGraph(State, context_schema=Ctx)...
graph.invoke({"out": []}, {"configurable": {"thread_id": "t7"}}, context=Ctx(tenant="acme"))
```

```
{'out': ['thread=t7', 'tenant=acme']}
```

**Context is not state.** The distinction matters and is easy to get wrong:

| | State | Context |
|---|---|---|
| Written by nodes | yes | no |
| Checkpointed | yes | no |
| Set per run | as input | as `context=` |
| Use for | the work in progress | tenant, user, db handle, feature flags |

A database connection in state will be serialised by the checkpointer and fail. Put it in
context. A running total belongs in state.

## Naming

`add_node("classify", classify)` gives the node a name. That name is what appears in stream
output, in `get_state().next`, in LangSmith traces, and in error messages.

If you omit it, the function's name is used:

```python
.add_node(classify)          # named "classify"
```

Node names must be unique, and they are part of your public interface in a way that is easy
to underestimate: **a checkpoint records node names.** Renaming a node invalidates the
ability to resume threads that were paused inside it. Chapter 26 covers migrating a graph
that has live threads.

## Nodes that call models

Nothing about a node changes when a model is involved. It is still a function that returns
a dict:

```python
def call_model(state: TicketState) -> dict:
    reply = model.invoke(state["messages"])
    return {"messages": [reply], "trail": ["model"]}
```

Two details carry real weight.

**Return `[reply]`, not `reply`.** The `messages` field has the `add_messages` reducer,
which expects a list of messages to merge. Passing a bare message is the single most common
version of the `TypeError` from Chapter 3.

**Build the prompt inside the node, from raw state.** Store the ticket body and the retrieved
article as separate fields; assemble the prompt where you use it. Storing a pre-rendered
prompt string in state means every checkpoint carries a redundant copy, and changing the
prompt no longer changes replayed runs.

## Async nodes

Declare a node `async def` and it is awaited. Run the graph with `ainvoke` or `astream`:

```python
async def retrieve(state: TicketState) -> dict:
    article = await store.search(state["category"])
    return {"evidence": [article]}

result = await graph.ainvoke({"ticket_id": "T-1001", ...})
```

You can mix sync and async nodes in one graph. What you must not do is put a blocking call
inside an `async def` node — as Chapter 4 showed, that stalls the event loop and silently
serialises your parallel branches. If a library is sync-only, either make the node a plain
`def` (LangGraph will run it in a thread pool) or wrap it in `asyncio.to_thread`.

## Nodes that are graphs

`add_node` accepts any compiled graph, not just a function:

```python
.add_node("sub", some_compiled_graph)
```

That is composition, and it has a sharp edge involving shared reducer keys. Chapter 9 is
about it.

## Keeping nodes testable

The best reason to keep nodes as plain functions is that a plain function needs no graph to
test:

```python
def test_classify_detects_billing():
    assert classify({"body": "I want a refund"})["category"] == "billing"
```

No graph, no compile, no checkpointer, no mocking. This is why the book's `classify` is a
keyword rule rather than a model call — and it is worth asking, for each node you write,
whether it needs a model at all. Chapter 24 builds this into a strategy.

Three habits keep that property:

- **One responsibility per node.** A node that retrieves *and* drafts cannot be tested for
  either.
- **Take dependencies from context, not module globals.** A node reaching for a global
  client cannot be tested without one.
- **Return, do not mutate.** Covered in Chapter 2; it is also what makes the assertion above
  a simple equality check.

## Try it

See all three signatures in one graph:

```bash
uv run python -c "
import operator
from dataclasses import dataclass
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime

@dataclass
class Ctx: tenant: str
class S(TypedDict): out: Annotated[list, operator.add]

def a(state): return {'out': ['plain']}
def b(state, config: RunnableConfig): return {'out': [f\"thread={config['configurable'].get('thread_id')}\"]}
def c(state, runtime: Runtime[Ctx]): return {'out': [f'tenant={runtime.context.tenant}']}

g = (StateGraph(S, context_schema=Ctx).add_node('a',a).add_node('b',b).add_node('c',c)
     .add_edge(START,'a').add_edge('a','b').add_edge('b','c').add_edge('c',END).compile())
print(g.invoke({'out': []}, {'configurable':{'thread_id':'t7'}}, context=Ctx(tenant='acme')))
"
```

Then test a node with no graph at all, which is the point of the chapter:

```bash
uv run python -c "
from examples.triage.graph import classify
print(classify({'body': 'I want a refund'}))
print(classify({'body': 'my toaster is sentient'}))
"
```

## Takeaways

- A node is a plain function. No base class, no decorator, no framework import.
- The contract is: receive the whole state, return only what changed — or `None`.
- Three signatures: `state`, `(state, config)`, `(state, runtime)`. Prefer the first.
- **Context is not state.** Context is per-run, not written by nodes, and not checkpointed —
  the right home for tenants, user ids, and database handles.
- Nodes calling models must return `[message]`, not `message`, because of `add_messages`.
- Build prompts inside the node from raw state; do not checkpoint rendered prompts.
- A blocking call inside `async def` serialises the graph. Use plain `def` or `asyncio.to_thread`.
- Node names are recorded in checkpoints, so renaming breaks resumption of live threads.
- Keeping nodes plain functions is what makes them testable without a graph.

---

Previous: [Chapter 4 — The execution model](04-execution-model.md) ·
Next: [Chapter 6 — Edges and routing](06-edges-and-routing.md)
