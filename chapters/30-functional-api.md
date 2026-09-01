# Chapter 30 — The Functional API

There is a second way to write LangGraph applications, and most people never encounter it.
Instead of declaring nodes and edges, you write an ordinary function and mark the parts that
should be durable.

```python
from langgraph.func import entrypoint, task

@task
def classify(body: str) -> str:
    return "billing" if "refund" in body else "unknown"

@task
def draft(category: str) -> str:
    return f"Reply about {category}"

@entrypoint(checkpointer=InMemorySaver())
def triage(body: str) -> str:
    cat = classify(body).result()
    return draft(cat).result()
```

```
result: Reply about billing
state:  Reply about billing
```

No `StateGraph`, no `add_edge`, no state schema. Control flow is Python — `if`, `for`,
`while`, `try` — and it still gets checkpointing, resumption, streaming and `interrupt()`.

## How it works

`@task` marks a unit of work whose result is checkpointed. Calling one returns a future;
`.result()` waits for it. `@entrypoint` marks the durable workflow.

Because a task's result is saved, **a resumed run does not re-execute completed tasks** — the
same guarantee as Chapter 14, expressed differently. The retry and the crash-recovery
semantics are the ones you already know.

Calling two tasks and resolving them later gives you parallelism without a graph:

```python
@entrypoint(checkpointer=saver)
def triage(body: str):
    kb = search_kb(body)          # both start
    customer = lookup(body)
    return combine(kb.result(), customer.result())
```

## What you give up

**State is whatever your function returns.** There is no shared state object, so no reducers —
which removes a whole class of bugs from Chapter 3 and also removes the mechanism that makes
parallel writes safe. You pass values as arguments instead, explicitly.

**No graph to draw.** `draw_mermaid()` has nothing to show. Chapter 16's first triage step is
unavailable, and so is the structural review it enables.

**No static structure at all.** The shape of the run is whatever the code did this time.
That is the point, and it is also why you cannot inspect the possible paths without reading
the function.

**Less material online.** The graph API is what nearly everything is written about.

## Choosing between them

| Signal | API |
|---|---|
| Control flow is ordinary Python — loops, conditionals, try/except | Functional |
| You want to see and reason about the structure | Graph |
| Adding durability to code that already exists | Functional |
| Human-in-the-loop at well-defined points | either |
| Complex parallel merging of shared state | Graph |
| The team is new to LangGraph | Graph |

The Functional API is at its best when you have a workflow already written as a function and
want it to survive a crash. Rewriting it as a graph would mean inverting perfectly good
control flow into edges for no benefit; adding two decorators does not.

The graph API is better when the structure *is* the thing you are designing — when you want
to draw it, review it, and reason about which paths exist. That is most agent applications,
which is why this book spends twenty-nine chapters on it.

They interoperate: a `@task` can call a compiled graph, and a graph node can call an
entrypoint. You do not have to choose once and forever.

## Interrupts work the same

`interrupt()` behaves identically, including the rule from Chapter 15:

```python
@entrypoint(checkpointer=saver)
def triage(body: str):
    d = draft(classify(body).result()).result()
    decision = interrupt({"draft": d})       # pauses here
    return d if decision == "approve" else decision
```

Resume with `Command(resume=...)` on the same thread, exactly as before.

**The entrypoint re-runs from the top on resume** — the same rule as an interrupt node, and
the reason `@task` matters. Recording every line that executes across a pause and a resume:

```
after first invoke: ['outside-task', 'inside-task']
after resume      : ['outside-task', 'inside-task', 'outside-task']

outside-task ran 2 times
inside-task  ran 1 times
```

Completed tasks are replayed from their checkpointed results rather than re-executed. Work
*outside* a task runs again. **Put side effects in tasks** — that is what makes them safe.

## Try it

```bash
uv run python -c "
from langgraph.func import entrypoint, task
from langgraph.checkpoint.memory import InMemorySaver

@task
def classify(body: str) -> str:
    return 'billing' if 'refund' in body else 'unknown'

@task
def draft(category: str) -> str:
    return f'Reply about {category}'

@entrypoint(checkpointer=InMemorySaver())
def triage(body: str) -> str:
    return draft(classify(body).result()).result()

cfg = {'configurable': {'thread_id': 'f1'}}
print('result:', triage.invoke('I want a refund', cfg))
print('state :', triage.get_state(cfg).values)
"
```

Then add a `print` outside any task and one inside a task, pause the workflow with an
`interrupt()`, resume it, and observe which printed twice.

## Takeaways

- `@entrypoint` and `@task` give durability, resumption, streaming and `interrupt()` to an
  ordinary Python function — no graph, no state schema, no edges.
- A `@task`'s result is checkpointed, so **completed tasks are not re-executed on resume**.
- Parallelism comes from calling several tasks and resolving their futures later.
- You give up shared state and reducers, the drawable structure, and most of the available
  documentation.
- Prefer it for **adding durability to existing procedural code**; prefer the graph API when
  the structure is what you are designing, or when the team is new.
- The two interoperate freely — a task can call a graph, and a node can call an entrypoint.
- On resume the entrypoint re-runs from the top; only tasks are replayed from results. Put
  side effects in tasks.

---

Previous: [Chapter 29 — Patterns](29-patterns.md) ·
Next: [Chapter 31 — The ecosystem](31-ecosystem.md)
