# Chapter 8 — Loops, limits and termination

A cycle in a LangGraph graph is just an edge pointing backwards. Nothing marks it as
special, and nothing stops it from running forever except a condition you wrote and a
ceiling you probably have not thought about.

This chapter is about that ceiling, because its default is not what almost every tutorial
says it is, and the difference is measured in money.

## Writing a loop

The agent loop from Chapter 1, as a graph:

```python
.add_edge(START, "model")
.add_conditional_edges("model", should_continue, ["tools", END])
.add_edge("tools", "model")            # the cycle
```

`tools` goes back to `model`, and `should_continue` decides each time round whether to go
again. Every loop has these two pieces: **an edge back, and a conditional edge out.**

Omit the way out and it never terminates:

```python
.add_edge("a", "b")
.add_edge("b", "a")     # no exit
```

This compiles. LangGraph does not analyse reachability, so a graph with no path to `END` is
a perfectly valid graph as far as compilation is concerned.

## The recursion limit

The safety net is `recursion_limit` — a cap on **supersteps**, not on nodes and not on stack
depth despite the name. Exceed it and you get:

```
GraphRecursionError: Recursion limit of 25 reached without hitting a stop condition.
You can increase the limit by setting the `recursion_limit` config key.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
```

Set it in the run config:

```python
graph.invoke(state, {"recursion_limit": 25})
```

## The default is 10007, not 25

Here is the part worth checking rather than believing.

The number 25 is everywhere in LangGraph tutorials, blog posts and answers. It is
`langchain_core`'s `DEFAULT_RECURSION_LIMIT`, and it is genuinely 25:

```python
from langchain_core.runnables.config import DEFAULT_RECURSION_LIMIT
# 25
```

But LangGraph does not use it when you invoke a graph without a config. It has its own:

```python
from langgraph._internal._config import DEFAULT_RECURSION_LIMIT
# 10007
```

Measured, with a loop that never terminates and no config passed:

```
GraphRecursionError: Recursion limit of 10007 reached without hitting a stop condition.
```

**10007 supersteps before anything stops it.** For a graph of pure functions that is a
wasted second. For an agent loop calling a model each time round, it is roughly ten thousand
API calls — which at a cent each is a hundred dollars, from one request, before any alarm
fires.

You can confirm the ceiling on your own install:

```bash
uv run python -c "from langgraph._internal._config import DEFAULT_RECURSION_LIMIT as D; print(D)"
```

It is overridable by environment variable — `LANGGRAPH_DEFAULT_RECURSION_LIMIT` — which is a
reasonable belt-and-braces measure for a whole deployment.

> **Set `recursion_limit` explicitly on every invocation of a graph containing a cycle.**
> The default is not a safety net at any price you want to pay.

A sensible value is roughly twice the number of supersteps you expect at the worst. An agent
allowed eight tool calls needs about 20; give it 25 and it fails fast when something goes
wrong. Note that this is exactly the number the folklore recommends — the advice is right,
it is the claim that you get it for free that is wrong.

## Bounding the loop yourself

The recursion limit is a crash barrier, not a control. It fails the whole run with an
exception and discards the work. Usually you want the loop to *notice* it has gone too far
and finish gracefully.

Count in state and check it in the router:

```python
class State(TypedDict):
    steps: Annotated[int, operator.add]

def call_model(state):
    return {"messages": [model.invoke(state["messages"])], "steps": 1}

def should_continue(state) -> Literal["tools", "__end__"]:
    if state["steps"] >= 8:
        return END                      # give up cleanly
    return "tools" if state["messages"][-1].tool_calls else END
```

Now the run completes, the state is intact and checkpointed, and you can inspect what
happened. The difference matters in production: a `GraphRecursionError` loses everything,
whereas a graceful stop leaves you a partial answer and a state you can resume from.

Better still, make the exit visible in the output so a stuck agent is detectable rather than
merely slow:

```python
def should_continue(state):
    if state["steps"] >= 8:
        return "give_up"     # a node that sets an explicit "hit the step limit" flag
```

## Why agents loop forever

The recursion limit fires; the interesting question is what caused it. In practice it is
nearly always one of four things.

**The tool result does not answer the question.** The model calls `search_kb`, gets
`"No matching article."`, and tries again with a slightly different query, indefinitely.
The fix is a better tool result — one that says *stop*, not merely *nothing found*.

**The exit condition never becomes true.** `should_continue` checks
`state["messages"][-1].tool_calls`, but a node appended something after the model's reply,
so `[-1]` is no longer the message you meant. Chapter 19 covers this class in detail.

**A `Command(goto=...)` cycle with a static edge still attached.** Chapter 6's trap: both
edges fire, and one of them goes backwards.

**The state the condition reads never changes.** A counter without `operator.add` is
overwritten with `1` every iteration rather than accumulating — Chapter 3's default-reducer
behaviour, in its most expensive form.

That last one deserves emphasis because it looks correct:

```python
class State(TypedDict):
    steps: int              # no reducer

def call_model(state):
    return {"steps": state["steps"] + 1}    # reads, adds, writes: fine here
```

This version works, because the node reads the current value. But the moment two nodes both
increment, or a branch runs in parallel, read-modify-write loses updates. Prefer
`Annotated[int, operator.add]` and return the *delta*:

```python
    return {"steps": 1}     # the reducer does the addition
```

## Loops that are not agent loops

Cycles are not only for tool calling. Two other shapes are worth naming:

**Retry with feedback.** Generate, validate, and on failure loop back with the validation
error added to state. Bound it — three attempts, not "until valid".

**Reflection.** Generate, critique, revise. The exit condition is a quality judgement, which
means it is a model call, which means it can be wrong in the direction of never being
satisfied. Always pair it with a hard iteration cap. Chapter 29 builds both patterns.

## Try it

Find your installed default, then watch it actually stop a runaway loop. This takes a few
seconds and burns 10007 supersteps of pure Python:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph._internal._config import DEFAULT_RECURSION_LIMIT
print('installed default:', DEFAULT_RECURSION_LIMIT)

class L(TypedDict): n: Annotated[int, operator.add]
g = (StateGraph(L).add_node('bump', lambda s: {'n': 1}).add_edge(START,'bump')
     .add_conditional_edges('bump', lambda s: 'bump', ['bump', END]).compile())
try: g.invoke({'n': 0})
except Exception as e: print(type(e).__name__+':', str(e).splitlines()[0])
"
```

Now imagine `bump` calling a model, and set a limit you would actually be willing to pay
for:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
class L(TypedDict): n: Annotated[int, operator.add]
g = (StateGraph(L).add_node('bump', lambda s: {'n': 1}).add_edge(START,'bump')
     .add_conditional_edges('bump', lambda s: 'bump', ['bump', END]).compile())
try: g.invoke({'n': 0}, {'recursion_limit': 10})
except Exception as e: print(type(e).__name__+':', str(e).splitlines()[0])
"
```

Then replace the always-`'bump'` router with one that returns `END` at `n >= 5`, and confirm
it finishes with `{'n': 5}` instead of raising.

## Takeaways

- A cycle is an edge pointing backwards. Every loop needs **an edge back and a conditional
  edge out**; a graph with no path to `END` still compiles.
- `recursion_limit` caps **supersteps**, not stack depth.
- **The default is 10007, not the widely-repeated 25.** The 25 belongs to `langchain_core`
  and does not apply when you invoke a graph without a config. Verify with
  `langgraph._internal._config.DEFAULT_RECURSION_LIMIT`.
- Ten thousand supersteps of an agent loop is roughly ten thousand model calls. **Set
  `recursion_limit` explicitly on any graph with a cycle** — about twice your expected worst
  case.
- The limit is a crash barrier that discards the run. Prefer a counter in state and a
  graceful exit, which leaves a resumable checkpoint and a partial answer.
- Count with `Annotated[int, operator.add]` and return the delta; read-modify-write loses
  updates under parallelism.
- Runaway loops are usually: an unhelpful tool result, an exit condition reading the wrong
  message, a `Command` cycle with a leftover static edge, or a counter with no reducer.

---

Previous: [Chapter 7 — Parallelism and `Send`](07-parallelism-and-send.md) ·
Next: [Chapter 9 — Subgraphs](09-subgraphs.md)
