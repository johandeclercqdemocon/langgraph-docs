# `triage` — the running example

A support-ticket triage agent. It classifies an inbound ticket, retrieves a
knowledge-base article, drafts a reply, and hands anything it is unsure about to
a human.

It grows across the book:

| Builder | Chapter | Shape |
|---|---|---|
| `build_linear()` | 2 | Two nodes, one edge |
| `build_routed()` | 6 | A conditional edge chooses retrieve or escalate |
| `build_agent()` | 10 | A model/tool loop that runs until the model stops calling tools |
| `build_hitl()` | 15 | The same graph, pausing at `review` for a human |

## Why the model is fake

`fakes.py` defines `ScriptedModel`, which replays a fixed list of replies. That
is deliberate: every output printed in this book was produced by running the
code, and a real model would give a different answer each time, cost money, and
make the chapters unverifiable.

The tool calls are real `AIMessage` tool calls, so `ToolNode` and the prebuilt
agent drive it exactly as they drive a real model. To use a real one:

```python
from langchain.chat_models import init_chat_model
model = init_chat_model("claude-sonnet-5").bind_tools(ALL_TOOLS)
```

That change bills your API account. Nothing else in this book does.

## Running it

```bash
uv run python -m examples.triage
```
