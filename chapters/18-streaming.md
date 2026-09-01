# Chapter 18 — Streaming and observing

Streaming is usually introduced as a UI feature — tokens appearing as they are generated.
It is that, but it is also the primary debugging instrument for layer 2: *which nodes ran,
in what order, and what did each produce.* Chapter 16's triage is two stream calls.

## The five modes

`graph.stream(input, stream_mode=...)` takes one mode or a list.

| Mode | Yields | Use for |
|---|---|---|
| `"updates"` | `{node_name: update}` after each node | which nodes ran, and what they returned |
| `"values"` | the whole state after each superstep | how state evolved; real step boundaries |
| `"messages"` | `(token, metadata)` as the model generates | chat UIs |
| `"custom"` | whatever a node writes | progress from inside long nodes |
| `"debug"` | detailed execution events | deep diagnosis |

`updates` and `values` answer different questions, and Chapter 4 measured why: **`updates`
emits one chunk per node, so chunk count is not superstep count.** Use `values` when you
care about rounds, `updates` when you care about nodes.

## Token streaming

`"messages"` yields `(token, metadata)` pairs as the model produces them:

```python
for token, meta in graph.stream(inp, stream_mode="messages"):
    if token.content:
        print(f"[{meta['langgraph_node']}] {token.content!r}")
```

```
[model] 'Looking '
[model] 'that '
[model] 'up.'
[tools] 'Refunds are issued to the original payment method within 5 working days.'
[model] 'Refunds '
[model] 'take '
...
```

**Look at the fourth line.** The `ToolMessage` came through this stream too. A chat UI that
renders every chunk in `messages` mode will print raw tool output to the user as though the
assistant said it.

This is the most common streaming bug in LangGraph applications, and the fix is to filter on
metadata rather than to trust the mode:

```python
for token, meta in graph.stream(inp, stream_mode="messages"):
    if meta["langgraph_node"] == "model" and token.content:
        emit(token.content)
```

`metadata` also carries `langgraph_step` and any `tags` you set, which is how you
distinguish two different model calls in the same graph — a drafter and a critic, say, where
only one should reach the user.

## Several modes at once

Pass a list and each chunk arrives as `(mode, payload)`:

```python
for mode, chunk in graph.stream(inp, stream_mode=["updates", "custom"]):
    print(mode, chunk)
```

```
updates: {'model': {'messages': [AIMessage(content='Looking that up.', ...
updates: {'tools': {'messages': [ToolMessage(content='Refunds are issued ...
updates: {'model': {'messages': [AIMessage(content='Refunds take five ...
```

This is how a real application drives a UI: tokens for the reply, `updates` for a "now
searching the knowledge base" indicator, `custom` for progress inside a slow node.

## Custom progress

A node that takes twenty seconds is a silent gap. `get_stream_writer` lets it report:

```python
from langgraph.config import get_stream_writer

def work(state):
    writer = get_stream_writer()
    writer({"progress": "half"})
    writer({"progress": "done"})
    return {"out": ["x"]}
```

```
{'progress': 'half'}
{'progress': 'done'}
```

The payload is anything JSON-serialisable — you define the protocol. This is the right way
to surface "searching 4 of 12 documents" from inside a fan-out, and it is far better than
inferring progress from node boundaries.

## Async

`astream` is the same API with `async for`, and it is what you want in a web server:

```python
async for chunk in graph.astream(inp, stream_mode="updates"):
    ...
```

There is also `astream_events` for a much finer-grained event feed. It is genuinely useful
for building rich UIs and genuinely verbose; reach for it only when the five modes above are
insufficient.

## Streaming is not tracing

Streaming shows you *this* run, live, in your process. It does not persist, it is not
searchable, and it is gone when the request ends.

For "what happened last Tuesday", you want tracing — that is Chapter 25. The two are
complementary: streaming for development and for the user experience, tracing for
production diagnosis. Neither replaces the other, and a team that has only one of them
notices the gap quickly.

## Getting output out of nodes

A `print()` inside a node works, and for a quick local check it is fine. Two better habits:

**Use a `trail` field.** The book's `TicketState` carries
`trail: Annotated[list[str], operator.add]`, and every node appends its name. The result is
an execution record that survives into the final state, into checkpoints, and into tests:

```python
assert out["trail"] == ["classify", "retrieve", "draft"]
```

That single assertion covers routing, ordering, and reducer behaviour, and it costs one
field. It is the cheapest observability in this book.

**Use logging, not `print`.** A node's `print` in production goes nowhere useful. A logger
with the thread id attached goes somewhere you can search.

## Try it

See the tool-output trap for yourself — the fourth line is the one to notice:

```bash
uv run python -c "
from examples.triage.graph import build_agent
from langchain_core.messages import HumanMessage
inp = {'ticket_id':'T-1001','body':'billing','messages':[HumanMessage('refund?')]}
for token, meta in build_agent().stream(inp, stream_mode='messages'):
    if getattr(token,'content',''):
        print(f\"[{meta['langgraph_node']}] {token.content!r}\")
"
```

Now filter to just the model, which is what a chat UI should do:

```bash
uv run python -c "
from examples.triage.graph import build_agent
from langchain_core.messages import HumanMessage
inp = {'ticket_id':'T-1001','body':'billing','messages':[HumanMessage('refund?')]}
for token, meta in build_agent().stream(inp, stream_mode='messages'):
    if meta['langgraph_node'] == 'model' and getattr(token,'content',''):
        print(token.content, end='')
print()
"
```

Then compare `updates` and `values` on the same run and confirm they answer different
questions.

## Takeaways

- Streaming is a debugging instrument as much as a UI feature. Chapter 16's triage is two
  stream calls.
- `updates` = per node; `values` = per superstep. **Chunk count in `updates` is not step
  count.**
- **`stream_mode="messages"` includes tool output.** Filter on
  `metadata["langgraph_node"]` or your chat UI will show users raw `ToolMessage` content.
- Pass a list of modes to get `(mode, payload)` chunks and drive a whole UI from one stream.
- `get_stream_writer()` reports progress from inside slow nodes; you define the payload.
- `astream` for servers; `astream_events` only when the five modes are not enough.
- Streaming is live and ephemeral — it is not tracing. You need both (Chapter 25).
- A `trail` field with `operator.add` gives you a durable execution record for one line of
  schema, and makes routing testable with a single assertion.

---

Previous: [Chapter 17 — When the graph won't build or run](17-build-and-run-failures.md) ·
Next: [Chapter 19 — When state is wrong](19-state-is-wrong.md)
