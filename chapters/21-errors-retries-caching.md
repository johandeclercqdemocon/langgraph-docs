# Chapter 21 — Errors, retries and caching

Not every exception deserves the same response, and the most common mistake is treating them
all alike — usually by wrapping everything in a retry, which turns a permanent failure into a
slower permanent failure.

## Four kinds of error, four responses

| Kind | Example | Who can fix it | Response |
|---|---|---|---|
| Transient | timeout, 429, connection reset | the system, by waiting | `RetryPolicy` |
| Model-recoverable | tool raised on bad arguments | the model, by trying differently | return the error as a `ToolMessage` |
| User-fixable | missing information, needs approval | a person | `interrupt()` |
| Genuine bug | `KeyError`, `TypeError` | you | let it raise |

Getting this wrong in either direction is costly. Retrying a `KeyError` three times just
delays the traceback. Letting a 429 bubble up fails a request that would have succeeded a
second later.

## Retries

Attach a policy per node:

```python
from langgraph.types import RetryPolicy

builder.add_node(
    "search", search_documentation,
    retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0),
)
```

A node failing twice and succeeding on the third attempt:

```
retry result: {'out': ['ok after 3']}
```

The graph never saw a failure. Backoff is exponential from `initial_interval`.

Three things worth knowing:

**Retries are per node, not per graph.** Only nodes you mark are retried, which is correct —
you rarely want a retry policy on a node with side effects.

**A retried node runs its whole body again.** Same idempotency requirement as Chapter 14. A
node that writes to a database and then calls a flaky API will write twice.

**Narrow what you retry.** `RetryPolicy` accepts a predicate; use it rather than retrying
everything:

```python
RetryPolicy(max_attempts=3, retry_on=(ConnectionError, TimeoutError))
```

Retrying a `ValueError` from your own validation is never right.

## Errors the model should handle

A tool failing because the model passed bad arguments is not a system failure — it is
information. `ToolNode` handles this by default:

```python
ToolNode(tools)            # handle_tool_errors=True by default
```

The exception becomes a `ToolMessage` containing the error text, the loop continues, and the
model gets to try again. This is usually what you want, and it is why the prebuilt agent
recovers from a mistyped tool argument without any work from you.

Two cautions. It can mask real bugs — a tool broken for everyone looks like the model being
unlucky, and the loop keeps paying for retries. And it interacts with Chapter 20: a tool that
always errors is a tool that always invites another attempt. Bound the loop.

For a tool where a failure is genuinely fatal, turn it off for that node and let it raise.

## Caching

Node-level caching skips re-execution when the input is unchanged:

```python
from langgraph.types import CachePolicy
from langgraph.cache.memory import InMemoryCache

builder.add_node("slow", slow_node, cache_policy=CachePolicy(ttl=60))
graph = builder.compile(cache=InMemoryCache())
```

The same input twice:

```
run1: 0.304s  fn calls so far=1
run2: 0.002s  fn calls so far=1
```

A 150× difference, and the function body ran **once**. The cache key is derived from the
node's input, so this is only safe when the node is a pure function of its input.

Where it pays:

- **Development.** Re-running a graph while editing a later node, without repeating an
  expensive retrieval each time. This alone justifies knowing about it.
- **Deterministic, expensive steps.** Embedding a document, parsing a large file.
- **Repeated identical work** across runs — the same document classified in many threads.

Where it does not:

- **Anything with side effects.** A cached node does not run, so its side effect does not
  happen. This is a real trap when the side effect was incidental.
- **Anything time-dependent.** "Today's tickets" cached for an hour is a wrong answer with
  good latency.
- **Model calls where variety matters.** Caching a creative generation makes it identical
  every time, which is occasionally what you want and usually not.

Set a `ttl` deliberately. Use `InMemoryCache` for development; a shared cache for production,
where the point is sharing across processes.

## Failure in parallel branches

Chapter 7 covered the semantics: one branch failing fails the superstep, and siblings'
results are discarded. For best-effort work, catch inside the worker and return the failure
as data:

```python
def worker(payload):
    try:
        return {"results": [do_work(payload)]}
    except Exception as exc:
        return {"failures": [{"input": payload, "error": str(exc)}]}
```

Now the aggregation step can see what succeeded, and you can decide whether four of five is
good enough. This composes well with retries: let `RetryPolicy` handle the transient cases,
and treat what still fails as data.

## Timeouts

A hanging node is worse than a failing one, because nothing tells you. Set timeouts at the
client — most model and HTTP clients take one — and treat the resulting exception as
transient:

```python
model = init_chat_model("claude-sonnet-5", timeout=30, max_retries=0)
```

Note `max_retries=0`. Model clients have their own retry logic, and stacking it under a
LangGraph `RetryPolicy` multiplies: three client retries under three node attempts is nine
calls and nine times the latency before anything is reported. Pick one layer to own retries.
Doing it at the node is usually clearer, because that is where the backoff is visible in your
graph.

## Try it

Watch a retry policy absorb two failures:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy

attempts = {'n': 0}
class S(TypedDict): out: Annotated[list, operator.add]
def flaky(state):
    attempts['n'] += 1
    if attempts['n'] < 3: raise ConnectionError(f\"timeout {attempts['n']}\")
    return {'out': [f\"ok after {attempts['n']}\"]}

g = (StateGraph(S).add_node('flaky', flaky, retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.01))
     .add_edge(START,'flaky').add_edge('flaky',END).compile())
print(g.invoke({'out': []}))
"
```

Then measure the cache, and note the call counter does not move:

```bash
uv run python -c "
import time, operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import CachePolicy
from langgraph.cache.memory import InMemoryCache

calls = {'n': 0}
class S(TypedDict): out: Annotated[list, operator.add]
def slow(state):
    calls['n'] += 1; time.sleep(0.3); return {'out': ['done']}

g = (StateGraph(S).add_node('slow', slow, cache_policy=CachePolicy(ttl=60))
     .add_edge(START,'slow').add_edge('slow',END).compile(cache=InMemoryCache()))
for i in (1,2):
    t = time.perf_counter(); g.invoke({'out': []})
    print(f'run{i}: {time.perf_counter()-t:.3f}s  fn calls={calls[\"n\"]}')
"
```

Now add a `print("side effect")` to `slow` and confirm it does not print on the second run.
That is the caching trap in one line.

## Takeaways

- Classify before responding: **transient** → retry, **model-recoverable** → return as a
  `ToolMessage`, **user-fixable** → `interrupt()`, **bug** → let it raise.
- `RetryPolicy` is per node with exponential backoff. Narrow it with `retry_on`; never retry
  your own `ValueError`.
- A retried node re-runs entirely — the same idempotency requirement as resumption.
- `ToolNode` turns tool exceptions into `ToolMessage`s by default so the model can recover.
  This can also mask a genuinely broken tool, so bound the loop.
- `CachePolicy` + a cache on `compile()` skips re-execution: measured 0.304s → 0.002s with
  the body running once.
- **A cached node does not run, so its side effects do not happen.** Cache only pure,
  time-independent work, and always set a `ttl`.
- For best-effort fan-out, catch inside the worker and return failures as data.
- **Do not stack client retries under node retries** — three under three is nine calls. Pick
  one layer.

---

Previous: [Chapter 20 — Runaway loops and cost](20-runaway-loops-and-cost.md) ·
Next: [Chapter 22 — Cookbook: symptom → cause → fix](22-cookbook.md)
