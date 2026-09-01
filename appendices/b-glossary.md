# Appendix B — Glossary

Terms as this book uses them, with the chapter that covers each properly.

**`add_messages`** — The reducer for message history. Appends, *and* replaces a message whose
id already exists, which is what makes editing and trimming possible. Use it instead of
`operator.add` for anything holding `BaseMessage`. → Ch 3

**Channel** — The internal representation of a state field: a named slot with an update rule
and a record of whether it was written this step. Appears in error messages
(`At key 'out'`). `add_edge` is implemented as a subscription to one. → Ch 4

**Checkpoint** — A saved copy of state, written once per **superstep**. Not once per node. → Ch 11

**Checkpointer** — The component that writes checkpoints. `InMemorySaver` for tests,
`SqliteSaver` for a single local process, `PostgresSaver` for anything with more than one.
Everything durable depends on it. → Ch 11

**`Command`** — A node return value combining a state update with a routing decision.
`Command(update={...}, goto="node")`. It **adds** a dynamic edge; it does not replace static
ones. → Ch 6

**Compile** — `builder.compile()`, turning a blueprint into something runnable. Costs ~0.5 ms;
do it once at startup, not per request. → Ch 2, 23

**Conditional edge** — An edge whose destination is chosen at runtime by a router function.
Always pass the destination list, or a typo becomes a silent skip. → Ch 6

**Context** — Per-run data that is *not* state: tenant, user id, database handles. Set with
`context=` at invoke time, read via `runtime.context`. **Not checkpointed** — which is why
secrets and connections belong here. → Ch 5

**Durability** — How eagerly checkpoints are written: `"sync"`, `"async"`, or `"exit"`.
`"exit"` is incompatible with `interrupt()`. → Ch 14

**Edge** — A rule for what runs next. Static (`add_edge`) or conditional. Two static edges
from one node means **both run in parallel**, not a choice. → Ch 6

**`END`** — The sentinel marking a graph's exit. A graph with no path to it still compiles
and runs. → Ch 2, 17

**Entrypoint** — In the Functional API, the decorator marking a durable workflow function.
Re-runs from the top on resume. → Ch 30

**Fan-out** — Starting several branches at once, either statically (two edges) or dynamically
(`Send`). Any field the branches write needs a reducer. → Ch 7

**Functional API** — `@entrypoint` and `@task`: durability for ordinary Python control flow,
with no graph, state schema, or reducers. → Ch 30

**Graph** — Nodes plus edges plus a state schema. Built with `StateGraph`, compiled before
use. → Ch 2

**`interrupt()`** — Pauses the graph mid-node and surfaces a payload for a human. The node
**re-runs from its first line** when resumed, so put it early and keep side effects after it.
→ Ch 15

**`InvalidUpdateError`** — Two distinct bugs sharing one exception: a node returned a non-dict,
or parallel branches wrote a field with no reducer. → Ch 3, 17

**Node** — A function taking the whole state and returning only the fields it changed (or
`None`). No base class, no decorator. May also be a compiled graph. → Ch 5

**Pregel** — The execution model LangGraph borrows from, and the module you will see in stack
traces. Skip those frames when reading a traceback. → Ch 4, 16

**Reducer** — A function `(current, update) -> new` deciding what a write to a field *means*.
Without one, a write **replaces**. `Annotated[list, operator.add]` appends. Must have an
introspectable signature — bare builtins like `max` raise. → Ch 3

**`recursion_limit`** — A cap on **supersteps**, not stack depth. **The default is 10007**,
not the widely-repeated 25. Set it explicitly on any graph with a cycle. → Ch 8, 20

**`RetryPolicy`** — Per-node retries with exponential backoff. Narrow it with `retry_on`;
a retried node re-runs entirely. → Ch 21

**Router** — A pure function of state returning a node name or `END`. It routes; it never
updates state. Test it with a plain dict. → Ch 6

**Run** — One `invoke` or `stream` call. A thread may span many runs. → Ch 11

**`Send`** — Dispatches a dynamic number of parallel workers, each receiving **only the
payload** you give it — not graph state. Its writes go through the real reducers. → Ch 7

**`START`** — The sentinel marking a graph's entry. `add_edge(START, "first")`. → Ch 2

**State** — The dict shared by every node; the only way nodes communicate. Everything in it is
serialised and checkpointed. → Ch 2, 3

**`StateSnapshot`** — What `get_state()` returns: `values`, `next`, `config`, `metadata`,
`interrupts`. A non-empty `next` after a completed call means the graph is **paused**. → Ch 11

**Store** — Key-value memory scoped to a namespace you choose, readable from **any** thread —
as opposed to the checkpointer, which is per thread. Put the tenant in the namespace tuple.
→ Ch 13

**Subgraph** — A compiled graph used as a node. Sharing a **reducer** key with the parent
causes silent double-counting. → Ch 9

**Superstep** — One round of execution: every ready node runs against the same state snapshot,
then all updates are applied together. Nodes in the same superstep **cannot see each other's
writes**. The unit of checkpointing. → Ch 4

**`task`** — In the Functional API, a unit of work whose result is checkpointed and therefore
not re-executed on resume. → Ch 30

**Thread** — A conversation or session, identified by `thread_id`. State is checkpointed per
thread, and threads are fully isolated. Namespacing an id is **not** authorisation. → Ch 11, 28

**Time travel** — Reading and resuming from past checkpoints. `update_state` on an old
snapshot forks — but **on the same thread**, so the thread head moves. Editable, therefore
not an audit log. → Ch 12

**`ToolNode`** — A prebuilt node that runs the last message's tool calls, in parallel, and
appends matching `ToolMessage`s. Converts tool exceptions into messages by default. → Ch 10

**`TypedDict`** — The default state schema type. Annotations only — **no runtime validation**.
Pydantic validates *input* but not node writes. → Ch 2, 23

---

Previous: [Appendix A — API cheatsheet](a-cheatsheet.md) ·
Next: [Appendix C — Further reading](c-further-reading.md)
