# Chapter 24 — Testing graphs

"You can't test an LLM application, it's non-deterministic" is half true and used to excuse
far too much. The model is non-deterministic. Your routing, your reducers, your state
transitions and your error handling are not, and they are where the bugs in this book live.

This chapter tests everything except the model, gets a fast suite for it, and then says what
to do about the model separately.

## Four layers

Cheapest and most valuable first.

| Layer | What | Needs a graph? | Needs a model? |
|---|---|---|---|
| 1 | Node functions | no | no |
| 2 | Routers | no | no |
| 3 | Graph paths | yes | no |
| 4 | The model loop | yes | scripted |

The book's own suite covers all four in half a second:

```
19 passed in 0.48s
```

No API key, no network, no fixtures beyond a scripted model. That speed is the point: a
suite that runs in half a second gets run.

## Layer 1: nodes are functions

Chapter 5's design pays off here. A node needs no graph:

```python
@pytest.mark.parametrize("body,expected", [
    ("I want a refund", "billing"),
    ("403 on register", "sip-registration"),
    ("choppy audio", "packet-loss"),
    ("my toaster is sentient", "unknown"),
])
def test_classify(body, expected):
    assert classify({"body": body})["category"] == expected
```

Pass a plain dict — you do not need a complete state, only the fields the node reads. That
is also a design check: if a test needs fifteen fields, the node is doing too much.

Test the branch that is easy to forget:

```python
def test_draft_without_evidence_does_not_crash():
    # the escalate path never runs `retrieve`, so `evidence` is absent
    assert "no supporting article" in draft({"ticket_id": "T-1"})["draft"]
```

This is the `KeyError` from Chapter 17, caught in a millisecond.

## Layer 2: routers

Every branch of your control flow, with a dict:

```python
def test_route_covers_both_branches():
    assert route({"confidence": 0.9}) == "retrieve"
    assert route({"confidence": 0.2}) == "escalate"

def test_route_boundary():
    assert route({"confidence": 0.5}) == "retrieve"
```

Include the boundary. `>=` versus `>` at a threshold is the most common routing bug, and it
is invisible in an end-to-end test.

## Layer 3: paths, asserted on `trail`

The `trail` field earns its place here. One assertion covers routing, ordering, and
duplication at once:

```python
def test_confident_ticket_takes_the_retrieve_path():
    out = build_routed().invoke({"ticket_id": "T-1001", "body": "billing refund"})
    assert out["trail"] == ["classify", "retrieve", "draft"]
```

Assert the *path*, not the prose. `assert out["draft"] == "Thanks for..."` breaks whenever
anyone rewords a template; `trail` breaks only when the behaviour changes.

And a structural test that catches Chapter 7's trap before production does:

```python
def test_no_node_runs_twice():
    seen = Counter(node
                   for chunk in graph.stream(inp, stream_mode="updates")
                   for node in chunk)
    assert all(count == 1 for count in seen.values()), seen
```

## Layer 4: the model, scripted

Replace the model with fixed replies and the loop becomes deterministic:

```python
def test_agent_calls_a_tool_then_answers():
    script = [
        {"text": "Checking.", "tool_calls": [{"name": "search_kb", "args": {"query": "billing"}}]},
        {"text": "Refunds take five working days."},
    ]
    out = build_agent(script=script).invoke({...})
    assert [type(m).__name__ for m in out["messages"]] == [
        "HumanMessage", "AIMessage", "ToolMessage", "AIMessage"
    ]
```

You are not testing the model's judgement. You are testing that *given* a tool call, your
graph runs the tool, appends the result correctly, and loops back — which is your code and
is entirely deterministic.

Script the failures too, since they are what you cannot reproduce on demand with a real
model:

```python
def test_agent_respects_recursion_limit():
    forever = [{"text": "again", "tool_calls": [{"name": "search_kb", "args": {"query": "x"}}]}]
    with pytest.raises(GraphRecursionError):
        build_agent(script=forever).invoke(inp, {"recursion_limit": 6})
```

That test is the guard for Chapter 20's expensive failure, and it costs nothing to run.

`ScriptedModel` in [`examples/triage/fakes.py`](../examples/triage/fakes.py) is about sixty
lines. Writing one for your own project is an afternoon that pays back permanently.

## Testing interrupts

Pause and resume in one test — the mechanism is fully deterministic:

```python
def test_interrupt_pauses_then_resumes():
    graph = build_hitl(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}

    out = graph.invoke({"ticket_id": "T-1001", "body": "billing refund"}, config)
    assert "__interrupt__" in out
    assert graph.get_state(config).next == ("review",)

    final = graph.invoke(Command(resume="approve"), config)
    assert final["trail"][-1] == "approved"
    assert graph.get_state(config).next == ()
```

Test both decisions. The edit path is the one that carries real logic and the one people
forget.

Use `InMemorySaver` for this: real persistence is not what you are testing, and a fresh
saver per test keeps them independent.

## A test for a silent failure

Chapter 2's dropped-key bug produces no error, so no ordinary test catches it. Assert on it
directly:

```python
def test_every_node_writes_only_known_keys():
    allowed = set(graph.get_input_jsonschema()["properties"])
    for chunk in graph.stream(inp, stream_mode="updates"):
        for node, update in chunk.items():
            unknown = set(update or {}) - allowed
            assert not unknown, f"node {node!r} wrote unknown keys: {unknown}"
```

One test, every node, catching a class of bug the framework will never report. A type
checker over your state schema catches most of the same thing earlier; this catches what
survives.

## What about the model's actual output?

Everything above deliberately avoids judging what the model *said*. That question is real,
but it is a different discipline — evaluation, not testing:

- It is **not** a pass/fail assertion but a score over a dataset.
- It belongs in a separate, slower suite that costs money to run.
- It does not gate every commit.

Keep them apart. A unit suite that calls a real model is slow, flaky, and expensive, and
teams respond by not running it. Chapter 25 covers the tooling for the evaluation half.

## Try it

Run the book's suite:

```bash
uv run --extra dev pytest -q
```

```
19 passed in 0.48s
```

Then break something on purpose and watch which test catches it. Change `route`'s threshold
from `>= 0.5` to `> 0.5` — the boundary test fails and nothing else does. Then misspell a key
in `draft`'s return dict and confirm `test_every_node_writes_only_known_keys` is the one that
notices, because no other test can.

## Takeaways

- The model is non-deterministic; your graph is not. Test the graph.
- Four layers, cheapest first: **nodes**, **routers**, **paths**, **the scripted loop**. The
  book's suite covers all four in under a second with no API key.
- Nodes and routers take plain dicts. If a test needs a large state, the node is too big.
- **Assert on `trail`, not on prose** — path assertions survive rewording and catch ordering,
  routing and duplication at once.
- Script the model to test the loop, and script the *failures* — a runaway loop test is free
  and guards a genuinely expensive bug.
- Interrupts are deterministic and fully testable. Test approve *and* edit.
- Add an explicit test for unknown state keys; the framework will never report them.
- Keep model-quality evaluation in a separate, slower, paid suite. Do not let it into the
  unit tests.

---

Previous: [Chapter 23 — Structuring a real project](23-project-structure.md) ·
Next: [Chapter 25 — Observability](25-observability.md)
