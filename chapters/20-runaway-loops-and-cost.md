# Chapter 20 — Runaway loops and cost

Every other failure in this book costs you time. This one costs money, and it does so
quietly, at machine speed, usually overnight.

## The default that is not a safety net

Chapter 8 established it and it belongs here too, because this is the chapter people find
when the invoice arrives:

```
GraphRecursionError: Recursion limit of 10007 reached without hitting a stop condition.
```

**10007 supersteps**, not the 25 that folklore promises. For a graph of pure functions that
is a wasted second. For an agent loop with a model call each time round, it is on the order
of ten thousand API calls from a single request.

The 25 is real, but it belongs to `langchain_core` and does not apply when you invoke a
LangGraph graph without a config. Check yours:

```bash
uv run python -c "from langgraph._internal._config import DEFAULT_RECURSION_LIMIT as D; print(D)"
```

> **Every graph containing a cycle should pass an explicit `recursion_limit`.** Treat an
> unset limit as a bug that a reviewer should catch.

## Three layers of defence

One limit is not enough, because each layer catches a different failure.

**1. A hard cap per run.** `recursion_limit` in the config, set to about twice your expected
worst case. This bounds a single request.

```python
graph.invoke(state, {"recursion_limit": 25})
```

**2. A graceful budget in state.** The limit raises and discards the run; a counter lets the
graph stop cleanly and keep its work:

```python
class State(TypedDict):
    steps: Annotated[int, operator.add]

def should_continue(state):
    if state["steps"] >= 8:
        return "give_up"
    return "tools" if state["messages"][-1].tool_calls else END
```

Prefer this as the primary control. The recursion limit is the crash barrier behind it.

**3. A spend cap outside the graph.** Neither of the above knows about money. If a single
step can call an expensive model, track token usage in state and stop on cost, not just on
count:

```python
def call_model(state):
    reply = model.invoke(state["messages"])
    usage = reply.usage_metadata or {}
    return {"messages": [reply], "tokens": usage.get("total_tokens", 0)}
```

With `tokens: Annotated[int, operator.add]`, a router can refuse to continue past a budget.
This is the only one of the three that maps onto what you are actually trying to limit.

## Why agents loop

Chapter 8 listed the causes; here is how to tell them apart from the evidence you will have.

**Read the message list.** It is the whole story:

```python
for m in out["messages"]:
    print(type(m).__name__, str(m.content)[:80])
```

- **The same tool call repeated with identical arguments** → the tool's result does not tell
  the model to stop. `"No matching article."` invites another try; *"No article exists for
  this topic; answer from general knowledge or escalate"* does not. Fix the tool's output,
  not the prompt.
- **The same tool with slightly varying arguments** → the model is searching. Cap attempts
  and give it a way to give up.
- **No tool calls at all, but it still loops** → your exit condition is not reading what you
  think. Usually `messages[-1]` is not the model's reply because a node appended after it.
- **Alternating between two nodes** → a `Command(goto=...)` with a leftover static edge
  (Chapter 6), or two routers disagreeing.

## Cost that is not a loop

Runaway iteration is the dramatic failure. Three quieter ones cost more in aggregate.

**Message history growing without bound.** Every model call sends the whole conversation. On
turn 50 you are paying for turns 1–49 again. This is quadratic in the length of a thread and
it is the single largest avoidable cost in most agent applications. Trim or summarise —
`add_messages` supports replacing and removing messages by id, which is exactly the tool for
it.

**A reducer where you wanted replacement.** Chapter 3's warning, in its expensive form. A
field that should hold the current category instead holds every category ever considered,
and it goes into the prompt.

**Fan-out without a cap.** `Send` over a list that is usually 3 and occasionally 3,000. Set
`max_concurrency`, and validate the length of what you are fanning out over.

## Noticing before the invoice

Detection matters more than any limit, because a limit you set to 25 is still 25 model calls
per request across every request.

- **Record steps and tokens in state.** They then appear in every checkpoint, so "which
  threads were expensive" becomes a query rather than an investigation.
- **Alert on the distribution, not the mean.** A handful of runs hitting the recursion limit
  will not move an average. Watch the 99th percentile of steps per run.
- **Count `GraphRecursionError` explicitly.** It should be zero. Any occurrence is a bug that
  has already cost you money.
- **Use tracing.** Chapter 25 — LangSmith shows token counts per run, which is the number you
  actually care about.

## A pre-deploy checklist

Before a graph with a cycle goes to production:

- [ ] `recursion_limit` passed explicitly at every invoke site.
- [ ] A step counter in state with a graceful exit.
- [ ] Token usage accumulated in state.
- [ ] Every tool returns something that can end the loop, not just "nothing found".
- [ ] Message history is trimmed or summarised on long threads.
- [ ] `max_concurrency` set wherever `Send` fans out over runtime data.
- [ ] An alert on `GraphRecursionError` and on p99 steps per run.

## Try it

Watch the real ceiling, and then a sane one. The first command burns 10007 supersteps of
pure Python — imagine each being a model call:

```bash
uv run python -c "
import operator, time
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

class L(TypedDict): n: Annotated[int, operator.add]
g = (StateGraph(L).add_node('bump', lambda s: {'n': 1}).add_edge(START,'bump')
     .add_conditional_edges('bump', lambda s: 'bump', ['bump', END]).compile())
t = time.perf_counter()
try: g.invoke({'n': 0})
except Exception as e: print(type(e).__name__+':', str(e).splitlines()[0])
print(f'burned in {time.perf_counter()-t:.2f}s of pure Python')
"
```

Now add the graceful budget and confirm you get a result instead of an exception:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
class L(TypedDict): n: Annotated[int, operator.add]
g = (StateGraph(L).add_node('bump', lambda s: {'n': 1}).add_edge(START,'bump')
     .add_conditional_edges('bump', lambda s: END if s['n'] >= 8 else 'bump', ['bump', END])
     .compile())
print('stopped cleanly at:', g.invoke({'n': 0}, {'recursion_limit': 25}))
"
```

## Takeaways

- **The default recursion limit is 10007.** Unset, a broken agent loop is roughly ten
  thousand model calls per request.
- Pass `recursion_limit` explicitly on every graph with a cycle; treat its absence as a
  review failure.
- Use three layers: a hard cap per run, a **graceful step budget in state**, and a token
  budget — only the last measures what you actually care about.
- Diagnose loops from the message list: identical repeated tool calls mean the tool's result
  does not permit stopping. Fix the tool output.
- The quiet costs are unbounded message history (quadratic per thread), a reducer where you
  wanted replacement, and uncapped fan-out.
- Record steps and tokens **in state** so cost becomes queryable, and alert on p99 rather
  than the mean.

---

Previous: [Chapter 19 — When state is wrong](19-state-is-wrong.md) ·
Next: [Chapter 21 — Errors, retries and caching](21-errors-retries-caching.md)
