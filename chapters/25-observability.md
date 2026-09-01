# Chapter 25 — Observability

Chapter 18 covered streaming, which shows you *this* run in *your* process. This chapter is
about the other question: what happened on a run you were not watching, days ago, for a user
you cannot ask.

Ordinary application logging is not sufficient here, for a specific reason. The interesting
unit is not a line of text; it is a **tree** — a run, containing supersteps, containing
nodes, containing model calls with prompts, tool calls, token counts and latencies. Flatten
that into log lines and the structure that makes it diagnosable is exactly what you lose.

## Tracing with LangSmith

LangGraph is instrumented for LangSmith out of the box. Three environment variables and
runs start appearing:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=triage-prod
```

No code change. Note the names — these were renamed from the older `LANGCHAIN_*` variables,
and the old ones no longer work. That is a small instance of the staleness problem in
Chapter 31.

What you get per run: the node tree, every model call with its full prompt and response,
tool inputs and outputs, token counts, per-step latency, and the error with its node if one
occurred. That is a superset of what you can practically log yourself, and it is the
difference between "the agent gave a bad answer" and "the retrieval step returned the wrong
article, here is the prompt it built."

Tracing is not free — it is a hosted service with a cost, and prompts and responses leave
your infrastructure. For regulated data, check the self-hosted option before enabling it.
Sampling is the usual compromise: trace everything in staging, a percentage in production,
and always trace runs that error.

## If you are not using LangSmith

The framework does not require it. OpenTelemetry via the standard callback interface works,
and the tree structure maps onto spans reasonably well. You will do more work and get less
LLM-specific detail — prompt and response capture in particular is something you have to
build deliberately.

The pragmatic minimum, if you adopt nothing:

- **Log the `thread_id` on every line.** Without it you cannot reconstruct a run at all.
  This is the single highest-value logging decision.
- **Log node entry and exit with duration.**
- **Log token usage per model call.**
- **Log the full message list on error**, not just the exception.

## What to record in state

Some observability belongs *in* the state, because it is then checkpointed, queryable, and
available to your own code:

```python
class TicketState(TypedDict, total=False):
    trail: Annotated[list[str], operator.add]   # which nodes ran
    steps: Annotated[int, operator.add]         # how many model turns
    tokens: Annotated[int, operator.add]        # cost
```

This is cheap and disproportionately useful. "Which threads escalated?", "what is the
p99 step count?", and "which tickets cost more than a dollar?" become queries over your
checkpoint store rather than investigations. And `trail` doubles as the test assertion from
Chapter 24.

The trade-off is that everything here is stored in every checkpoint, so keep it small —
counters and short strings, not full prompts.

## What to alert on

Four signals cover most real incidents.

**`GraphRecursionError` count.** Should be zero. Any occurrence already cost money
(Chapter 20).

**p99 steps per run.** Runaway loops hide in the tail; the mean will not move.

**Interrupt age.** Threads paused for a human that nobody has answered. This is a queue, and
queues need monitoring — a review request nobody sees is an invisible failure.

```python
snap = graph.get_state(config)
if snap.interrupts and age(snap) > timedelta(days=1):
    escalate()
```

**Token spend per run, and in total.** The metric that maps to the invoice.

Deliberately *not* on that list: node latency on its own. It is dominated by model calls and
tells you little you did not already know.

## Evaluation is separate

Tracing tells you what happened. It does not tell you whether the answer was any good, and
conflating the two is a common mistake.

Answer quality needs a dataset of inputs with expected outcomes, a scoring method, and a run
over the set — not an assertion in CI. The practical route is to collect real traces, promote
the interesting ones into a dataset, and score changes against it before shipping. Chapter 24
argued for keeping that out of your unit suite; this is where it belongs instead.

## Debugging a production run

The sequence that works, given a `thread_id`:

1. **Read the trace.** Which node produced the wrong thing?
2. **Read the state history** (Chapter 12) — the first step where state was wrong.
3. **Reproduce locally.** Copy the messages into a `ScriptedModel` and replay.
4. **Fork the thread** at the step before the failure, apply a fix, run forward.

Step 3 is where most of the value is, and it depends on having captured the prompts. That is
the concrete argument for tracing: without it, step 3 is guesswork.

## Try it

Turn on local tracing without a service — the callback interface is what LangSmith uses:

```bash
uv run python -c "
from langchain_core.tracers import ConsoleCallbackHandler
from examples.triage.graph import build_routed
build_routed().invoke({'ticket_id':'T-1','body':'billing refund'},
                      {'callbacks':[ConsoleCallbackHandler()]})
" 2>&1 | head -20
```

Then look at what the book's own state already records for free:

```bash
uv run python -c "
from examples.triage.graph import build_routed
out = build_routed().invoke({'ticket_id':'T-1','body':'billing refund'})
print('trail:', out['trail'])
"
```

## Takeaways

- The unit of observability is a **tree**, not a log line. Flattening it loses what makes a
  run diagnosable.
- LangSmith needs three env vars and no code change. The variables are `LANGSMITH_*`; the
  older `LANGCHAIN_*` names no longer work.
- Tracing costs money and sends prompts off your infrastructure. Sample in production, and
  always trace errors.
- Without it, the minimum is: **`thread_id` on every log line**, node timings, token usage,
  and the full message list on error.
- Record `trail`, `steps` and `tokens` **in state** — cheap, checkpointed, queryable, and
  reusable as test assertions.
- Alert on `GraphRecursionError` count, p99 steps, **interrupt age**, and token spend. Not
  on node latency.
- Tracing is not evaluation. Answer quality needs a dataset and a score, run separately from
  CI.
- To debug production: trace → state history → replay with a scripted model → fork and fix.

---

Previous: [Chapter 24 — Testing graphs](24-testing.md) ·
Next: [Chapter 26 — Deployment](26-deployment.md)
