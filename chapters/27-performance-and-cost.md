# Chapter 27 — Performance and cost

Chapter 1 claimed that LangGraph's own overhead is negligible against LLM latency. This
chapter measures it, and then spends the rest of its length on the things that actually cost
you money — none of which are the framework.

## The framework's overhead, measured

Nodes that do nothing but increment a counter, median of 200 runs:

```
 1 node,  no checkpointer : 0.698 ms
10 nodes, no checkpointer : 2.768 ms
10 nodes, InMemorySaver   : 11.591 ms

compile() cost            : 0.502 ms
```

Three numbers to take away:

**About 0.23 ms per node.** Nine extra nodes cost 2.07 ms.

**About 0.9 ms per superstep with an in-memory checkpointer.** Checkpointing was 8.8 ms
across 10 supersteps — an order of magnitude more than the execution itself. With Postgres it
will be more, since it is a network write.

**`compile()` costs 0.5 ms**, which is why Chapter 23 says compile once at startup rather
than per request. It is not catastrophic; it is simply free to avoid.

Set against a model call at 500–2000 ms, the executor is noise. **If your agent is slow, the
framework is not why** — and this is worth knowing because "the framework is slow" is a
tempting and wrong first theory.

The one framework-shaped cost worth watching is checkpointing, and it has a dial:
`durability="async"` (Chapter 14).

## Where the time actually goes

In order:

**Sequential model calls.** An agent making five tool calls in sequence is five round trips.
This dominates everything.

**Serialised parallelism.** Chapter 4's trap: a blocking call inside an `async def` node
stalls the event loop and your parallel branches become sequential. The signature is wall
clock equal to the *sum* rather than the *max*. Chapter 7 measured the healthy case — six
0.2 s workers finishing in 0.21 s.

**Oversized prompts.** Latency scales with input length. A conversation that has accumulated
fifty messages is slow as well as expensive.

**Checkpoint writes**, if your state is large.

The fix for the first is structural: if two tool calls do not depend on each other, fan out
with `Send` instead of letting the model make them in sequence. That converts *n* round trips
into one superstep — the single largest latency win available in most agent applications.

## Where the money goes

**Message history is the big one.** Every model call sends the whole conversation. Turn 50
pays for turns 1–49 again, so cost grows quadratically with thread length. Nothing else in a
typical agent comes close.

Three remedies:

- **Trim.** Keep the system prompt, the first exchange, and the last *n* turns.
  `add_messages` can remove messages by id, which is what makes this possible in place.
- **Summarise.** Replace old turns with a summary. Cheaper long-term, and lossy — the loss is
  usually acceptable, but it is a real trade rather than a free win.
- **Do not accumulate at all.** Many "agents" are one-shot classifiers dressed as
  conversations. If a thread does not need history, do not keep it.

**Reducers on fields that should replace.** Chapter 3's warning in its costly form: a field
that should hold the current category instead holds all of them, and it goes into the prompt.

**Runaway loops.** Chapter 20. The default limit of 10007 makes this the highest-variance
cost in the book.

**Uncapped fan-out.** `Send` over a list that is occasionally enormous.

**Retries stacked on retries.** Chapter 21: three client retries under three node attempts is
nine paid calls.

## Measuring cost properly

Put it in state, so it is checkpointed and queryable:

```python
def call_model(state):
    reply = model.invoke(state["messages"])
    usage = reply.usage_metadata or {}
    return {"messages": [reply], "tokens": usage.get("total_tokens", 0)}
```

With `tokens: Annotated[int, operator.add]`, every thread carries its own running total,
which makes "what did this conversation cost" a lookup rather than a reconstruction. It also
gives a router something to enforce a budget against.

`usage_metadata` is populated by real model integrations. The book's `ScriptedModel` returns
fixed counts (100 in, 20 out) so that this arithmetic is reproducible offline.

## Cheap wins

**Use a smaller model for the easy nodes.** Classification and routing rarely need your
largest model, and they are often the most-called nodes. Two models in one graph is normal.

**Do not use a model at all where a rule works.** The book's `classify` is a lookup table. It
is free, instant, deterministic, and testable — and for a large fraction of real routing
decisions that is sufficient. Reach for a model when the input is genuinely open-ended.

**Cache deterministic steps.** Chapter 21 measured 0.304 s → 0.002 s. Only for pure,
time-independent work.

**Fan out instead of looping.** As above: *n* round trips become one.

**Prompt caching**, where your provider supports it. A long stable system prompt across many
calls is the case it is designed for.

## A worked comparison

A triage agent handling 10,000 tickets a month, three model turns each, at roughly
$3/million input tokens:

| Approach | Input tokens/ticket | Monthly |
|---|---|---|
| Full history, no trimming, 3 turns | ~12,000 | ~$360 |
| Trimmed to last 4 messages | ~4,000 | ~$120 |
| Rule-based classify, model only for drafting | ~1,500 | ~$45 |

The token counts are illustrative rather than measured — your prompts are not these prompts.
The *ratios* are the point, and they hold: the two largest levers are **how much history you
send** and **how many steps use a model at all**. Neither is a framework feature. Both are
design decisions available to you on day one.

## Try it

Measure the overhead on your own machine, so you have your own number rather than this
book's:

```bash
uv run python -c "
import time, operator, statistics
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

class S(TypedDict): n: Annotated[int, operator.add]
def noop(s): return {'n': 1}

def build(n, cp=None):
    b = StateGraph(S)
    for i in range(n): b = b.add_node(f'n{i}', noop)
    b = b.add_edge(START, 'n0')
    for i in range(n-1): b = b.add_edge(f'n{i}', f'n{i+1}')
    return b.add_edge(f'n{n-1}', END).compile(checkpointer=cp)

def bench(g, cfg=None, reps=200):
    ts = []
    for _ in range(reps):
        t = time.perf_counter(); g.invoke({'n':0}, cfg) if cfg else g.invoke({'n':0})
        ts.append((time.perf_counter()-t)*1000)
    return statistics.median(ts)

print(f\"  1 node : {bench(build(1)):.3f} ms\")
print(f\" 10 nodes: {bench(build(10)):.3f} ms\")
print(f\" 10 + ckpt: {bench(build(10, InMemorySaver()), {'configurable':{'thread_id':'x'}}):.3f} ms\")
"
```

Then confirm the checkpointer is the expensive part, and that `durability='async'` moves it.

## Takeaways

- Measured overhead: **~0.23 ms per node**, **~0.9 ms per superstep** with an in-memory
  checkpointer, **0.5 ms** to compile. Against a 500 ms model call this is noise.
- **If your agent is slow, the framework is not why.** Look at sequential model calls first.
- Checkpointing costs about ten times more than execution. `durability="async"` is the dial.
- Latency: sequential model calls, then accidentally-serialised parallelism (blocking call in
  an `async def` node), then oversized prompts.
- **Cost is dominated by message history**, which grows quadratically per thread. Trim,
  summarise, or do not accumulate.
- Then: reducers that should have been replacements, runaway loops, uncapped fan-out, and
  stacked retries.
- Track `tokens` in state so cost is queryable per thread and enforceable by a router.
- The biggest wins are design, not tuning: a smaller model for easy nodes, **no model at all
  where a rule works**, caching pure steps, and fanning out instead of looping.

---

Previous: [Chapter 26 — Deployment](26-deployment.md) ·
Next: [Chapter 28 — Security and multi-tenancy](28-security-and-multi-tenancy.md)
