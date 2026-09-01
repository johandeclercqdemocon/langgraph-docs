# Chapter 16 — The debugging mindset

LangGraph failures are confusing for a specific reason: the thing that went wrong and the
place you notice it are usually in different layers. A wrong final answer can be a prompt
problem, a routing problem, a reducer problem, or a stale checkpoint — and the symptom looks
identical in all four cases.

The cure is to stop guessing and identify the layer first.

## Five layers

Work down this list. Each has a different diagnostic and a different chapter.

| # | Layer | Question | Chapter |
|---|---|---|---|
| 1 | **Structure** | Does the graph have the shape you think? | 17 |
| 2 | **Execution** | Did the nodes you expect run, in the order you expect? | 18 |
| 3 | **State** | Does state hold what you expect after each step? | 19 |
| 4 | **Model** | Given that state, is the model doing something sensible? | 27, 29 |
| 5 | **Environment** | Right versions, keys, checkpointer, deploy? | 26, 31 |

Most people start at layer 4 because that is where the interesting failure feels like it
should be. In practice **layers 1 to 3 account for the large majority of LangGraph-specific
bugs**, and they are far cheaper to check. Checking them takes about a minute.

## The one-minute triage

Before forming any theory, run these three commands.

**1. Draw it.**

```python
print(graph.get_graph().draw_mermaid())
```

You are looking for edges you did not intend — the leftover `add_edge` next to a
`Command(goto=...)` from Chapter 6, or a missing dotted branch because
`add_conditional_edges` had no destination list. A surprising number of bugs are visible
here and nowhere else.

**2. Watch it run.**

```python
for chunk in graph.stream(input, stream_mode="updates"):
    print(chunk)
```

Which nodes ran? In what order? Did one run twice (Chapter 7's unequal branches)? Did the
one you care about run at all?

**3. Read the state at each step.**

```python
for chunk in graph.stream(input, stream_mode="values"):
    print(chunk)
```

Where does the state first differ from what you expected? That step is your bug, and
everything after it is a consequence.

Three commands narrow the search from "somewhere in my agent" to a single node in most
cases.

## Reading a stack trace

A node's exception passes through the executor, which makes traces longer than you would
like:

```
File ".../langgraph/pregel/main.py", line 3913, in invoke
File ".../langgraph/pregel/main.py", line 2967, in stream
File ".../langgraph/pregel/_runner.py", line 207, in tick
File ".../langgraph/pregel/_retry.py", line 617, in run_with_retry
File ".../langgraph/_internal/_runnable.py", line 707, in invoke
File ".../langgraph/_internal/_runnable.py", line 447, in invoke
File "<stdin>", line 6, in boom
ZeroDivisionError: division by zero
During task with name 'boom' and id '4c03e5f8-8ed2-dccd-47ef-7ca4d158c4f0'
```

Two lines matter, and neither is in the middle.

**The last frame in your own file** — `line 6, in boom` — is the actual error site.
Everything above it is `pregel` plumbing and can be skipped entirely.

**The final line** — `During task with name 'boom'` — names the node. LangGraph appends this
deliberately, and it is the fastest way to locate a failure in a graph with many nodes. When
someone pastes you a LangGraph traceback, read the bottom two lines first.

## Errors that carry documentation

LangGraph's own exceptions include a URL:

```
InvalidUpdateError: At key 'out': Can receive only one value per step.
Use an Annotated key to handle multiple values.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/INVALID_CONCURRENT_GRAPH_UPDATE
```

The error name in that URL — `INVALID_CONCURRENT_GRAPH_UPDATE` — is more specific than the
exception class, which is shared by several unrelated problems. Search for the URL slug, not
the class name.

## The silent failures

Three LangGraph behaviours produce **no error at all**, which makes them the most expensive
to debug. Each was measured earlier in this book:

- **A returned state key that is not in the schema is dropped** (Chapter 2). No warning. A
  node appears to do nothing.
- **A router typo with no destination list logs to stderr and skips the node** (Chapter 6).
  The run succeeds.
- **A subgraph sharing a reducer key double-counts** (Chapter 9). The output is simply wrong.

If a node "isn't doing anything" and there is no exception, check these three before
anything else. They are not rare.

## Bisecting

When the triage does not localise it, shrink the problem:

**Cut the graph down.** Replace suspect nodes with `lambda s: {"field": "known value"}` until
the bug disappears. The last node you stubbed is implicated.

**Take the model out.** Replace it with a `ScriptedModel` (as this book does throughout). If
the bug persists with fixed replies, it is not a prompt problem — you have just eliminated
layer 4 and made the failure reproducible for free.

**Call nodes directly.** A node is a function (Chapter 5):

```python
print(classify({"body": "I want a refund"}))
```

No graph, no checkpointer, no framework. If it misbehaves here, nothing above matters.

**Use time travel.** With a checkpointer you can find the exact step where state went wrong
(Chapter 12) instead of re-running from the top with print statements.

## Reproduce before you fix

Two things make LangGraph bugs hard to reproduce, and both are avoidable.

**The model.** Non-determinism means "it happened once" is not a bug report. Capture the
messages that produced it and replay them against a scripted model.

**The checkpoint.** A bug on a thread with history is not reproducible from a fresh input,
because the state is not fresh. Conversely, a bug that appears only on the *first* run
vanishes on the second. Always note whether you are testing a new thread or a resumed one —
"works on my machine" is frequently "works on my empty checkpointer".

## Try it

Get familiar with a trace before you need to read one at speed:

```bash
uv run python -c "
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
class S(TypedDict): x: int
g = (StateGraph(S).add_node('boom', lambda s: 1/0)
     .add_edge(START,'boom').add_edge('boom',END).compile())
g.invoke({'x': 1})
" 2>&1 | tail -4
```

Read the bottom two lines: your file, then the node name.

Now run the one-minute triage on a graph you did not write:

```bash
uv run python -c "
from examples.triage.graph import build_routed
g = build_routed()
print(g.get_graph().draw_mermaid())
for c in g.stream({'ticket_id':'T-1','body':'billing refund'}, stream_mode='updates'): print(c)
"
```

## Takeaways

- Identify the **layer** before forming a theory: structure, execution, state, model,
  environment. Layers 1–3 hold most LangGraph-specific bugs and cost a minute to check.
- The one-minute triage is `draw_mermaid()`, then `stream_mode="updates"`, then
  `stream_mode="values"`. The first step where state differs from expectation is the bug.
- In a traceback, read the **bottom two lines**: the last frame in your own file, and
  `During task with name '<node>'`. Skip the `pregel` frames.
- LangGraph errors carry a documentation URL whose slug is more specific than the exception
  class — search the slug.
- **Three failures are completely silent**: a dropped unknown state key, a router typo with
  no destination list, and a double-counting subgraph. Check these when there is no exception.
- Bisect by stubbing nodes, replacing the model with a scripted one, and calling nodes
  directly as plain functions.
- Before fixing, reproduce — which means pinning the model *and* knowing whether the thread
  was fresh or resumed.

---

Previous: [Chapter 15 — Human in the loop](15-human-in-the-loop.md) ·
Next: [Chapter 17 — When the graph won't build or run](17-build-and-run-failures.md)
