# Chapter 12 — Time travel

A checkpointer does not keep only the latest state. It keeps every checkpoint, which means
the history of a run is queryable, editable, and re-runnable.

This is the capability that most justifies the framework, and it is the one people most
often do not know they have.

## The history

`get_state_history(config)` yields every checkpoint on a thread, **newest first**. A
three-node graph, after one run:

```
step= 3 next=()             values={'log': ['a', 'b', 'c'], 'n': 3}
step= 2 next=('c',)         values={'log': ['a', 'b'], 'n': 2}
step= 1 next=('b',)         values={'log': ['a'], 'n': 1}
step= 0 next=('a',)         values={'log': [], 'n': 0}
step=-1 next=('__start__',) values={'log': []}
```

Read it as a filmstrip. Each row is the state **before** the node in `next` ran. Step 2 is
"after `b`, about to run `c`".

Two details worth noticing. Step `-1` is the input as received, before anything ran. And
`next` is what makes a row addressable: to answer "what did the graph look like just before
`c`", filter for `next == ("c",)`.

This alone is a debugging tool. When a run produces a wrong answer, you do not have to infer
what happened from logs — you can read the state at every step.

## Resuming from a past checkpoint

Every snapshot carries a `config` that identifies it. Pass that back instead of the thread
config, and the graph runs forward from there:

```python
history = list(graph.get_state_history(config))
before_c = [h for h in history if h.next == ("c",)][0]

graph.invoke(None, before_c.config)     # re-run from just before c
```

`None` as input means "no new input, continue from the checkpoint".

## Editing the past

`update_state` writes a new checkpoint on top of an existing one, as if a node had produced
that update. Combined with a past checkpoint, this is a fork:

```python
forked = graph.update_state(before_c.config, {"log": ["MANUAL"], "n": 99})
graph.invoke(None, forked)
```

```
forking at: {'log': ['a', 'b'], 'n': 2}
resumed:    {'log': ['a', 'b', 'MANUAL', 'c'], 'n': 3}
```

`MANUAL` was injected before `c` ran, and `c` then ran normally on the modified state. Note
that `log` *appended* — `update_state` goes through the field's reducer exactly like a node's
return value. It is not a raw assignment, and forgetting that is a reliable source of
confusion on reducer fields.

You can also attribute the update to a specific node, which matters when that determines
what runs next:

```python
graph.update_state(config, {"category": "billing"}, as_node="classify")
```

## The fork stays on the same thread

Here is the part that surprises people, and it is worth measuring rather than assuming.

After forking and resuming, ask the *original* thread config for its state:

```
original head: {'log': ['a', 'b', 'MANUAL', 'c']}
```

The fork is not a separate timeline. `update_state` appended new checkpoints to the same
thread, so the thread's head is now the forked branch. The history contains both:

```
step= 4 next=()             {'log': ['a', 'b', 'MANUAL', 'c']}
step= 3 next=('c',)         {'log': ['a', 'b', 'MANUAL']}
step= 3 next=()             {'log': ['a', 'b', 'c']}      <- the original branch
step= 2 next=('c',)         {'log': ['a', 'b']}
step= 1 next=('b',)         {'log': ['a']}
step= 0 next=('a',)         {'log': []}
step=-1 next=('__start__',) {'log': []}
```

Two rows at `step=3`. Nothing was destroyed — the original outcome is still there and still
addressable by its `checkpoint_id` — but "the current state of this thread" now means the
fork.

For a genuinely independent branch, seed a **new thread**:

```python
branch = {"configurable": {"thread_id": "branch"}}
graph.update_state(branch, before_c.values)
```

```
new thread seeded: {'log': ['a', 'b']}
original head:     {'log': ['a', 'b', 'MANUAL', 'c']}
```

Now the two evolve independently. Use this for A/B comparisons, and for anything where the
original run must remain authoritative.

## What it is actually for

**Debugging a bad answer.** Find the step where the state first went wrong, rather than
reasoning backwards from the output.

**Testing a fix without re-running everything.** If step nine was wrong, fork at step eight
and run forward. The first eight steps' model calls are not repeated, which on a long agent
run is the difference between a fast loop and a slow one.

**Recovering from a bad tool result.** A tool returned nonsense and the agent went astray.
Fork to before the tool call, `update_state` a corrected `ToolMessage`, and continue.

**Human correction.** The reviewer in Chapter 15 edits a draft; that edit is an
`update_state` under the surface.

**Counterfactuals.** Same history, different decision, on a separate thread. The most
under-used of the five.

## Costs

History is not free.

**Storage grows per superstep, per thread.** A long-running agent on one thread accumulates
thousands of checkpoints, each holding a full copy of state. If `messages` is in state, each
checkpoint holds the whole conversation so far. Chapter 28 covers retention and cleanup;
plan for it before you have a large table rather than after.

**Replay is not free either.** Forking re-runs the nodes after the fork point, with real
model calls and real side effects. If those nodes send email, forking sends it again.

**It is not an audit log.** Checkpoints can be edited by anyone who can call `update_state`,
and forking rewrites what a thread's history "means". If you need a tamper-evident record of
what actually happened, write one separately.

## Try it

Read a run's filmstrip:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

class S(TypedDict): log: Annotated[list, operator.add]
g = (StateGraph(S).add_node('a', lambda s:{'log':['a']}).add_node('b', lambda s:{'log':['b']})
     .add_node('c', lambda s:{'log':['c']})
     .add_edge(START,'a').add_edge('a','b').add_edge('b','c').add_edge('c',END)
     .compile(checkpointer=InMemorySaver()))
cfg = {'configurable':{'thread_id':'t'}}
g.invoke({'log': []}, cfg)
for h in g.get_state_history(cfg):
    print(f\"step={h.metadata.get('step'):>2} next={str(h.next):<16} {h.values}\")
"
```

Then fork it, and check the original thread afterwards — the head has moved:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

class S(TypedDict): log: Annotated[list, operator.add]
g = (StateGraph(S).add_node('a', lambda s:{'log':['a']}).add_node('b', lambda s:{'log':['b']})
     .add_node('c', lambda s:{'log':['c']})
     .add_edge(START,'a').add_edge('a','b').add_edge('b','c').add_edge('c',END)
     .compile(checkpointer=InMemorySaver()))
cfg = {'configurable':{'thread_id':'t'}}
g.invoke({'log': []}, cfg)
before_c = [h for h in g.get_state_history(cfg) if h.next == ('c',)][0]
forked = g.update_state(before_c.config, {'log': ['MANUAL']})
print('resumed:', g.invoke(None, forked))
print('original head:', g.get_state(cfg).values)
"
```

Then do it again into a fresh `thread_id` and confirm the original head is untouched.

## Takeaways

- `get_state_history()` yields every checkpoint, **newest first**. Each row is the state
  *before* the node in `next` ran; `step=-1` is the raw input.
- Any snapshot's `config` can be passed to `invoke(None, snapshot.config)` to run forward
  from that point.
- `update_state` writes an update **through the reducers** — on a reducer field it appends
  rather than assigns.
- **A fork stays on the same thread.** `update_state` appends checkpoints, so the thread head
  becomes the forked branch. Both branches remain in history.
- For an independent timeline, seed a **new `thread_id`** with the old snapshot's values.
- Use it to locate where state first went wrong, to test fixes without replaying earlier
  model calls, to repair bad tool results, and to run counterfactuals.
- Costs: storage grows per superstep per thread; replay re-executes real side effects; and
  because history is editable, **it is not an audit log**.

---

Previous: [Chapter 11 — Checkpointers and threads](11-checkpointers-and-threads.md) ·
Next: [Chapter 13 — Store: memory across threads](13-store.md)
