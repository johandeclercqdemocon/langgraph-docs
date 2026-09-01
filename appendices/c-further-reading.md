# Appendix C — Further reading

## Official documentation

**[docs.langchain.com](https://docs.langchain.com)** — the only source worth trusting by
default, because it tracks the current version. The LangGraph tree is at
`/oss/python/langgraph/overview` (swap `python` for `javascript` for TypeScript).

**[docs.langchain.com/llms.txt](https://docs.langchain.com/llms.txt)** — an index of every
page with a description. If you are asking an AI assistant about LangGraph, point it here
first; it is the difference between a current answer and a 2024 one.

**The error-code pages.** LangGraph exceptions carry a URL, and the slug
(`INVALID_CONCURRENT_GRAPH_UPDATE`, `GRAPH_RECURSION_LIMIT`) is more specific than the
exception class. Search the slug.

**The repository** — [`langchain-ai/langgraph`](https://github.com/langchain-ai/langgraph).
Read the changelog before upgrading. Several behaviours measured in this book are clearer in
the source than in the prose documentation; `langgraph/_internal/_config.py` is where the
10007 default lives.

## On the ideas underneath

**Pregel** (Malewicz et al., 2010) — the paper LangGraph's execution model is named for. Worth
skimming if supersteps feel arbitrary; they are not, and the original context makes the
design obvious. → Ch 4

**Temporal's documentation on durable execution** — the clearest writing anywhere on
at-least-once semantics, idempotency, and why replay works the way it does. Useful even if you
never use Temporal, because Chapter 14's constraints are the general ones. → Ch 14

**The Twelve-Factor App**, factor III (config) — the discipline behind Chapter 23's split of
environment, context, and state.

## Adjacent tools

**[Temporal](https://temporal.io)** — durable execution done properly, with nothing
LLM-specific. If durability dominates your requirements and the model is a small part,
compare seriously.

**[LangSmith](https://docs.langchain.com/langsmith/home)** — tracing and evaluation.
Framework-agnostic. → Ch 25

**Deep Agents** — `/oss/python/deepagents/overview`. The pre-built harness above LangGraph:
planning, virtual filesystem, subagents, memory. → Ch 31

**OpenAI Agents SDK, Pydantic AI** — lighter agent frameworks. Worth knowing so you can tell
when LangGraph is more machinery than you need.

## On the problem, not the framework

**Anthropic, "Building effective agents"** — the best short argument for using the simplest
thing that works, and against reaching for multi-agent architectures early. Chapter 29's
ordering agrees with it.

**Simon Willison's writing on prompt injection** — the clearest available explanation of why
prompt-level defences do not work, and why Chapter 28 insists on structural controls.

**Anything on evaluation.** The gap between "my agent works" and "my agent works on the
inputs I have not tried" is where most production disappointment lives, and it is a
measurement problem rather than a framework problem. Chapter 24 deliberately scoped it out;
do not leave it there.

## How to read anything about LangGraph

Restating Chapter 31, because it is the most useful habit in this appendix:

1. **Find the version** the material assumes. Undated LangGraph writing is close to unusable.
2. **Check it against yours** — `importlib.metadata.version("langgraph")`.
3. **Prefer the docs** over blog posts and forum answers.
4. **Run it.** Every claim in this book was checked by running it, which is the only defence
   against confident wrong information — from a blog, from an answer, or from a model.

Three examples measured while writing this book, each contradicting widely-published advice:
`create_react_agent` is deprecated in favour of `langchain.agents.create_agent`; the tracing
variables are `LANGSMITH_*` and not `LANGCHAIN_*`; and the default recursion limit is 10007,
not 25.

---

Previous: [Appendix B — Glossary](b-glossary.md) ·
Back to the [table of contents](../README.md)
