# Chapter 23 — Structuring a real project

Everything so far has been a single file. This chapter is about what changes when the graph
has to live in an application, be tested by a team, and be deployed.

## A layout that works

```
src/triage/
  state.py        # the schema, and nothing else
  tools.py        # tools, with docstrings written as prompts
  nodes.py        # node functions -- no graph, no compile
  routers.py      # routing functions -- pure, testable
  graph.py        # assembles and compiles
  models.py       # model construction, one place
  app.py          # the web layer
tests/
  test_nodes.py
  test_routers.py
  test_graph.py
```

The split that earns its keep is **`nodes.py` and `routers.py` importing nothing from
`graph.py`**. Nodes and routers are plain functions; keeping them free of graph imports is
what lets you test them without building anything, and it prevents the circular import you
otherwise hit the moment a node wants to call a subgraph.

## Build the graph in a function

Not at import time:

```python
def build_graph(checkpointer=None, model=None):
    model = model or default_model()
    return (
        StateGraph(TicketState)
        .add_node("classify", classify)
        .add_node("model", make_model_node(model))
        ...
        .compile(checkpointer=checkpointer)
    )
```

Module-level `graph = builder.compile()` runs on import. That means importing your package
constructs model clients and opens database connections — which breaks tests, slows CLI
startup, and makes the import order significant. Take the checkpointer and the model as
arguments so tests can pass fakes.

Compiling is not free but it is cheap, and it is *not* per request. Compile once at
application startup and reuse the object; a compiled graph is safe to invoke concurrently.

## Where the checkpointer lives

The commonest production mistake in this book:

```python
# WRONG -- the connection closes at the end of the request
@app.post("/triage")
def triage(req):
    with SqliteSaver.from_conn_string("db.sqlite") as cp:
        graph = build_graph(checkpointer=cp)
        return graph.invoke(...)
```

Two problems. The connection's lifetime is the request, so a paused thread cannot be resumed
by a later one. And you recompile the graph per request for no reason.

The checkpointer's lifetime must be the **application's**:

```python
@asynccontextmanager
async def lifespan(app):
    async with AsyncPostgresSaver.from_conn_string(DB_URL) as checkpointer:
        await checkpointer.setup()
        app.state.graph = build_graph(checkpointer=checkpointer)
        yield

app = FastAPI(lifespan=lifespan)

@app.post("/triage/{ticket_id}")
async def triage(ticket_id: str, body: str):
    config = {"configurable": {"thread_id": f"ticket-{ticket_id}"}}
    return await app.state.graph.ainvoke({"ticket_id": ticket_id, "body": body}, config)
```

Note `checkpointer.setup()` — the Postgres and SQLite savers create their tables on first
use, and forgetting it produces a missing-table error on the first invoke rather than at
startup.

## Choosing the state schema type

`TypedDict` is the default and is what this book uses. Pydantic is the alternative, and the
reason to choose it is narrower than usually claimed.

```python
class PState(BaseModel):
    ticket_id: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
```

**Pydantic validates the input:**

```
invalid input value  -> ValidationError
wrong type on input  -> ValidationError
missing required     -> ValidationError
```

**It does not validate what nodes write.** A node returning `confidence: 99.0` into a field
declared `le=1.0`:

```
{'ticket_id': 'T-1', 'confidence': 99.0}   type: <class 'dict'>
```

No error. The constraint was not applied, and the result is a plain `dict`, not a `PState`.

This is worth knowing because "use Pydantic so bad values can't get into state" is common
advice and, for node writes, it is **wrong**. Pydantic buys you a validated boundary at the
edge of the graph. If you need invariants enforced on what nodes produce, assert inside the
node or in a test.

| | `TypedDict` | Pydantic |
|---|---|---|
| Input validation | none | yes |
| Node-write validation | none | **none** |
| Defaults | via `total=False` + `.get()` | declared |
| Overhead | none | per-superstep validation |

Use `TypedDict` unless you specifically want the input boundary checked.

## Input and output schemas

By default, `invoke` returns the entire state, including scratch fields nobody outside cares
about. Declare narrower schemas:

```python
StateGraph(FullState, input_schema=In, output_schema=Out)
```

```
{'draft': 'hello'}
```

Only `draft` came back; `scratch` stayed internal. This is worth doing for any graph exposed
over HTTP — it keeps internal fields out of your API surface, so renaming one is not a
breaking change.

## Configuration

Three kinds of configuration, three homes:

- **Per deployment** (API keys, database URL, model name) → environment variables, read once
  at startup.
- **Per request** (tenant, user id, feature flags) → `context` (Chapter 5). Not state: it
  should not be checkpointed.
- **Per run mechanics** (`thread_id`, `recursion_limit`, `max_concurrency`) → the config
  dict.

Never put secrets in state. Everything in state is written to the checkpointer.

## Models in one place

```python
def default_model():
    return init_chat_model(
        os.environ.get("TRIAGE_MODEL", "claude-sonnet-5"),
        timeout=30,
        max_retries=0,     # Chapter 21: don't stack retries
    )
```

One function, so swapping models is one edit and tests can inject a `ScriptedModel`. Scatter
`init_chat_model` across your nodes and changing model becomes a grep.

## Versions

Pin them, and record them where readers can see. This library moves quickly enough that
"LangGraph" without a version is not a reproducible statement:

```toml
dependencies = [
    "langgraph>=1.2,<2",
    "langchain>=1.3,<2",
]
```

Upper bounds matter here more than in most ecosystems. Chapter 31 covers keeping up.

## Try it

Confirm the Pydantic boundary is exactly where this chapter says:

```bash
uv run python -c "
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END

class P(BaseModel):
    ticket_id: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)

g = (StateGraph(P).add_node('n', lambda s: {'confidence': 99.0})
     .add_edge(START,'n').add_edge('n',END).compile())
try: g.invoke({'ticket_id':'T-1','confidence':5.0})
except Exception as e: print('bad INPUT  ->', type(e).__name__)
print('bad WRITE  ->', g.invoke({'ticket_id':'T-1'}))
"
```

Then hide an internal field from the output:

```bash
uv run python -c "
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
class In(TypedDict): body: str
class Out(TypedDict): draft: str
class Full(TypedDict):
    body: str
    scratch: str
    draft: str
g = (StateGraph(Full, input_schema=In, output_schema=Out)
     .add_node('work', lambda s: {'scratch':'internal','draft':'hello'})
     .add_edge(START,'work').add_edge('work',END).compile())
print(g.invoke({'body':'hi'}))
"
```

## Takeaways

- Keep `nodes.py` and `routers.py` free of graph imports. That is what makes them testable
  and prevents circular imports.
- **Build the graph in a function**, taking the checkpointer and model as arguments. Never
  compile at import time.
- Compile once at startup and reuse; a compiled graph is safe to invoke concurrently.
- **The checkpointer's lifetime is the application's, not the request's.** Use a lifespan
  hook, and call `setup()`.
- **Pydantic state validates input but not node writes** — a node can write a value that
  violates its own field constraints. Use `TypedDict` unless you want the input boundary.
- `input_schema` / `output_schema` keep internal fields out of your API surface.
- Deployment config → env; per-request config → `context`; run mechanics → the config dict.
  Secrets never go in state.
- Construct models in one function so tests can inject a fake.
- Pin versions with upper bounds.

---

Previous: [Chapter 22 — Cookbook](22-cookbook.md) ·
Next: [Chapter 24 — Testing graphs](24-testing.md)
