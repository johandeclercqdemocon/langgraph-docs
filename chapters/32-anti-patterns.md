# Chapter 32 — Anti-patterns

A catalogue of things that look reasonable and are not, each with the reason and the fix.
Most were measured earlier in this book.

## Design

### Using LangGraph when a `while` loop would do

**Why it happens:** the framework is interesting, and the requirements that justify it feel
imminent.

**Why it hurts:** a real learning curve and real indirection, for capabilities you are not
using.

**Fix:** adopt it when a requirement demands it — pausing for a human, resuming after a
crash, parallel branches over shared state, explaining a past run. Chapter 1 is not
decoration.

### Reaching for an agent when a router would do

**Why it hurts:** unbounded steps, unbounded cost, and the hardest thing in the book to test.

**Fix:** Chapter 29's list, read top to bottom, stopping at the first match. If request types
are distinct, route. If the steps are known, chain.

### A supervisor of agents as a first design

**Why it hurts:** every hand-off is a model call, context must be passed explicitly, and
debugging spans several loops. The most over-applied pattern in the ecosystem.

**Fix:** a router over specialised chains gets most of the benefit. Escalate to a supervisor
only after a single agent has demonstrably failed.

### Using a model where a rule works

**Why it hurts:** cost, latency, non-determinism, and an untestable node — for a decision a
lookup table makes correctly.

**Fix:** the book's `classify` is a dict. Use a model when the input is genuinely open-ended.

## State

### Mutating state

```python
def bad(state):
    state["log"].append("x")
    return state
```

**Why it hurts:** measured in Chapter 19 — four entries from one node, ten after a second run
on a thread.

**Fix:** return a dict of changes. `return state` is the bug.

### A reducer on a field that should be replaced

**Why it hurts:** grows without bound, and if it reaches a prompt it inflates every call.

**Fix:** only accumulate what you want accumulated. `category` should replace.

### No reducer on a field written in parallel

**Why it hurts:** `InvalidUpdateError` at best, and the temptation to "fix" it by serialising
branches — throwing away the parallelism.

**Fix:** add the reducer.

### Putting unserialisable or secret things in state

**Why it hurts:** connections fail to serialise; secrets get persisted to a database and kept.

**Fix:** context (Chapter 5) for handles and identity; environment for secrets.

### Pre-rendered prompts in state

**Why it hurts:** every checkpoint carries a redundant copy, and changing the prompt no longer
changes replayed runs.

**Fix:** store raw values; build the prompt inside the node.

## Structure

### `Command(goto=...)` with the static edge still attached

**Why it hurts:** both destinations run. Measured in Chapter 6: asked for `c`, got `b` and `c`.

**Fix:** delete the node's `add_edge` when converting it to `Command`.

### `add_conditional_edges` without the destination list

**Why it hurts:** a router typo logs a warning to stderr, skips the node, and the run
**succeeds**. With the list you get a `KeyError`.

**Fix:** always pass it. Annotate the router with `Literal[...]` too.

### A join node with branches of unequal length

**Why it hurts:** it runs twice — once with partial data (Chapter 7). Doubled side effects.

**Fix:** equalise the branches, gate on completeness, or use `Send`.

### Sharing a reducer key with a subgraph

**Why it hurts:** silent double-counting (Chapter 9).

**Fix:** rename the field, or wrap the subgraph in a node.

### A subgraph for something used once

**Why it hurts:** an extra schema, a namespace in every trace, and the trap above — for no
reuse.

**Fix:** keep the graph flat until a component is reused, tested separately, or interrupted
as a unit.

## Operations

### Not setting `recursion_limit`

**Why it hurts:** **the default is 10007**, so a broken loop is roughly ten thousand model
calls from one request.

**Fix:** set it explicitly on every graph with a cycle, and add a step budget in state.

### Shipping `InMemorySaver`

**Why it hurts:** every conversation is lost on deploy, and it does not work across workers.

**Fix:** Postgres in production. SQLite only for a single local process.

### A checkpointer scoped to a request

```python
with SqliteSaver.from_conn_string(...) as cp:   # inside the handler
```

**Why it hurts:** the connection closes at the end of the request, so paused threads cannot
be resumed, and you recompile per request.

**Fix:** application lifespan (Chapter 23).

### Compiling the graph per request

**Why it hurts:** 0.5 ms of pure waste, and it invites the previous mistake.

**Fix:** compile once at startup; a compiled graph is safe to invoke concurrently.

### Renaming nodes with live threads

**Why it hurts:** paused threads resume against today's code and fail. No deploy-time error.

**Fix:** treat node names and the state schema as a public interface — add, alias, drain, or
version (Chapter 26).

### No checkpoint retention policy

**Why it hurts:** checkpoints accumulate per superstep per thread, forever. A cost problem
and a privacy problem.

**Fix:** decide how long completed threads live, and run the job.

### Stacking client retries under node retries

**Why it hurts:** three under three is nine paid calls and nine times the latency.

**Fix:** pick one layer. `max_retries=0` on the client if the node owns it.

### Caching a node with side effects

**Why it hurts:** a cache hit means the node did not run, so the side effect did not happen.

**Fix:** cache only pure, time-independent work.

## Security

### Taking the tenant from tool arguments

**Why it hurts:** the model chooses the arguments, and its input is attacker-controlled.

**Fix:** close tools over the tenant from context (Chapter 28).

### Treating a namespaced `thread_id` as authorisation

**Why it hurts:** the checkpointer loads whatever id it is given. Demonstrated in Chapter 28.

**Fix:** verify ownership at the API boundary.

### Relying on prompts to stop injection

**Why it hurts:** no prompt reliably prevents it.

**Fix:** constrain what tools can do; put a human in front of the irreversible.

### Treating time travel as an audit log

**Why it hurts:** history is editable via `update_state`.

**Fix:** write a separate append-only record if you need evidence.

## Testing

### "You can't test an LLM app"

**Why it hurts:** it excuses testing nothing, when routing, reducers and state transitions are
fully deterministic.

**Fix:** Chapter 24's four layers. The book's suite is 19 tests in 0.48 s with no API key.

### Only end-to-end tests, against a real model

**Why it hurts:** slow, flaky, expensive — so nobody runs them.

**Fix:** a scripted model for the loop; keep evaluation in a separate paid suite.

### Asserting on generated prose

**Why it hurts:** breaks whenever anyone rewords a template.

**Fix:** assert on `trail` — the path, not the words.

## A review checklist

For a pull request touching a graph:

- [ ] Does any node `return state` or mutate its input?
- [ ] Does every field written by parallel branches have a reducer?
- [ ] Does every field that should replace *lack* one?
- [ ] Does every `add_conditional_edges` pass its destination list?
- [ ] Does any `Command(goto=...)` node still have a static outgoing edge?
- [ ] Are all branches into a join node the same length?
- [ ] Does any subgraph share a reducer key with its parent?
- [ ] Is `recursion_limit` set wherever there is a cycle?
- [ ] Are secrets and connections out of state?
- [ ] Is tenant scope taken from context, not from arguments?
- [ ] Do node names and the state schema remain compatible with live threads?
- [ ] Are routers covered by tests at their boundaries?

## Takeaways

- Most anti-patterns here are one of three things: **using more machinery than the problem
  needs**, **mistaking a write for an append**, or **assuming the framework will warn you**.
- It frequently will not. The silent failures — dropped keys, skipped routers, double-counting
  subgraphs, the 10007 default — are the ones that cost real money.
- The review checklist above catches most of them before they ship, and takes about two
  minutes.

---

Previous: [Chapter 31 — The ecosystem](31-ecosystem.md) ·
Back to the [table of contents](../README.md)
