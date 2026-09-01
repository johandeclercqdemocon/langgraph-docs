# Chapter 14 — Durability and resumption

Chapter 1 claimed that a hand-written `while` loop cannot survive a crash on step nine of
twelve. This chapter makes good on the alternative, and then covers the parts that
durability does *not* give you for free — which is where the real work is.

## Crash recovery, measured

A three-step graph with a SQLite checkpointer. `step1` is expensive; `step2` raises. Run it
in one process:

```
CRASHED: process died here
state after: {'log': ['step1 (expensive)']} next: ('step2',)
```

The process failed, but the checkpoint survived. `step1`'s work is recorded, and `next` says
the graph is waiting to run `step2`.

Now start a **completely new process**, point it at the same database and the same thread,
and pass `None` as input:

```python
graph.invoke(None, {"configurable": {"thread_id": "job"}})
```

```
result: {'log': ['step1 (expensive)', 'step2', 'step3']}
state after: {'log': ['step1 (expensive)', 'step2', 'step3']} next: ()
```

The job completed. **`step1` did not run again** — its entry appears once. The new process
picked up at `step2` with the state as it stood.

That is the whole mechanism: `invoke(None, config)` means "no new input, continue from where
this thread stopped". Nothing about the graph is special; the durability came from the
checkpointer.

## What resumption actually guarantees

Precision matters here, because the guarantee is narrower than it first appears.

> **Committed supersteps are not repeated. The interrupted superstep is repeated in full.**

If four nodes were running in parallel and the process died after three finished, none of
their updates were committed — the superstep never completed — and **all four re-run** on
resume.

This is not a flaw; it is the only consistent choice. Committing a partial superstep would
produce a state that no sequence of complete steps could have produced. But it has a hard
consequence:

> **Nodes must be idempotent.** A node may run more than once for a single logical execution.

The framework cannot help with this. If a node charges a card, sends an email, or posts to a
webhook, guard it yourself:

```python
def charge(state):
    key = f"ticket-{state['ticket_id']}-refund"     # stable across retries
    return {"charge_id": payments.charge(amount, idempotency_key=key)}
```

Derive idempotency keys from **state**, not from a clock or a UUID generated inside the
node — those change on every attempt, which defeats the purpose.

Where a side effect genuinely cannot be made idempotent, isolate it in its own node so the
superstep containing it is as small as possible, and consider an explicit "already done"
flag in state that the node checks first.

## When to write

Chapter 11 introduced the `durability` argument; here is the decision.

```python
graph.invoke(state, config, durability="async")
```

| Mode | Write | Use when |
|---|---|---|
| `"sync"` | before continuing | side effects are real and expensive to repeat |
| `"async"` | in the background | checkpoint latency is measurable and steps are cheap to repeat |
| `"exit"` | at the end of the run | the run is short, disposable, and has no `interrupt()` |

`"async"` narrows the window rather than closing it: if the process dies before the
background write lands, you lose that step. That is usually fine for a step that only called
a read-only tool, and not fine for the one that sent the email.

A reasonable rule: **default to `"sync"`, and move a graph to `"async"` only after measuring
that checkpoint writes are actually costing you.** Chapter 27 shows how to measure that.

## Failure is not the only reason to stop

The same machinery covers three situations that look different and are not:

- **A crash.** Covered above.
- **A pause for a human.** `interrupt()` stops the graph mid-run; the state sits in the
  checkpointer until someone responds. That is Chapter 15, and it is why `"exit"` durability
  is incompatible with it — an interrupted run never "exits".
- **A deliberate stop.** `interrupt_before=["risky_node"]` at compile time, or simply not
  calling `invoke` again.

In all three, the recovery is the same call: `invoke(None, config)`.

## Detecting what needs resuming

In production, something must notice that a thread stopped and do something about it.
`next` is the signal:

```python
snapshot = graph.get_state(config)
if snapshot.next:
    # not finished: either paused for a human, or interrupted by a failure
    ...
```

Distinguishing "waiting for a human" from "crashed" is your job, not the framework's, and
the cleanest way is not to infer it: check for pending interrupts explicitly rather than
guessing from node names.

```python
if snapshot.interrupts:
    ...   # waiting on a person
else:
    ...   # stopped for some other reason; safe to retry
```

A sweeper that lists threads with a non-empty `next` and no pending interrupt, older than
some threshold, and re-invokes them, is a genuinely small amount of code and is what turns
durability from a demo into an operational property.

## What durability does not give you

Four honest limits.

**Not exactly-once.** At-least-once, with a smaller window. See idempotency above.

**Not automatic.** Nothing retries for you. A crashed thread sits in the database until
something invokes it again.

**Not free.** A checkpoint write per superstep, holding the whole state. Chapter 27 measures
it; Chapter 28 covers pruning.

**Not immune to your own deploys.** Resuming a thread runs it against **today's code**. If
you renamed a node, changed the state schema, or removed a branch, an old thread may resume
into a graph that no longer matches it. This is the most under-appreciated operational risk
in LangGraph, and Chapter 26 is where it is addressed.

## Try it

Recreate the crash and the recovery in two separate processes. Save this as `crash.py`:

```python
import operator, sys
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

path, phase = sys.argv[1], sys.argv[2]

class S(TypedDict):
    log: Annotated[list, operator.add]

def step1(s): return {"log": ["step1 (expensive)"]}
def step2(s):
    if phase == "crash":
        raise RuntimeError("process died here")
    return {"log": ["step2"]}
def step3(s): return {"log": ["step3"]}

with SqliteSaver.from_conn_string(path) as cp:
    g = (StateGraph(S).add_node("step1", step1).add_node("step2", step2).add_node("step3", step3)
         .add_edge(START, "step1").add_edge("step1", "step2").add_edge("step2", "step3")
         .add_edge("step3", END).compile(checkpointer=cp))
    cfg = {"configurable": {"thread_id": "job"}}
    try:
        # first run passes input; the resume passes None
        print("result:", g.invoke({"log": []} if phase == "crash" else None, cfg))
    except Exception as e:
        print("CRASHED:", e)
    print("state:", g.get_state(cfg).values, "next:", g.get_state(cfg).next)
```

```bash
uv run python crash.py /tmp/job.sqlite crash
```

```bash
uv run python crash.py /tmp/job.sqlite ok
```

The second command is a new process. Confirm `step1 (expensive)` appears exactly **once** in
the final log.

Then make the point about idempotency concrete: add `print("CHARGING")` to `step1`, delete
`/tmp/job.sqlite`, and run both commands again. It prints once. Now move the `raise` into
`step1` itself and watch what a non-idempotent node in the *failing* superstep costs you.

## Takeaways

- `invoke(None, config)` resumes a thread from wherever it stopped, in any process.
- **Committed supersteps never repeat; the interrupted superstep repeats in full** — including
  sibling nodes that had already finished.
- Therefore **nodes must be idempotent**. Derive idempotency keys from state, never from a
  clock or a fresh UUID.
- `durability` trades safety for speed. Default to `"sync"`; use `"async"` only after
  measuring; `"exit"` cannot be used with `interrupt()`.
- Crash, human pause, and deliberate stop are the same mechanism, and all resume the same way.
- A non-empty `next` means unfinished; check `snapshot.interrupts` to tell "waiting for a
  person" from "crashed". A sweeper over those threads is what makes durability operational.
- Durability is at-least-once, not automatic, not free, and **not immune to deploys** —
  resumed threads run against today's code.

---

Previous: [Chapter 13 — Store: memory across threads](13-store.md) ·
Next: [Chapter 15 — Human in the loop](15-human-in-the-loop.md)
