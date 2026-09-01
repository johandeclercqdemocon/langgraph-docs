# Chapter 1 — Why LangGraph

You can build an agent with a `while` loop. Many production agents are exactly that, and
some of them should stay that way. This chapter is about the point where that stops being
true, because adopting a framework before you have the problem it solves is how projects
acquire complexity they never needed.

## The loop everyone writes first

Strip an agent to its essentials and it is this:

```python
messages = [system_prompt, user_message]
while True:
    reply = model.invoke(messages)
    messages.append(reply)
    if not reply.tool_calls:
        break
    for call in reply.tool_calls:
        messages.append(run_tool(call))
return reply.content
```

Twelve lines, no dependencies beyond a model client. It genuinely works. If your agent is
one model, a handful of tools, and a request that finishes in a few seconds, **stop here**.
You do not need this book yet, and Chapter 31 will tell you the same thing at the end of it.

The loop starts to hurt when the requirements arrive that always arrive.

## What actually breaks

**"It should ask a human before doing that."** Now you need to stop mid-loop, return to a
web request, and come back — possibly minutes later, possibly in a different process. Your
`while` loop lives on a call stack, and a call stack cannot be paused, serialised, and
resumed tomorrow. This is the requirement that most often ends the hand-written loop, and
it ends it abruptly.

**"It crashed on step nine of twelve; don't redo the first eight."** The eight succeeded.
Two called paid APIs. One sent an email. Retrying from scratch is wrong — it is expensive
at best and duplicates the email at worst. To resume, something must have recorded what
step nine even was.

**"Run those five checks at once."** Trivial with `asyncio.gather`, until each branch wants
to write results into shared state and you have to decide what happens when two branches
write the same key in the same instant.

**"Why did it do that?"** Somebody asks about a run from last Tuesday. You have logs. You
do not have the state the agent held at each step, and you cannot re-run it from just
before the bad decision to test a fix.

Each of these is solvable by hand. The trap is that the solutions are the same four
solutions every team writes, they are subtle, and they interact. You end up maintaining a
worse version of a workflow engine as a side effect of shipping an agent.

## What LangGraph actually is

LangGraph is that workflow engine, specialised for LLM applications. You describe your
application as a **graph**: nodes that do work, edges that decide what runs next, and a
shared **state** object that nodes read from and write to.

That description sounds like a mild reorganisation of the `while` loop. It is not, and the
reason is the single most important idea in this book:

> **Because the structure is data rather than a call stack, the runtime can do things to it
> that it cannot do to your code.**

A call stack can only run. A graph can be paused between any two nodes, its state written
to a database, resumed in a different process an hour later, rewound to an earlier point,
forked into an alternative history, streamed as it executes, and drawn as a diagram. You do
not implement any of that. You get it because you gave up direct control of the control
flow.

That is the trade, stated honestly: **you write your logic in a more constrained form, and
in exchange the runtime can suspend, persist, resume, and inspect it.** If you do not need
those capabilities, the constraint is pure cost.

## The vocabulary, once

Five terms carry the whole book. Appendix B has the rest.

| Term | What it is |
|---|---|
| **State** | A dict, shared by every node. The only thing nodes use to communicate. |
| **Node** | A function. Takes the state, returns a dict of changes to it. |
| **Edge** | A rule for what runs next. Fixed, or decided at runtime. |
| **Graph** | Nodes plus edges. Built with `StateGraph`, then `.compile()`d to run. |
| **Checkpointer** | Saves state after every step. Everything durable depends on it. |

Note what is absent: there is no "agent" primitive at this layer, and no requirement that
any node call a model at all. A LangGraph node is an ordinary function. Several graphs in
this book never call an LLM, which is why they run for free.

## Where it sits

LangGraph is the middle of three layers from the same maintainers, and picking the wrong
one costs you weeks.

**LangChain** (`create_agent`) is the tool-calling loop above, packaged, with a
provider-agnostic model interface. Reach for it for a single-purpose agent with a fixed set
of tools. It is *built on* LangGraph, so choosing it is not a dead end — you can drop down
later.

**LangGraph** is the runtime: explicit control flow, durable state, human-in-the-loop.
Reach for it when the shape of the work is the hard part.

**Deep Agents** is a pre-built harness on top of both, shipping planning, a virtual
filesystem, subagents, and memory. Reach for it when you want those specific features and
not to design them.

The honest decision rule:

- Fixed tools, one loop, finishes in seconds → **LangChain**.
- You need control flow *you* define, or durability, or a human in the middle → **LangGraph**.
- You want planning, files, and subagents out of the box → **Deep Agents**.
- Your workflow is fully deterministic with no model in it → **none of the above**. Use a
  task queue. Celery and Temporal are better at this and have been for a decade.

## What it costs

Not free, and the costs are unevenly distributed.

**A real learning curve, front-loaded.** Reducers, supersteps and channels (Chapters 3 and
4) are genuinely unfamiliar. Most early LangGraph bugs are one of about five state
misunderstandings, which is why Chapter 19 is devoted to them.

**Indirection when debugging.** A stack trace from inside a node passes through the Pregel
executor. Chapter 16 is about reading these.

**A moving API.** This is a fast-moving library and advice online goes stale quickly. This
book states its exact versions for that reason, and Chapter 31 tells you how to tell a
current answer from an obsolete one.

**Not much runtime overhead.** Measured in Chapter 27: the framework's own cost per step is
in the low milliseconds, against LLM calls that take hundreds. If your agent is slow,
LangGraph is almost certainly not why.

## The example this book builds

Every chapter uses one application: `triage`, which handles an inbound support ticket. It
classifies it, looks up a knowledge-base article, drafts a reply, and escalates anything it
is unsure about to a human.

It is deliberately small enough to hold in your head and large enough to need everything —
branching, a tool loop, parallel work, persistence, and an approval step.

**Its model is fake.** `ScriptedModel` replays a fixed list of replies, so every output
printed in this book is reproducible, runs offline, and costs nothing. The tool calls are
real tool calls, so the machinery is exercised exactly as a real model would exercise it.
Two chapters use a real model, and say so before they do.

## Try it

You need Python 3.11+ and [`uv`](https://docs.astral.sh/uv/). From the repository root:

```bash
uv run python scripts/verify.py
```

```
[PASS] Python >= 3.11  found 3.13.12
[PASS] langgraph >= 1.2  found 1.2.11
[PASS] langchain-core >= 1.0  found 1.6.1
[PASS] build and run a graph
[PASS] state persists across runs  log=['x', 'x']
[PASS] the triage example runs

All 6 checks passed. You are ready for Chapter 1.
```

If any line says `FAIL`, fix that before going on — the rest of the book assumes a working
environment. No API key is needed, now or in almost every chapter that follows.

Then watch the finished application run in all four of the shapes this book builds it in:

```bash
uv run python -m examples.triage
```

You are not expected to understand the output yet. Chapter 2 builds the first shape from
nothing.

## Takeaways

- A hand-written `while` loop is a legitimate agent. Use one until a requirement breaks it.
- The requirements that break it are always the same four: pause for a human, resume after
  a crash, run branches in parallel, and explain a past run.
- LangGraph's central trade is that **structure becomes data**. Constrain how you express
  control flow, and the runtime gains the ability to suspend, persist, rewind and inspect it.
- Five terms carry everything: state, node, edge, graph, checkpointer. A node is just a
  function; nothing requires it to call a model.
- Pick the layer deliberately: LangChain for a fixed tool loop, LangGraph for control flow
  and durability, Deep Agents for a ready-made harness, a task queue if no model is involved.
- The main cost is a front-loaded conceptual learning curve, not runtime overhead.

---

Next: [Chapter 2 — Your first graph](02-first-graph.md)
