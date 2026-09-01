# Chapter 31 — The ecosystem

LangGraph sits in a stack of four things with confusingly adjacent names, maintained by the
same people, that you will see used interchangeably in material that is often out of date.
This chapter is a map, and a method for telling current advice from stale.

## The four layers

**LangChain** — models, tools, and `create_agent`. Provider-agnostic interfaces. Built *on*
LangGraph, so starting here is not a dead end.

**LangGraph** — the runtime this book is about. Explicit control flow, durable state,
human-in-the-loop.

**Deep Agents** — a pre-built harness on top of both, shipping planning, a virtual
filesystem, subagents and memory. Use it when you want those features rather than to design
them.

**LangSmith** — tracing and evaluation. Framework-agnostic; useful whichever of the above you
pick (Chapter 25).

Dependencies point downward, but you use only the layer you need. `create_agent` returns a
LangGraph graph, which is why Chapter 10 could nest one inside a larger graph without
ceremony.

### Which to reach for

- Fixed tools, one loop, finishes in seconds → **LangChain**.
- Control flow you define, durability, or a human in the middle → **LangGraph**.
- You want planning, files and subagents out of the box → **Deep Agents**.
- No model involved at all → **none of them**. Use Celery or Temporal; they have been better
  at deterministic workflows for a decade.

That last line is worth keeping. LangGraph's durability is genuinely good, but it is
durability *for LLM applications*, and a purely deterministic pipeline is better served by a
task queue.

## The staleness problem

This is the practical section, because it will cost you more time than anything else.

These libraries moved through a major version recently, and the internet has not caught up.
Three concrete examples measured while writing this book:

**`create_react_agent` is deprecated.** Almost every tutorial shows
`from langgraph.prebuilt import create_react_agent`. Current code is
`from langchain.agents import create_agent`, with `tools=` as a keyword (Chapter 10).

**The tracing environment variables were renamed.** `LANGCHAIN_TRACING_V2` and friends are
gone; it is `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` (Chapter 25).

**The recursion limit default is not 25.** It is 10007, and the widely-repeated 25 belongs to
a different package (Chapters 8 and 20).

Each of these is stated confidently and incorrectly in a great deal of published material.

### A method

**Check the version first.** `uv run python -c "import langgraph; print(...)"`, and compare
against what the article assumed. An undated LangGraph post is close to unusable.

**Prefer `docs.langchain.com` over blog posts and forum answers.** For an agent, the
`llms.txt` index at `https://docs.langchain.com/llms.txt` lists every page with a
description — fetch that, pick the relevant pages, and read those rather than working from
memory.

**Read the deprecation warnings.** They name the replacement precisely, as Chapter 10's did.
Do not suppress them.

**Verify in a REPL.** This is the theme of the whole book. Every claim here was checked by
running it, because that is the only defence against confident wrong information — including
confident wrong information from a language model.

**Pin with upper bounds.** `langgraph>=1.2,<2` means a major version cannot arrive
unannounced.

## Alternatives

Worth knowing, briefly, so you can tell when LangGraph is the wrong tool.

**Temporal** — durable execution done properly, and better than LangGraph at it: stronger
guarantees, mature operations, decades of workflow thinking. Nothing LLM-specific. If
durability is your dominant requirement and the LLM part is small, seriously consider it.

**Celery / Airflow / Dagster** — task queues and data pipelines. Better for scheduled or
throughput-oriented deterministic work.

**OpenAI Agents SDK, Pydantic AI, and others** — lighter agent frameworks. Less machinery,
less durability, less to learn.

**No framework.** The `while` loop from Chapter 1. Still the right answer for a genuinely
simple agent, and the answer this book has been careful not to talk you out of.

The honest summary: LangGraph's distinctive combination is *durable execution plus
LLM-specific ergonomics plus explicit control flow*. If you need only one of those three,
something else is probably simpler.

## Keeping up

- **The changelog and release notes**, over anything else.
- **Deprecation warnings in your own logs** — the earliest signal that something you use is
  moving.
- **The repository issues** when behaviour surprises you. This book found several behaviours
  worth knowing that are not in the documentation.
- **A pinned, upper-bounded dependency** so upgrades are a decision.

## Try it

Find out what you are actually running, which is the first step of every version question:

```bash
uv run python -c "
import importlib.metadata as md
for p in ['langgraph','langgraph-checkpoint','langgraph-prebuilt','langchain','langchain-core']:
    try: print(f'{p:24} {md.version(p)}')
    except Exception: print(f'{p:24} not installed')
"
```

Then make a deprecation warning appear, so you recognise the shape of one:

```bash
uv run python -c "from langgraph.prebuilt import create_react_agent" 2>&1 | tail -2
```

## Takeaways

- Four layers: **LangChain** (framework), **LangGraph** (runtime), **Deep Agents** (harness),
  **LangSmith** (observability). Each builds on the one below, and you use only what you need.
- If no model is involved, use a task queue instead — Celery and Temporal are better at
  deterministic workflows.
- **Published material is frequently out of date.** Verified examples: `create_react_agent`
  is deprecated, `LANGCHAIN_TRACING_V2` was renamed to `LANGSMITH_TRACING`, and the recursion
  limit default is 10007 rather than the widely-repeated 25.
- Method: check your installed version, prefer `docs.langchain.com` (and `llms.txt` for
  agents), read deprecation warnings, **verify in a REPL**, and pin with upper bounds.
- Temporal is better at pure durable execution; lighter SDKs are better when you need less;
  no framework at all is still right for a simple agent.
- LangGraph's distinctive combination is durable execution + LLM ergonomics + explicit control
  flow. Needing only one of the three suggests a simpler tool.

---

Previous: [Chapter 30 — The Functional API](30-functional-api.md) ·
Next: [Chapter 32 — Anti-patterns](32-anti-patterns.md)
