# Chapter 11 — Checkpointers and threads

Everything durable in LangGraph rests on one idea: after each superstep, write the state
somewhere. That is a checkpointer, and adding one is a single argument:

```python
graph = builder.compile(checkpointer=InMemorySaver())
```

From that line follow conversation memory, crash recovery, human-in-the-loop, and time
travel. Chapters 12 to 15 are all consequences of this chapter.

## Threads

A checkpointer stores state per **thread**. A thread is an identifier you choose — a
conversation, a ticket, a user session — and it is required once a checkpointer is present:

```python
config = {"configurable": {"thread_id": "ticket-1001"}}
graph.invoke({"log": []}, config)
```

Invoking the same thread twice continues where it left off. Threads are completely
isolated:

```
thread a: {'log': ['x', 'x']}   thread b: {'log': ['x']}
```

Thread `a` was invoked twice and accumulated two entries; thread `b`, invoked once, has one.
Same graph, same process, same checkpointer.

This is where "memory" comes from, and it is worth being precise: there is no memory
feature. There is a saved state, keyed by a string you supply. Choosing `thread_id` well —
stable per conversation, unique per user — *is* the memory design.

**Forget the `thread_id` and you get an error, not a fresh run:**

```
ValueError: Checkpointer requires one or more of the following 'configurable' keys:
thread_id, checkpoint_ns, checkpoint_id
```

That is the right behaviour — silently starting over would be worse.

## Reading state

`get_state(config)` returns a `StateSnapshot`:

```
values: {'log': ['x', 'x']}
next: ()
step: 4  source: loop
checkpoint_id: 1f1a5652-a05d-6382-8 ...
```

Four fields carry the weight:

**`values`** — the state itself.

**`next`** — the nodes that will run on the next step. `()` means finished. **A non-empty
`next` on a completed call means the graph is paused**, which is how you detect an interrupt
(Chapter 15).

**`metadata.step`** — the superstep counter, continuing across invocations on the same
thread. Note the `4` above after two runs of a one-node graph; it is not a per-run counter.

**`config.configurable.checkpoint_id`** — the identifier of this exact checkpoint. Passing it
back is how you address a past point in time (Chapter 12).

## Choosing one

| Checkpointer | Install | Use for |
|---|---|---|
| `InMemorySaver` | built in | tests, notebooks, examples |
| `SqliteSaver` | `langgraph-checkpoint-sqlite` | local development, single-process apps |
| `PostgresSaver` | `langgraph-checkpoint-postgres` | production |
| none | — | stateless, single-shot graphs |

`InMemorySaver` is a dict. It dies with the process, and it is the right choice for every
example in this book — but shipping it is the mistake that turns "our agent forgets
everything on deploy" into a bug report.

SQLite genuinely persists. Same thread id, a new saver over the same file:

```
before:            {'log': ['x', 'x']}
after reopening:   {'log': ['x', 'x']}
```

Note the context-manager form, which is easy to get wrong:

```python
with SqliteSaver.from_conn_string("checkpoints.sqlite") as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
    graph.invoke(...)
```

The connection closes at the end of the `with` block, and a graph compiled with a closed
checkpointer fails at the next invoke. In a web application, the checkpointer's lifetime
must be the *application's*, not a request's. Chapter 23 shows that wiring.

For production use Postgres. It is the only option in the table that handles several
processes writing concurrently, which is what any real deployment is.

## What gets written, and when

One checkpoint per superstep — not per node. This follows directly from Chapter 4: updates
are applied between supersteps, so a superstep is the smallest unit with a consistent state
to save.

The consequence for recovery: **you resume at a superstep boundary.** If two nodes ran in
parallel and the process died after one finished, neither result was committed and both
re-run. Nodes must therefore be **idempotent** — safe to run twice — or you must guard side
effects yourself. A node that charges a card needs an idempotency key regardless of what
your framework promises.

## Durability modes

You can trade durability for speed with the `durability` argument:

```python
graph.invoke(state, config, durability="async")
```

| Mode | Behaviour |
|---|---|
| `"sync"` | Write and wait for it before continuing. Safest, slowest. |
| `"async"` | Write in the background while the next step runs. |
| `"exit"` | Write only when the run finishes. Fastest, loses everything on a crash. |

`"exit"` is tempting and usually wrong: a run that ends normally is exactly the run you did
not need durability for. Use `"async"` when checkpoint latency measurably matters, and stay
with the default otherwise. Never use `"exit"` on a graph with an `interrupt()` in it, since
pausing *is* an unfinished run.

## What must not go in state

Everything in state is serialised. Two categories break this:

**Unserialisable objects** — database connections, file handles, clients, model instances.
Put these in context (Chapter 5) or module scope.

**Things that should not be persisted** — API keys, raw card numbers, personal data you
have promised to delete. A checkpointer is a database, and a `thread_id` that lives forever
means the data does too. Chapter 28 covers retention.

The failure mode is a serialisation error at the first checkpoint write, which is at least
loud. The second category is silent, and worse.

## Try it

Watch two threads stay isolated:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

class S(TypedDict): log: Annotated[list, operator.add]
g = (StateGraph(S).add_node('step', lambda s: {'log':['x']})
     .add_edge(START,'step').add_edge('step',END).compile(checkpointer=InMemorySaver()))
a = {'configurable':{'thread_id':'a'}}; b = {'configurable':{'thread_id':'b'}}
g.invoke({'log':[]}, a); g.invoke({'log':[]}, a); g.invoke({'log':[]}, b)
print('a:', g.get_state(a).values, ' b:', g.get_state(b).values)
"
```

Then prove SQLite outlives the saver object:

```bash
uv run python -c "
import operator, tempfile, os
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

class S(TypedDict): log: Annotated[list, operator.add]
def mk(cp): return (StateGraph(S).add_node('step', lambda s:{'log':['x']})
    .add_edge(START,'step').add_edge('step',END).compile(checkpointer=cp))
path = tempfile.mktemp(suffix='.sqlite'); cfg={'configurable':{'thread_id':'a'}}
with SqliteSaver.from_conn_string(path) as cp:
    g = mk(cp); g.invoke({'log':[]}, cfg); g.invoke({'log':[]}, cfg)
    print('before:', g.get_state(cfg).values)
with SqliteSaver.from_conn_string(path) as cp:
    print('after: ', mk(cp).get_state(cfg).values)
os.unlink(path)
"
```

Finally, remove the `thread_id` from the config and read the error — you want to recognise
it instantly.

## Takeaways

- A checkpointer writes state after every **superstep**. One argument to `compile()` enables
  everything durable.
- State is stored per **thread**. There is no memory feature — there is a saved state keyed
  by a `thread_id` you choose, and choosing it well is the memory design.
- `get_state()` returns a snapshot; **a non-empty `next` after a completed call means the
  graph is paused**.
- `metadata.step` counts supersteps across the whole thread, not per run.
- `InMemorySaver` for tests, SQLite for local, **Postgres for production** — it is the only
  one safe for multiple processes.
- A SQLite checkpointer opened with `with` closes at the end of the block. Its lifetime must
  match the application's, not a request's.
- Recovery resumes at a superstep boundary, so **nodes must be idempotent**. Guard real side
  effects yourself.
- `durability="exit"` is fast and usually wrong, and is incompatible with `interrupt()`.
- State is serialised: keep connections and clients out of it, and remember that secrets put
  there are persisted.

---

Previous: [Chapter 10 — The prebuilt agent](10-prebuilt-agent.md) ·
Next: [Chapter 12 — Time travel](12-time-travel.md)
