# LangGraph: From First Graph to Production

A working book on LangGraph — what the execution model actually does, how to build graphs
that survive contact with production, how to debug them when they misbehave, and when not to
use it at all.

Written against **LangGraph 1.2.11** / **langchain-core 1.6.1**, on Python 3.12 and 3.13.
Every version this book was verified against is listed in [Versions](#versions) below.

Its companion is [LangChain: From First Call to Production][lc], which covers the layer
above: models, prompts, tools, retrieval and `create_agent`. That book's Chapter 31 ends
where this one begins.

[lc]: https://github.com/johandeclercqdemocon/langchain-docs

## Who this is for

Someone who can write Python and now has to build an LLM application that does more than one
model call. **You do not need to have used LangChain, or any agent framework.** Chapters 1
and 2 assume nothing; the vocabulary is introduced before it is used, and every term has an
entry in [Appendix B](appendices/b-glossary.md).

If you already ship LangGraph, Parts IV and V are the ones worth your time.

## Before you begin

You need Python 3.11+ and [`uv`](https://docs.astral.sh/uv/). **You do not need an API key.**

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

That installs everything on first run. If a line says `FAIL`, fix it before continuing — the
rest of the book assumes a working environment.

Then watch the finished example run in all four shapes the book builds it in:

```bash
uv run python -m examples.triage
```

And run the test suite, which is also Chapter 24's worked example:

```bash
uv run --extra dev pytest -q
```

## The approach

**Every output printed in this book was produced by running the code.** Where a result
contradicted what I expected, or contradicted common advice, the chapter says so and shows
the output. Three examples that turned up this way:

- The default `recursion_limit` is **10007**, not the widely-repeated 25 — so a runaway agent
  loop is ten thousand model calls, not twenty-five. (Ch 8, 20)
- A subgraph sharing a reducer key with its parent **silently double-counts**. (Ch 9)
- Pydantic state validates your *input* but **not what nodes write** — a node can violate its
  own field constraints without error. (Ch 23)

Chapters end with **Try it** (runnable, offline, free) and **Takeaways**.

## The running example

`triage` — a support-ticket agent that classifies a ticket, retrieves an article, drafts a
reply, and escalates what it is unsure about. It grows across the book: a linear graph, then
routing, then a tool loop, then a human approval step.

**Its model is fake, on purpose.** `ScriptedModel` replays fixed replies, so every output
here is reproducible, runs offline, and costs nothing — while the tool calls are real tool
calls, so the machinery is exercised exactly as a real model would exercise it. Swapping in a
real model is one line, and the book says so where it matters.

Code lives in [`examples/triage/`](examples/triage/).

---

## Contents

### Part I — Foundations

| # | Chapter | What it covers |
|---|---------|----------------|
| 1 | [Why LangGraph](chapters/01-why-langgraph.md) | The four requirements that break a `while` loop, and when not to adopt it |
| 2 | [Your first graph](chapters/02-first-graph.md) | State, nodes, edges, compile — and the errors you'll hit this week |
| 3 | [State and reducers](chapters/03-state-and-reducers.md) | Why a write replaces, and how to make it append |
| 4 | [The execution model](chapters/04-execution-model.md) | Supersteps, channels, and why nodes see stale data |

### Part II — Building graphs

| # | Chapter | What it covers |
|---|---------|----------------|
| 5 | [Nodes](chapters/05-nodes.md) | Three signatures, and why context is not state |
| 6 | [Edges and routing](chapters/06-edges-and-routing.md) | Static, conditional, `Command` — and the trap in each |
| 7 | [Parallelism and `Send`](chapters/07-parallelism-and-send.md) | Fan-out, map-reduce, and the join that runs twice |
| 8 | [Loops, limits and termination](chapters/08-loops-and-limits.md) | Cycles, and the 10007 nobody mentions |
| 9 | [Subgraphs](chapters/09-subgraphs.md) | Composition, and the silent double-count |
| 10 | [The prebuilt agent](chapters/10-prebuilt-agent.md) | `create_agent`, what it builds, and when to leave it |

### Part III — State that survives

| # | Chapter | What it covers |
|---|---------|----------------|
| 11 | [Checkpointers and threads](chapters/11-checkpointers-and-threads.md) | Persistence, thread isolation, and reading a snapshot |
| 12 | [Time travel](chapters/12-time-travel.md) | History, forking, and where the fork actually lands |
| 13 | [Store: memory across threads](chapters/13-store.md) | Long-term memory, namespaces, and what not to remember |
| 14 | [Durability and resumption](chapters/14-durability-and-resumption.md) | Crash recovery across processes, and idempotency |
| 15 | [Human in the loop](chapters/15-human-in-the-loop.md) | `interrupt`, resume, and the node that runs twice |

### Part IV — Debugging

| # | Chapter | What it covers |
|---|---------|----------------|
| 16 | [The debugging mindset](chapters/16-debugging-mindset.md) | Five layers, a one-minute triage, and the silent failures |
| 17 | [When the graph won't build or run](chapters/17-build-and-run-failures.md) | Every error message, and the ones that don't appear |
| 18 | [Streaming and observing](chapters/18-streaming.md) | Five modes, and why your chat UI shows tool output |
| 19 | [When state is wrong](chapters/19-state-is-wrong.md) | Six causes, and what mutation really costs |
| 20 | [Runaway loops and cost](chapters/20-runaway-loops-and-cost.md) | Three layers of defence against a large invoice |
| 21 | [Errors, retries and caching](chapters/21-errors-retries-caching.md) | Four kinds of error, four responses |
| 22 | [Cookbook: symptom → cause → fix](chapters/22-cookbook.md) | Indexed by what you actually see |

### Part V — Production

| # | Chapter | What it covers |
|---|---------|----------------|
| 23 | [Structuring a real project](chapters/23-project-structure.md) | Layout, checkpointer lifetime, and what Pydantic does not do |
| 24 | [Testing graphs](chapters/24-testing.md) | Four layers, 19 tests, 0.48s, no API key |
| 25 | [Observability](chapters/25-observability.md) | Tracing, what to record in state, what to alert on |
| 26 | [Deployment](chapters/26-deployment.md) | The API server, and the deploy hazard nobody mentions |
| 27 | [Performance and cost](chapters/27-performance-and-cost.md) | Measured overhead, and where the money actually goes |
| 28 | [Security and multi-tenancy](chapters/28-security-and-multi-tenancy.md) | Injection, tenant isolation, and retention |

### Part VI — Beyond the basics

| # | Chapter | What it covers |
|---|---------|----------------|
| 29 | [Patterns](chapters/29-patterns.md) | Six shapes, ordered by cost — take the first match |
| 30 | [The Functional API](chapters/30-functional-api.md) | Durability without a graph |
| 31 | [The ecosystem](chapters/31-ecosystem.md) | The four layers, and how to spot stale advice |
| 32 | [Anti-patterns](chapters/32-anti-patterns.md) | The catalogue, with a review checklist |

### Appendices

- [A — API cheatsheet](appendices/a-cheatsheet.md) — everything in one page
- [B — Glossary](appendices/b-glossary.md)
- [C — Further reading](appendices/c-further-reading.md)

---

## Suggested paths

**New to LangGraph** — Chapters 1–4 in order, without skipping 3 and 4. They are the
conceptual core, and most later confusion traces back to them. Then 5–10, then dip into Part
IV as things break.

**Already shipping** — Chapter 4, then Part IV (16–22), then 26 and 28. Chapter 22 is a
reference; bookmark it.

**Evaluating whether to adopt** — Chapters 1, 29 and 31.

## Conventions

Commands you can run:

```bash
uv run python scripts/verify.py
```

Real output, shown when it is the point:

```
no reducer : {'log': ['B']}
operator.add: {'log': ['A', 'B']}
```

Blockquotes mark rules worth remembering:

> A node does not write a value into state. It **submits an update**, and the field's
> reducer decides what that update means.

Anything that costs money says so before you run it. Almost nothing does.

## Versions

| Package | Version |
|---|---|
| langgraph | 1.2.11 |
| langgraph-checkpoint | 4.2.0 |
| langgraph-checkpoint-sqlite | 3.1.1 |
| langgraph-prebuilt | 1.1.0 |
| langchain | 1.3.18 |
| langchain-core | 1.6.1 |
| langgraph-cli | 0.4.31 |
| Python | 3.12 and 3.13 |

This library moves quickly. [Chapter 31](chapters/31-ecosystem.md) covers telling current
advice from stale, which is a real and recurring problem.

## Licence

MIT. See [LICENSE](LICENSE).
