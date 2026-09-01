# Chapter 4 — The execution model

You can write useful graphs knowing only Chapters 2 and 3. You cannot *debug* them without
this one, because almost every confusing LangGraph behaviour — parallel branches that
interleave oddly, a node that seems to see stale data, an update that lands a step late —
follows from one mechanism.

## Supersteps

LangGraph does not walk your graph node by node. It executes in **supersteps**: discrete
rounds in which every node that is ready runs, and only when all of them have finished are
their updates applied to state.

Each superstep is:

```
1. work out which nodes are ready to run
2. run all of them, with the SAME snapshot of state
3. collect every update they returned
4. apply them all through their reducers
5. repeat, until nothing is ready
```

The consequences are worth stating one at a time.

**Nodes in the same superstep cannot see each other's writes.** They all received the state
as it was at the start of the round. Two parallel nodes, one writing `category` and one
reporting what it sees:

```
{'category': 'billing', 'seen': ["reader saw category='unset'"]}
```

The write landed — `category` is `'billing'` in the final state — but `reader` saw
`'unset'`, because it was handed the snapshot taken before the round began. This is the
single most common source of "why is my node seeing stale data".

**Updates apply between supersteps, never during one.** A node's return value does not take
effect the moment it returns.

**The unit of durability is the superstep.** Chapter 11's checkpointer writes once per
superstep, not once per node. That is why resumption granularity is what it is.

This design is borrowed from Google's Pregel, a graph-processing system, which is why the
executor is called `Pregel` in stack traces.

## Watching it happen

A diamond: `a` runs, then `b` and `c` in parallel, then `d`. Every node sleeps 0.3 s and
appends its name.

```python
.add_edge(START, "a")
.add_edge("a", "b")
.add_edge("a", "c")
.add_edge("b", "d")
.add_edge("c", "d")
```

Streaming with `stream_mode="updates"` shows what each node returned:

```
superstep 1: {'a': {'log': ['a']}}
superstep 2: {'b': {'log': ['b']}}
superstep 3: {'c': {'log': ['c']}}
superstep 4: {'d': {'log': ['d']}}

total wall clock: 0.91s  (4 nodes x 0.3s sleep)
```

Read those two facts together, because they contradict each other. Four chunks labelled as
four steps — but four nodes sleeping 0.3 s each took **0.91 s**, not 1.2 s. Two of them
overlapped.

**The labels are misleading.** `updates` mode emits one chunk per *node*, so a superstep
containing two nodes produces two chunks. It tells you nothing about round boundaries. The
timing is the evidence: `b` and `c` ran concurrently, so there were three supersteps, not
four.

`stream_mode="values"`, which emits the state after each round, shows the truth:

```
{'log': []}
{'log': ['a']}
{'log': ['a', 'b', 'c']}
{'log': ['a', 'b', 'c', 'd']}
```

Four snapshots: the input, then one per superstep. `b` and `c` land **together**, in a
single transition. There was never a moment when state contained `['a', 'b']` and not `c`.

> When you need to reason about rounds, use `stream_mode="values"`. `updates` shows you
> nodes, and node count is not step count.

Note also that `b` appears before `c` in the list. That ordering is not the order they
finished — it is a deterministic ordering LangGraph applies when combining a superstep's
updates. Do not rely on it, but do expect it to be stable between runs.

## Channels

Under the surface, each state field is a **channel**: a named slot with an update rule
(its reducer) and a record of whether it was written this step. Nodes do not read state
directly; they read a view assembled from the channels, and their return dicts are writes
to channels.

You rarely touch channels by name, but the vocabulary appears in error messages —
`InvalidUpdateError: At key 'out'` is a channel rejecting two writes in one step — and it
explains a fact that is otherwise arbitrary:

**A node runs when a channel it subscribes to has been written.** `add_edge("a", "b")` is
implemented as "`b` subscribes to `a` having run". This is why a node with two incoming
edges runs *once* when both fire in the same superstep, rather than twice.

## What "ready" means

A node is ready when every incoming edge that could trigger it has fired in the previous
superstep. In the diamond, `d` has edges from both `b` and `c`. Both fire in superstep 2, so
`d` runs once, in superstep 3, seeing both writes.

This is the behaviour you want, and it is also a trap. If `b` and `c` are in different
supersteps — because one has an extra node in front of it — then `d` becomes ready as soon
as the *first* of them fires, and runs with only half the data. Chapter 7 shows the fix,
and Chapter 19 shows how to recognise the symptom.

## Determinism, and its limits

Given the same input, the same graph, and deterministic nodes, a run produces the same
sequence of supersteps and the same final state. That is what makes the outputs in this book
reproducible, and what makes replay in Chapter 12 meaningful.

Three things break it, and it is worth being precise about which:

- **The model.** A real LLM is not deterministic. This is the big one, and it is why this
  book uses a scripted model.
- **Node side effects.** Reading a clock, a database, or a random number.
- **Concurrency *within* a superstep.** Nodes in one round may finish in any order. Their
  updates are combined deterministically, but if two nodes both append to the same list
  their relative order is stable rather than meaningful — do not build logic on it.

Notably *not* on that list: the number and shape of supersteps. Those follow from the graph
structure alone.

## Async, threads, and what runs where

`invoke` runs sync nodes on the current thread. Within a superstep, multiple sync nodes run
in a thread pool; `async def` nodes run as concurrent tasks on the event loop.

The rule that matters in practice:

> **Mixing a blocking call into an async graph serialises it.** A `requests.get()` inside an
> `async def` node blocks the whole event loop, and your parallel branches quietly become
> sequential.

The symptom is exactly the measurement above, inverted: the wall clock equals the sum rather
than the max. Chapter 27 measures a real case.

Use `ainvoke`/`astream` with `async def` nodes throughout, or `invoke` with plain `def`
nodes throughout. Mixing works but is where the surprises live.

## Try it

Measure the superstep boundary yourself. The point is the wall clock, not the chunk count:

```bash
uv run python -c "
import operator, time
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict): log: Annotated[list, operator.add]
def slow(n):
    def f(state):
        time.sleep(0.3); return {'log': [n]}
    return f

g = (StateGraph(S)
     .add_node('a', slow('a')).add_node('b', slow('b'))
     .add_node('c', slow('c')).add_node('d', slow('d'))
     .add_edge(START,'a').add_edge('a','b').add_edge('a','c')
     .add_edge('b','d').add_edge('c','d').add_edge('d',END).compile())

t0 = time.perf_counter()
for chunk in g.stream({'log': []}, stream_mode='values'): print(chunk)
print(f'{time.perf_counter()-t0:.2f}s for 4 nodes x 0.3s')
"
```

Three transitions, about 0.9 s. Now delete the `a -> c` edge and add `b -> c` instead,
making it a straight line. Same four nodes, same sleeps — the wall clock goes to ~1.2 s and
you get one more snapshot. **The graph's shape is its concurrency.**

Then prove nodes in one superstep cannot see each other: have `b` write `category` and `c`
print the `category` it received.

## Takeaways

- Execution proceeds in **supersteps**: every ready node runs against the same state
  snapshot, then all updates are applied together.
- Nodes in the same superstep **cannot see each other's writes**. This causes most
  "stale data" confusion.
- `stream_mode="updates"` emits one chunk per node, so **chunk count is not superstep
  count**. Use `stream_mode="values"` to see real round boundaries.
- Each state field is a **channel** with an update rule; `add_edge` is a subscription. A
  node with two incoming edges firing in one step runs once, seeing both writes.
- A node becomes ready when its triggers fire — so branches of *unequal length* can start a
  downstream node early, with partial data.
- The number and shape of supersteps is determined by graph structure alone. Non-determinism
  comes from the model, node side effects, and intra-superstep ordering.
- A blocking call in an `async def` node serialises the whole graph. The symptom is wall
  clock equal to the sum rather than the max.

---

Previous: [Chapter 3 — State and reducers](03-state-and-reducers.md) ·
Next: [Chapter 5 — Nodes](05-nodes.md)
