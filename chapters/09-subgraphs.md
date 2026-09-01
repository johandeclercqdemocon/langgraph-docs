# Chapter 9 — Subgraphs

A compiled graph can be a node in another graph:

```python
.add_node("sub", some_compiled_graph)
```

That one line is the whole composition story, and it is genuinely useful — a retrieval
pipeline, a reflection loop, or a validation routine can be built and tested on its own and
then dropped into a larger graph.

It also contains the sharpest trap in this book, and you will not notice it from reading the
code.

## The trap: shared reducer keys double-count

A parent and a subgraph that both declare `log: Annotated[list, operator.add]`. The parent
runs `before`, then the subgraph (which appends `inner`), then `after`:

```python
.add_edge(START, "before")
.add_edge("before", "sub")
.add_edge("sub", "after")
```

Expected: `['before', 'inner', 'after']`. Measured:

```
{'log': ['before', 'before', 'inner', 'after']}
```

**`before` appears twice.**

The mechanism, once you see it, is obvious and entirely consistent with Chapter 3:

1. The parent's `log` is `['before']`.
2. Keys shared with the subgraph's schema are passed in, so the subgraph *starts* with
   `log = ['before']`.
3. The subgraph appends, ending at `['before', 'inner']`.
4. The subgraph returns its **whole** `log` as its update to the parent.
5. The parent's reducer is `operator.add`, so it **appends** that to its own `['before']`,
   giving `['before', 'before', 'inner']`.

Nothing is broken. A reducer did exactly what it was told, twice. Streaming with
`subgraphs=True` shows the returning update plainly:

```
((), {'before': {'log': ['before']}})
(('sub:f0241a94-...',), {'inner': {'log': ['inner']}})
((), {'sub': {'log': ['before', 'inner']}})
((), {'after': {'log': ['after']}})
```

Look at the third line: the `sub` node's update is `['before', 'inner']` — the accumulated
list, not just the new part.

**This is silent.** No error, no warning. A duplicated audit trail is cosmetic; a duplicated
`evidence` list fed back into a prompt is a doubled token bill, and a duplicated list of
side effects to perform is an incident.

### The two fixes

**Rename the key.** If the subgraph's field is `sub_log` rather than `log`, nothing is
shared, nothing is passed in, and nothing is double-appended:

```
{'log': ['before', 'after'], 'sub_log': ['inner']}
```

Cleanest when the subgraph's internal state is genuinely its own business.

**Wrap it in a node.** Call the subgraph explicitly and control both directions:

```python
def call_sub(state):
    result = sub.invoke({"log": []})     # fresh input, not the parent's list
    return {"log": result["log"]}        # only what the subgraph produced
```

```
{'log': ['before', 'inner', 'after']}
```

This is more code and it is usually the right answer, because it makes the interface between
the two graphs explicit and greppable.

> **Share a key between a parent and a subgraph only when the field has no reducer.** For
> reducer fields, rename or wrap.

## Different schemas need a wrapper anyway

Passing a compiled graph to `add_node` only works when the schemas overlap. When they do
not — the normal case for a reusable component — the wrapper node is not a workaround, it is
the interface:

```python
def call_sub(state: Outer) -> dict:
    result = inner_graph.invoke({"q": state["question"]})
    return {"reply": result["a"]}
```

```
{'question': 'why', 'reply': 'answer to why'}
```

The wrapper is where translation lives: outer names in, inner names out. It is a plain
function, so it tests without either graph.

## Seeing inside

By default, streaming shows a subgraph as one opaque node. Pass `subgraphs=True` to see
inside:

```python
for chunk in graph.stream(state, stream_mode="updates", subgraphs=True):
    print(chunk)
```

Each chunk becomes `(namespace, update)`. The namespace is `()` for the parent and
`('sub:<uuid>',)` for nodes inside the subgraph — that is how you tell which `inner` you are
looking at when the same subgraph appears twice.

When a subgraph seems to misbehave, turning this on is the first move. It is how the
double-count above becomes visible rather than merely puzzling.

## Persistence

You do not give a subgraph its own checkpointer. Compile it plainly and let the parent's
checkpointer cover the whole tree:

```python
sub = sub_builder.compile()                       # no checkpointer
parent = parent_builder.compile(checkpointer=saver)
```

The parent's checkpoints include subgraph state, under the namespaces above. This is what
makes it possible to interrupt inside a subgraph and resume there — Chapter 15 does exactly
that, and Chapter 11 covers the checkpoint layout.

Passing a checkpointer to a subgraph that is used as a node is a common mistake and produces
confusing double-persistence. The exception is a subgraph you also run standalone, in which
case give it one only in that context.

## When not to use one

Subgraphs cost real clarity: an extra schema, a namespace layer in every trace, and the trap
above. Use one when at least one of these is true:

- The component is **used in more than one place**.
- It is **developed or tested independently**.
- It has **genuinely private state** the parent should not see.
- You want to **interrupt inside it** as a unit.

If none applies, add the nodes to the parent graph. A flat graph of twelve nodes is easier
to reason about than four graphs of three, and `draw_mermaid()` will show you all of it at
once.

## Try it

Reproduce the double-count, then fix it two ways:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

class Sub(TypedDict): log: Annotated[list, operator.add]
sub = (StateGraph(Sub).add_node('inner', lambda s:{'log':['inner']})
       .add_edge(START,'inner').add_edge('inner',END).compile())
class Par(TypedDict): log: Annotated[list, operator.add]
p = (StateGraph(Par).add_node('before', lambda s:{'log':['before']}).add_node('sub', sub)
     .add_node('after', lambda s:{'log':['after']})
     .add_edge(START,'before').add_edge('before','sub').add_edge('sub','after')
     .add_edge('after',END).compile())
print('shared key:', p.invoke({'log': []}))
"
```

Now watch it happen, with `subgraphs=True` — the third chunk is the culprit:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
class Sub(TypedDict): log: Annotated[list, operator.add]
sub = (StateGraph(Sub).add_node('inner', lambda s:{'log':['inner']})
       .add_edge(START,'inner').add_edge('inner',END).compile())
class Par(TypedDict): log: Annotated[list, operator.add]
p = (StateGraph(Par).add_node('before', lambda s:{'log':['before']}).add_node('sub', sub)
     .add_edge(START,'before').add_edge('before','sub').add_edge('sub',END).compile())
for c in p.stream({'log': []}, stream_mode='updates', subgraphs=True): print(c)
"
```

Then apply each fix — rename the subgraph's key to `sub_log`, and separately replace the
subgraph node with a wrapper function — and confirm both give `['before', 'inner', ...]`
exactly once.

## Takeaways

- A compiled graph can be used directly as a node. Shared state keys are passed in and out
  automatically.
- **A shared key with a reducer double-counts**, silently: the subgraph receives the parent's
  accumulated value and returns the whole thing, which the reducer appends again.
- Share keys with a subgraph only when they have **no reducer**. Otherwise rename the field
  or wrap the subgraph in a node.
- A wrapper node is required anyway when schemas differ, and it is the better default — it
  makes the interface explicit and testable.
- Stream with `subgraphs=True` to see inside; chunks become `(namespace, update)`.
- Give the **parent** the checkpointer, not the subgraph. Parent checkpoints cover the whole
  tree.
- Only reach for a subgraph if it is reused, independently tested, genuinely private, or
  interrupted as a unit. Otherwise keep the graph flat.

---

Previous: [Chapter 8 — Loops, limits and termination](08-loops-and-limits.md) ·
Next: [Chapter 10 — The prebuilt agent](10-prebuilt-agent.md)
