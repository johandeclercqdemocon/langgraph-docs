# Chapter 26 — Deployment

A compiled graph is a Python object. Deploying it means answering three questions: where
does it run, where does the checkpointer live, and what happens to threads that are mid-flight
when you ship new code.

The third is the one people discover late.

## Two honest options

**Put it in your own application.** The graph is a library. Import it into FastAPI, a worker,
a Lambda, whatever you already run, and wire the checkpointer as in Chapter 23. You keep full
control of routing, auth, and infrastructure, and you write the streaming and thread-management
endpoints yourself.

**Run the LangGraph API server.** A prebuilt server that exposes your graph over HTTP with
threads, streaming, interrupt handling, and a task queue already implemented.

Choose the first if you have an application already and your graph is one feature of it.
Choose the second if the agent *is* the product, or if you would otherwise spend a fortnight
rebuilding thread and interrupt endpoints.

## The API server

Configuration is one file, `langgraph.json`:

```json
{
  "dependencies": ["."],
  "graphs": {
    "triage": "./examples/triage/server.py:graph"
  },
  "env": ".env"
}
```

`graphs` maps a name to `module_path:variable`. The variable must be a **compiled graph** at
import time — this is the one place where the "never compile at import" advice from
Chapter 23 is inverted, so keep that module a thin export:

```python
from .graph import build_routed

graph = build_routed()
```

Note it is compiled **without a checkpointer**. The server provides its own, backed by
Postgres. Passing one here is at best redundant.

Validate before you deploy anything:

```bash
uv run langgraph validate
```

```
Configuration file /.../langgraph.json is valid. (1 graph found)
```

Then run it locally:

```bash
uv run langgraph dev
```

That gives you the HTTP API plus a browser UI for inspecting threads, watching runs, and
resuming interrupts by hand — which is genuinely the fastest way to exercise a
human-in-the-loop graph while building it.

For a container, `langgraph build` produces an image and `langgraph up` runs the stack
including Postgres. `langgraph dockerfile` emits a Dockerfile if you would rather own the
build.

The server is not a black box worth fearing, but it is worth knowing that it brings its own
Postgres schema, task queue, and thread semantics. Read what it stores before putting
regulated data through it.

## Checkpointer choices

| Deployment | Checkpointer |
|---|---|
| Tests, CI | `InMemorySaver` |
| Local development, single process | `SqliteSaver` |
| Anything with more than one process | **`PostgresSaver`** |
| LangGraph API server | provided |

The rule that matters: **the moment you run two workers, SQLite is wrong.** Two processes
writing one SQLite file over a network filesystem is a corruption story, and the symptom —
occasional lost updates under load — is miserable to diagnose. A single-worker deployment
that gets scaled to two by a routine autoscaling change is the usual route in.

Remember `await checkpointer.setup()` at startup to create the tables.

## The deploy problem nobody mentions

This is the important part of the chapter.

A thread paused for human review on Monday is resumed on Wednesday — **against Wednesday's
code**. The checkpoint holds state and node names; it does not hold the graph. So:

**Renaming a node breaks paused threads.** The checkpoint says the next node is `review`; if
you renamed it to `human_review`, resumption fails.

**Removing a node breaks paused threads** in the same way.

**Changing the state schema breaks threads mid-flight.** Old checkpoints have the old shape.
A newly-required field will be missing; a field whose reducer changed will merge differently.

**Changing routing logic silently changes outcomes.** A thread that would have escalated now
retrieves. No error — just a different answer than the one the run started towards.

None of this is hypothetical, and none of it is reported as a deploy failure. It shows up as
a handful of stuck or strange threads a day later.

### Working with it

**Treat node names and the state schema as a public interface.** Because for live threads,
they are.

**Add fields; do not remove or rename them.** New fields should be optional with a default,
so old checkpoints remain valid. Deprecate rather than delete.

**Drain before breaking changes.** Before a structural change, check for threads with a
non-empty `next`:

```python
# threads still in flight
[t for t in list_threads() if graph.get_state(t).next]
```

Wait for them, or resolve them deliberately.

**Keep the old node name as an alias** when you must rename. A node that exists and
immediately routes onward costs nothing and keeps paused threads resumable.

**Version the graph** when a change is genuinely incompatible: run `triage-v2` alongside
`triage-v1`, send new threads to v2, and let v1 drain. This is more work and it is the only
approach that is actually safe for a big change.

## An operational checklist

- [ ] Postgres checkpointer, with `setup()` called at startup.
- [ ] The graph compiled **once** at startup, not per request.
- [ ] `recursion_limit` set at every invoke site (Chapter 20).
- [ ] Secrets in environment or context — never in state.
- [ ] A sweeper for threads with a non-empty `next` and no pending interrupt (Chapter 14).
- [ ] A monitor for interrupt age (Chapter 25).
- [ ] Checkpoint retention policy (Chapter 28).
- [ ] Node names and state schema changes reviewed for live-thread compatibility.

## Try it

Validate a real configuration:

```bash
uv run langgraph validate
```

Then run the development server and open the UI it prints:

```bash
uv run langgraph dev
```

Create a thread, run the triage graph, and inspect the state — it is the same
`StateSnapshot` from Chapter 11, rendered.

Finally, simulate the deploy hazard, which is the exercise worth doing. Pause a thread with
`build_hitl`, then rename the `review` node in
[`examples/triage/graph.py`](../examples/triage/graph.py), and try to resume the thread you
already paused.

## Takeaways

- Either embed the graph in your own application, or run the LangGraph API server. Pick the
  server when the agent is the product.
- `langgraph.json` maps a name to `module:variable`, and that variable must be a **compiled
  graph at import time** — the one exception to Chapter 23's rule.
- Compile the served graph **without** a checkpointer; the server brings its own.
- `langgraph validate`, then `dev`, then `build`/`up`. The dev UI is the fastest way to
  exercise interrupts.
- **Two processes means Postgres.** SQLite under multiple workers corrupts, and the symptom
  is intermittent lost updates.
- **Resumed threads run against today's code.** Renaming or removing a node, or changing the
  state schema, breaks threads that are already paused — with no deploy-time error.
- Treat node names and the state schema as a public interface: add fields, never remove;
  alias renamed nodes; drain in-flight threads before structural changes; version the graph
  for genuinely incompatible ones.

---

Previous: [Chapter 25 — Observability](25-observability.md) ·
Next: [Chapter 27 — Performance and cost](27-performance-and-cost.md)
