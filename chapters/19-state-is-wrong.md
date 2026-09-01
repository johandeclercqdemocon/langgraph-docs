# Chapter 19 — When state is wrong

Layer 3. The graph has the right shape and the right nodes ran, but the data is wrong.

Almost every bug in this category is one of six, and they are worth knowing by their
symptoms because the underlying causes are not guessable from the output.

## 1. A value disappeared

**Symptom:** a node wrote a field; later it holds something else, or the original.

**Cause:** no reducer, so the write replaced rather than merged (Chapter 3). Or two nodes
wrote it and you are seeing the second.

**Check:**

```python
for chunk in graph.stream(inp, stream_mode="values"):
    print(chunk["the_field"])
```

The step where it changes unexpectedly names the node responsible.

## 2. A node appears to do nothing

**Symptom:** the node runs — you can see it in `updates` — but state is unchanged.

**Cause, in order of likelihood:**

- **A typo in the returned key.** Dropped silently (Chapter 2). Check the spelling against
  the schema first, every time.
- The node returned `None`, or a dict that was empty.
- The node mutated the state instead of returning a dict (see below).

**Check:** print exactly what the node returns, in isolation:

```python
print(classify({"body": "I want a refund"}))
```

## 3. Mutation, and why it is so bad

**Symptom:** duplicated entries, values that grow strangely, results that differ between the
first and second run of a thread.

Chapter 2 said never to mutate the input state. Here is what it actually costs. A node that
appends in place and returns the whole state:

```python
def bad(state):
    state["log"].append("mutated")     # in-place
    return state                       # return everything
```

Against `{"log": ["initial"]}` and a field with `operator.add`:

```
{'log': ['initial', 'mutated', 'initial', 'mutated']}
```

Four entries from one node. The mutation changed the current value to
`['initial', 'mutated']`, and then returning the whole state submitted *that same list* as
an update, which the reducer appended to the value it had just mutated.

Add a checkpointer and run the thread twice:

```
run1: {'log': ['initial', 'mutated', 'initial', 'mutated']}
run2: {'log': ['initial', 'mutated', 'initial', 'mutated', 'mutated',
               'initial', 'mutated', 'initial', 'mutated', 'mutated']}
```

Ten entries. The correct version is unremarkable:

```
{'log': ['initial', 'appended']}
```

**The rule, restated: return a dict of changes, never the state you were given.** If you
find yourself writing `return state`, that is the bug.

## 4. A node saw stale data

**Symptom:** a node reads a field another node just wrote and gets the old value.

**Cause:** they are in the same superstep (Chapter 4). Measured there:

```
{'category': 'billing', 'seen': ["reader saw category='unset'"]}
```

**Check:** `stream_mode="values"` — if both writes appear in the *same* transition, the nodes
ran together and neither could see the other.

**Fix:** add an edge to force ordering. Two nodes that must be sequential need an edge
between them; being written in sequence in your file means nothing.

## 5. A node ran twice

**Symptom:** duplicated work, doubled side effects, a counter that increments by two.

**Cause:** branches of unequal length joining at one node (Chapter 7). Measured there, the
join ran twice — once with partial data.

**Check:** count occurrences in `updates`:

```python
from collections import Counter
print(Counter(k for c in graph.stream(inp, stream_mode="updates") for k in c))
```

**Fix:** equalise the branches, gate on completeness, or use `Send`.

## 6. A value is doubled after a subgraph

**Symptom:** an accumulated field contains everything twice, or the parent's earlier entries
reappear.

**Cause:** parent and subgraph share a reducer key (Chapter 9):

```
{'log': ['before', 'before', 'inner', 'after']}
```

**Check:** `stream(..., subgraphs=True)` and look at the update the subgraph node returns.
It will be the whole accumulated list rather than just the new part.

**Fix:** rename the key, or wrap the subgraph in a node.

## The diagnostic that finds all six

One loop, printing state after every superstep:

```python
for chunk in graph.stream(inp, stream_mode="values"):
    print(chunk)
```

Find the **first** step where the state differs from what you expected. Everything after
that is a consequence, and the node that ran at that step is your suspect. This is worth
more than any amount of reasoning about the code, because all six causes above are invisible
in the source and obvious in the sequence.

If the graph has a checkpointer, `get_state_history()` gives you the same filmstrip after
the fact, which works on a run that already happened (Chapter 12).

## Guarding against the whole class

Three habits prevent most of this.

**Assert on `trail`.** With every node appending its name, one assertion covers routing,
ordering, and duplication:

```python
assert out["trail"] == ["classify", "retrieve", "draft"]
```

A node that ran twice, or a branch that took the wrong path, fails this immediately.

**Type-check the schema.** A `TypedDict` plus a type checker catches misspelled keys — the
silent failure — before you run. This is the single highest-value piece of tooling for
LangGraph specifically, because the framework will not tell you.

**Test nodes as functions.** A node's behaviour is a pure input/output question. Chapter 24
builds this out.

## Try it

Watch mutation destroy a list, then fix it:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict): log: Annotated[list, operator.add]
def bad(state):
    state['log'].append('mutated')
    return state
def good(state):
    return {'log': ['appended']}

for name, fn in (('mutating', bad), ('correct ', good)):
    g = (StateGraph(S).add_node('n', fn).add_edge(START,'n').add_edge('n',END).compile())
    print(name, g.invoke({'log': ['initial']}))
"
```

Now count how often each node runs, which is the check for cause 5:

```bash
uv run python -c "
from collections import Counter
from examples.triage.graph import build_routed
g = build_routed()
print(Counter(k for c in g.stream({'ticket_id':'T-1','body':'billing refund'}, stream_mode='updates') for k in c))
"
```

## Takeaways

- Six causes cover nearly all wrong-state bugs: no reducer, a typo'd key, mutation, a stale
  read within a superstep, a node running twice, and a double-counting subgraph.
- **Mutating state is not a style issue.** One node produced four entries where one was
  expected, and ten after a second run on the same thread.
- `return state` is the bug. Return a dict of changes.
- A stale read means the two nodes are in the same superstep. Add an edge — file order is
  not execution order.
- A node running twice means branches of unequal length. Count node occurrences in `updates`.
- Doubling after a subgraph means a shared reducer key. Inspect with `subgraphs=True`.
- **The universal diagnostic is `stream_mode="values"`**: find the first step where state
  differs from expectation.
- Prevent the class with a `trail` assertion, a type checker over the state schema, and
  node-level unit tests.

---

Previous: [Chapter 18 — Streaming and observing](18-streaming.md) ·
Next: [Chapter 20 — Runaway loops and cost](20-runaway-loops-and-cost.md)
