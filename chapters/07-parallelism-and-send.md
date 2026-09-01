# Chapter 7 — Parallelism and `Send`

Parallelism in LangGraph is not something you switch on. It is a consequence of graph shape:
if two nodes are ready in the same superstep, they run together. You get it by drawing the
graph that way, and — this is the part that catches people — you sometimes get it when you
did not mean to.

## Static fan-out

Two edges from one node is a fan-out:

```python
.add_edge("classify", "search_kb")
.add_edge("classify", "lookup_customer")
.add_edge("search_kb", "draft")
.add_edge("lookup_customer", "draft")
```

`search_kb` and `lookup_customer` run in one superstep; `draft` runs in the next, seeing
both results. Nothing is marked `parallel`. The shape *is* the parallelism.

Both branches write `evidence`, so `evidence` needs a reducer — without one you get the
`InvalidUpdateError` from Chapter 3. **This is the rule to internalise: fan-out and reducers
are the same subject.** Any field two concurrent branches write needs one.

## The unequal-branch trap

Here is the failure that costs a production incident, and it is not obvious from the
diagram.

Two branches join at one node, but one branch is longer than the other:

```python
.add_edge(START, "short")          # branch A: one node
.add_edge(START, "long1")          # branch B: two nodes
.add_edge("long1", "long2")
.add_edge("short", "join")
.add_edge("long2", "join")
```

You would expect `join` to run once, after both branches finish. Measured:

```
joins ran: 2 times
log: ['long1', 'short', "join saw ['short']", 'long2', "join saw ['long2', 'short']"]
```

**`join` ran twice.** Once in superstep 2 — triggered by `short`, seeing only `short`'s data
— and again in superstep 3, once `long2` arrived.

Recall the rule from Chapter 4: a node runs when a channel it subscribes to is written. Both
incoming edges write the same trigger, so the *first* one to fire is enough. In the diamond
of Chapter 4, both branches were one node long, so both fired in the same superstep and
`join` ran once. Make the branches uneven and that coincidence disappears.

If `join` sends an email, you have sent two. If it calls a paid model, you have paid twice.
If it writes to a database, you may have written a partial record and then a complete one.

Three fixes, in order of preference:

**Equalise the branches.** Often the simplest honest fix — restructure so both paths are the
same length, or move the extra work inside one node.

**Gate on completeness.** Have `join` check whether it has everything and return `None` if
not:

```python
def join(state):
    if "long2" not in state["log"]:
        return None          # not ready; the later trigger will bring us back
    return {"summary": ...}
```

Explicit and easy to test, at the cost of the node running more than once.

**Fan out with `Send` instead**, which does not have this problem, because the join is not
triggered until every dispatched task returns.

The general lesson: **a join node is only safe if all its inbound branches are the same
length.** Chapter 19 lists the symptom — "my node ran twice" — under diagnosis.

## `Send`: dynamic fan-out

Static edges require you to know the branches at build time. `Send` lets you decide at
runtime how many parallel tasks to spawn, and what each receives.

Return a list of `Send` objects from a conditional edge:

```python
def fan(state):
    return [Send("worker", {"topic": t}) for t in state["topics"]]

.add_conditional_edges(START, fan, ["worker"])
.add_edge("worker", "summarise")
```

`Send("worker", {...})` means "run `worker`, with **this** as its state". Three topics:

```
{'topics': ['a', 'b', 'c'], 'results': ['did:a', 'did:b', 'did:c'], 'summary': '3 done'}
```

And the supersteps show all three landing at once:

```
{'topics': ['a','b','c'], 'results': []}
{'topics': ['a','b','c'], 'results': ['did:a', 'did:b', 'did:c']}
{'topics': ['a','b','c'], 'results': ['did:a','did:b','did:c'], 'summary': '3 done'}
```

Three snapshots for three supersteps: dispatch, all workers, summarise. One worker or fifty
— same graph, same code.

Two things about `Send` that are not obvious:

**The worker gets the payload, not the graph state.** Have a worker report the keys it can
actually see:

```
["keys=['topic']"]
```

One key. `topics`, `results` and everything else in the graph state are absent. This is a
feature — workers are isolated — but it surprises people who expect shared state to be
readable everywhere. Anything a worker needs must go into the `Send`.

**Its writes go to the real state, through the reducers.** That is how results come back, and
why `results` must have a reducer. Without one you get `InvalidUpdateError` the moment you
have more than one worker — the classic version of that error.

## Map-reduce

`Send` plus a reducer is map-reduce, and it is the workhorse pattern for LLM applications:
summarise ten documents, evaluate one answer against five criteria, run one query against
four retrievers.

```python
def fan_out(state):                                  # map
    return [Send("grade", {"criterion": c, "answer": state["answer"]})
            for c in state["criteria"]]

def grade(payload):                                  # one worker
    return {"scores": [score_one(payload)]}

def aggregate(state):                                # reduce
    return {"verdict": sum(state["scores"]) / len(state["scores"])}
```

The whole fan-out costs one superstep of wall clock rather than *n*, which for LLM calls at
several hundred milliseconds each is the difference between a usable feature and a timeout.

## Controlling concurrency

Fifty parallel model calls will hit a rate limit. Cap in-flight work with `max_concurrency`:

```python
graph.invoke(state, {"max_concurrency": 5})
```

Six workers sleeping 0.2 s each, unconstrained and then capped at two:

```
max_concurrency=None: 0.21s for 6x0.2s
max_concurrency=2:    0.61s for 6x0.2s
```

Unconstrained, all six overlap and the whole fan-out costs one worker's latency. Capped at
two, they run in three batches. Workers beyond the limit queue and run as slots free; the
graph is unchanged and only the scheduler is constrained. Chapter 21 covers what to do about the rate-limit errors that get
through anyway.

## When a branch fails

By default, an exception in one parallel branch fails the whole superstep. Sibling branches
already running are allowed to finish, but their results are discarded — the step did not
complete, so nothing is committed.

That is usually right: a partial result silently treated as complete is worse than an error.
When you want the opposite — best-effort fan-out where some workers may fail — catch inside
the worker and return the failure as data:

```python
def worker(payload):
    try:
        return {"results": [do_work(payload)]}
    except Exception as exc:
        return {"failures": [{"topic": payload["topic"], "error": str(exc)}]}
```

Now the aggregate step can see what succeeded and what did not, and decide. Chapter 21
covers retries for the transient cases.

## Try it

Watch the unequal-branch trap fire. This is the one worth seeing with your own eyes:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict):
    log: Annotated[list, operator.add]
    joins: Annotated[int, operator.add]
def n(name): return lambda s: {'log':[name]}
def join(s): return {'log':['join ran'], 'joins':1}

g = (StateGraph(S).add_node('short', n('short'))
     .add_node('long1', n('long1')).add_node('long2', n('long2')).add_node('join', join)
     .add_edge(START,'short').add_edge(START,'long1').add_edge('long1','long2')
     .add_edge('short','join').add_edge('long2','join').add_edge('join',END).compile())
out = g.invoke({'log':[],'joins':0})
print('join ran', out['joins'], 'times')
"
```

Then equalise the branches — delete `long1` and wire `START -> long2` — and confirm it drops
to one.

Now fan out dynamically and watch the worker count stop mattering:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

class S(TypedDict):
    topics: list
    results: Annotated[list, operator.add]
g = (StateGraph(S).add_node('worker', lambda s: {'results':[f\"did:{s['topic']}\"]})
     .add_conditional_edges(START, lambda s: [Send('worker', {'topic':t}) for t in s['topics']], ['worker'])
     .add_edge('worker', END).compile())
print(g.invoke({'topics': list('abcdef'), 'results': []})['results'])
"
```

Finally, remove the reducer from `results` and watch it become `InvalidUpdateError`.

## Takeaways

- Parallelism is graph shape, not a setting. Two edges out of one node means both run.
- **Fan-out and reducers are the same subject.** Any field written by concurrent branches
  needs one.
- **A join node with branches of unequal length runs more than once**, the first time with
  incomplete data. Equalise the branches, gate on completeness, or use `Send`.
- `Send("node", payload)` dispatches a dynamic number of workers. The worker sees **only the
  payload**, not graph state, but its writes go through the real reducers.
- `Send` plus a reducer is map-reduce, and it turns *n* sequential model calls into one
  superstep.
- Cap in-flight work with `max_concurrency` in the run config.
- A failing branch fails the superstep and discards siblings' results. For best-effort work,
  catch inside the worker and return the failure as data.

---

Previous: [Chapter 6 — Edges and routing](06-edges-and-routing.md) ·
Next: [Chapter 8 — Loops, limits and termination](08-loops-and-limits.md)
