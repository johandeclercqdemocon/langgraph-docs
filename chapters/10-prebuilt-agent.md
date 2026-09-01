# Chapter 10 — The prebuilt agent

Chapters 2 to 9 built graphs by hand. Most agents do not need that, because most agents are
the same graph: call a model, run any tools it asked for, repeat until it stops asking.

That graph ships ready-made. This chapter covers when to use it, what it actually builds,
and how to leave it when you outgrow it.

## The import has moved

Start here, because this is where an hour disappears.

Nearly every LangGraph tutorial, answer and blog post you will find says:

```python
from langgraph.prebuilt import create_react_agent    # deprecated
```

Run it against a current install and it still works, with a warning:

```
LangGraphDeprecatedSinceV10: create_react_agent has been moved to `langchain.agents`.
Please update your import to `from langchain.agents import create_agent`.
Deprecated in LangGraph V1.0 to be removed in V2.0.
```

The current form is:

```python
from langchain.agents import create_agent

agent = create_agent(model, tools=[search_kb, lookup_customer, escalate])
```

Note the differences beyond the name: `tools` is now a keyword argument, and the node it
builds is called `model` rather than `agent` — which matters, because node names appear in
your traces, your `get_state().next`, and your interrupt configuration.

This is the concrete form of a warning worth repeating: **this library moves faster than the
writing about it.** Chapter 31 gives a routine for telling current advice from stale.

## What it builds

`create_agent` returns an ordinary compiled graph. Ask it:

```python
print(list(agent.get_graph().nodes))
```

```
['__start__', 'model', 'tools', '__end__']
```

Two real nodes. It is the loop from Chapter 8 — `model`, a conditional edge to `tools` or
`END`, and `tools` back to `model`. There is no hidden machinery, and it is worth confirming
that for yourself early, because it makes the prebuilt agent much less mysterious.

Running it against the scripted model:

```
HumanMessage  how long for a refund?
AIMessage     Checking.
ToolMessage   Refunds are issued to the original payment method within 5 w
AIMessage     Refunds take five working days.
```

Four messages: the question, the model's decision to use a tool, the tool's result, and the
final answer. That message list *is* the agent's state.

## Compared to the hand-written version

The book's `build_agent()` writes it out longhand:

```python
def call_model(state):
    return {"messages": [model.invoke(state["messages"])], "trail": ["model"]}

def should_continue(state) -> Literal["tools", "__end__"]:
    return "tools" if state["messages"][-1].tool_calls else END

StateGraph(TicketState)
    .add_node("model", call_model)
    .add_node("tools", ToolNode(ALL_TOOLS))
    .add_edge(START, "model")
    .add_conditional_edges("model", should_continue, ["tools", END])
    .add_edge("tools", "model")
```

About fifteen lines against one. The fifteen are worth writing **once**, as an exercise, so
that the one is not magic — and then you should use the one.

`ToolNode` is the piece worth knowing independently: it takes the tool calls from the last
message, runs them (in parallel, if there are several), and appends a `ToolMessage` for
each, matched by id. You can use it in any graph of your own.

## Where the prebuilt agent stops

Use `create_agent` when your application *is* the loop. Move to a hand-built graph when you
need something the loop cannot express:

| Requirement | Prebuilt | Custom graph |
|---|---|---|
| Model + tools until done | yes | unnecessary |
| A system prompt, memory, structured output | yes, via options | — |
| Approve specific tools before they run | via middleware | yes |
| Deterministic steps before or after the loop | no | yes |
| Branching that is not "tool or stop" | no | yes |
| Parallel fan-out over documents | no | yes |
| Two models with different roles | no | yes |

The escape hatch is that it returns a normal graph, so "outgrowing it" is not a rewrite. You
can put it inside a larger graph as a node:

```python
.add_node("classify", classify)          # deterministic, no model
.add_node("agent", create_agent(model, tools=ALL_TOOLS))
.add_node("record", record_outcome)
```

Chapter 9's subgraph rules apply — in particular, `messages` is a reducer key, so read that
chapter before sharing it.

## Options worth knowing

`create_agent` takes arguments that cover most of what people hand-roll:

- **`system_prompt`** — the standing instructions.
- **`checkpointer`** — persistence, exactly as in Chapter 11. This is what makes it a
  conversation rather than a one-shot.
- **`response_format`** — a schema for structured final output.
- **`middleware`** — hooks around the loop, including human approval of tool calls. This is
  the current mechanism for the "ask before running this tool" requirement.

The middleware layer is where the prebuilt agent has grown most, and it is worth checking the
current documentation rather than this table: `middleware` in particular gained capabilities
after this book's pinned versions.

## Recognising the failure modes

Two problems account for most prebuilt-agent trouble, and both are covered elsewhere because
neither is really about the prebuilt agent.

**It loops.** The model keeps calling tools. Chapter 8 — set `recursion_limit` explicitly,
and check that your tools return results that tell the model to stop rather than merely
reporting nothing found.

**It ignores a tool, or calls it wrongly.** Almost always the tool's description and
signature, which are what the model actually sees. `search_kb(query: str)` with the
docstring *"Search the support knowledge base for an article matching the query"* is a
specification; a bare `def search(q)` is a guess. Write tool docstrings as prompts, because
that is what they are.

## Try it

Confirm the prebuilt agent is just a graph, and that the node is called `model`:

```bash
uv run python -c "
from langchain.agents import create_agent
from examples.triage.fakes import ScriptedModel
from examples.triage.tools import ALL_TOOLS

script = [
    {'text':'Checking.', 'tool_calls':[{'name':'search_kb','args':{'query':'billing'}}]},
    {'text':'Refunds take five working days.'},
]
agent = create_agent(ScriptedModel(script=script), tools=ALL_TOOLS)
print('nodes:', list(agent.get_graph().nodes))
for m in agent.invoke({'messages':[('user','how long for a refund?')]})['messages']:
    print(f'{type(m).__name__:13} {str(m.content)[:55]}')
"
```

Now run the book's hand-written equivalent and compare the message sequence:

```bash
uv run python -c "
from examples.triage.graph import build_agent
from langchain_core.messages import HumanMessage
out = build_agent().invoke({'ticket_id':'T-1001','body':'billing','messages':[HumanMessage('refund?')]})
for m in out['messages']: print(f'{type(m).__name__:13} {str(m.content)[:55]}')
"
```

Same four-message shape. Then trigger the deprecated import and read the warning yourself,
so you recognise it in someone else's code:

```bash
uv run python -c "from langgraph.prebuilt import create_react_agent" 2>&1 | tail -2
```

## Takeaways

- **`from langgraph.prebuilt import create_react_agent` is deprecated.** Use
  `from langchain.agents import create_agent`, with `tools=` as a keyword. Most material
  online still shows the old form.
- The prebuilt agent is an ordinary compiled graph with two real nodes, `model` and `tools`.
  Verify with `get_graph().nodes`.
- Write the loop by hand once so it is not magic; then use the prebuilt one.
- `ToolNode` is independently useful: it runs the last message's tool calls, in parallel, and
  appends matching `ToolMessage`s.
- Outgrow it by nesting it — it is a normal graph, so it can be a node in a bigger one.
  Chapter 9's shared-reducer-key warning applies to `messages`.
- Set `recursion_limit` explicitly; a prebuilt agent is a cycle like any other.
- **Tool docstrings and signatures are prompts.** An ignored or misused tool is usually a
  description problem, not a framework problem.

---

Previous: [Chapter 9 — Subgraphs](09-subgraphs.md) ·
Next: [Chapter 11 — Checkpointers and threads](11-checkpointers-and-threads.md)
