# Chapter 3 — State and reducers

Most LangGraph bugs that reach a production incident are state bugs, and most state bugs are
one question answered wrongly: **when two nodes write the same field, what should happen?**

By default, the second write wins and the first is destroyed. That is right for some fields
and catastrophic for others. A reducer is how you say which.

## The default: last write wins

Declare a field with a plain annotation and each write replaces the previous value:

```python
class State(TypedDict):
    log: list          # no reducer
```

Two nodes, each appending one entry, in sequence:

```python
.add_node("a", lambda s: {"log": ["A"]})
.add_node("b", lambda s: {"log": ["B"]})
```

```
no reducer : {'log': ['B']}
```

`A` is gone. Not merged, not warned about — replaced. The node did exactly what it said:
"set `log` to `["A"]`", and then the next node said "set `log` to `["B"]`".

This is the single most common surprise for people arriving from ordinary Python, where
`state["log"].append("A")` would have accumulated. **Returning a list does not add to a
list. It replaces it.**

## The fix: a reducer

Wrap the type in `Annotated` with a two-argument function. LangGraph calls it with
`(current_value, incoming_update)` and stores the result:

```python
from typing import Annotated
import operator

class State(TypedDict):
    log: Annotated[list, operator.add]
```

Identical graph, identical nodes:

```
operator.add: {'log': ['A', 'B']}
```

`operator.add` on two lists is concatenation, so each write appends. The change is one
annotation; the behaviour is completely different.

The mental model worth carrying:

> A node does not write a value into state. It **submits an update**, and the field's
> reducer decides what that update means.

No reducer means "the update *is* the new value". `operator.add` means "the update is
something to append".

## Choosing one

| You want | Annotation |
|---|---|
| Replace (counters, flags, the current category) | none — plain type |
| Append to a list | `Annotated[list, operator.add]` |
| Sum a number | `Annotated[int, operator.add]` |
| Chat history, with updates by id | `Annotated[list, add_messages]` |
| Anything else | `Annotated[T, your_function]` |

The `triage` state uses three of these, and the choices are the design:

```python
class TicketState(TypedDict, total=False):
    category: str                              # replace: only the latest matters
    confidence: float                          # replace
    messages: Annotated[list, add_messages]    # append, dedupe by id
    trail: Annotated[list[str], operator.add]  # append: the audit log
    evidence: Annotated[list[str], operator.add]
```

`category` has no reducer *on purpose*. Re-classifying should overwrite the old category,
not accumulate a list of every category ever considered. Getting this wrong in the other
direction — a reducer where you wanted replacement — produces a field that grows forever
and quietly inflates your token bill when it reaches a prompt.

## `add_messages`, and why not `operator.add`

Message history looks like a plain append, and `operator.add` nearly works. Use
`add_messages` instead — it does two things concatenation cannot.

**It appends, as expected:**

```python
add_messages([HumanMessage("hi", id="1")], [AIMessage("hello", id="2")])
```

```
[HumanMessage(content='hi', id='1'), AIMessage(content='hello', id='2')]
```

**But a message with an existing id replaces that message rather than duplicating it:**

```python
add_messages([AIMessage("draft one", id="x")], [AIMessage("draft two", id="x")])
```

```
[AIMessage(content='draft two', id='x')]
```

One message out, not two. This is what makes it possible to correct or remove a message
already in the history — which is exactly what you need for editing a bad tool call, or
trimming history to control cost (Chapter 27). It also assigns ids to messages that lack
them, so this behaviour works without you managing ids by hand.

Use `add_messages` for anything holding `BaseMessage` objects. Use `operator.add` for plain
lists like `trail`.

## Writing your own

A reducer is any function of `(current, update)`. To keep the highest confidence score
any node has reported:

```python
def keep_max(current: float, new: float) -> float:
    return max(current, new)

class State(TypedDict):
    best: Annotated[float, keep_max]
```

Three nodes reporting `0.4`, `0.9`, `0.2` in sequence:

```
{'best': 0.9}
```

**Do not pass the builtin directly.** `Annotated[float, max]` looks like it should work and
fails at construction time:

```
ValueError: no signature found for builtin <built-in function max>
```

LangGraph inspects the function's signature to distinguish a reducer from a plain type
annotation, and C builtins have no introspectable signature. Wrap it in a `def`, as above.

Two rules for reducers you write:

- **Be pure and return a new value.** Mutating `current` in place breaks checkpointing,
  which compares old and new values to work out what changed.
- **Handle the first call.** `current` will be whatever the field's initial value is —
  often `None` if you never supplied one.

## Reducers are also how parallelism works

This is the part that is not obvious from the single-node examples, and it is the real
reason reducers exist.

Two nodes running *at the same time* both write `out`, which has no reducer:

```python
.add_node("x", lambda s: {"out": "from-x"})
.add_node("y", lambda s: {"out": "from-y"})
.add_edge(START, "x")
.add_edge(START, "y")
```

```
InvalidUpdateError: At key 'out': Can receive only one value per step.
Use an Annotated key to handle multiple values.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/INVALID_CONCURRENT_GRAPH_UPDATE
```

LangGraph refuses to guess. With sequential writes, "last wins" has an unambiguous meaning —
there is a defined order. With simultaneous writes there is no last, so rather than pick
arbitrarily and give you a race condition, it raises.

**`InvalidUpdateError` at a key is nearly always a missing reducer on a field written by
parallel branches.** Add one and the same graph runs:

```python
out: Annotated[list[str], operator.add]   # now both branches contribute
```

This is why `evidence` and `trail` have reducers in `TicketState`: Chapter 7 fans the graph
out across several retrieval branches, and both fields are written concurrently.

## When a reducer gets the wrong type

Reducers are not type-checked ahead of time. A node returning a string into a list field
fails at runtime, inside the reducer:

```python
.add_node("a", lambda s: {"log": "oops-a-string"})   # log is Annotated[list, operator.add]
```

```
TypeError: can only concatenate list (not "str") to list
```

The message comes from `operator.add`, not from LangGraph, so it does not name the field.
When you see a bare `TypeError` from a reducer, the culprit is a node returning `X` where
the field wants `[X]`. Returning `{"trail": "draft"}` instead of `{"trail": ["draft"]}` is
the usual version of this.

## Try it

Watch a write get destroyed, then rescue it with one annotation:

```bash
uv run python -c "
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

def mk(S):
    return (StateGraph(S).add_node('a', lambda s: {'log': ['A']})
            .add_node('b', lambda s: {'log': ['B']})
            .add_edge(START,'a').add_edge('a','b').add_edge('b',END).compile())

class NoRed(TypedDict): log: list
class Red(TypedDict): log: Annotated[list, operator.add]
print('no reducer :', mk(NoRed).invoke({'log': []}))
print('with reducer:', mk(Red).invoke({'log': []}))
"
```

Then provoke the parallel error, because recognising it on sight saves an hour later:

```bash
uv run python -c "
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
class P(TypedDict): out: str
g = (StateGraph(P).add_node('x', lambda s:{'out':'x'}).add_node('y', lambda s:{'out':'y'})
     .add_edge(START,'x').add_edge(START,'y').add_edge('x',END).add_edge('y',END).compile())
g.invoke({})
"
```

Now fix it by changing `out: str` to `out: Annotated[list, operator.add]` and having each
node return a list.

## Takeaways

- Without a reducer, a write **replaces**. Returning a list does not append to a list.
- A node submits an *update*; the field's reducer decides what that update means.
- `Annotated[list, operator.add]` appends. `Annotated[int, operator.add]` sums.
- Use `add_messages` for message history — it appends *and* replaces by id, which is what
  makes editing and trimming history possible.
- Choosing "no reducer" is a real decision. A reducer on a field that should be replaced
  grows without bound and inflates token cost.
- Reducers must be introspectable: `Annotated[float, max]` raises `ValueError`. Wrap
  builtins in a `def`.
- **`InvalidUpdateError: Can receive only one value per step` means a field written by
  parallel branches has no reducer.** This is the most common route to that error.
- A bare `TypeError` from a reducer means a node returned `X` where the field wanted `[X]`.

---

Previous: [Chapter 2 — Your first graph](02-first-graph.md) ·
Next: [Chapter 4 — The execution model](04-execution-model.md)
