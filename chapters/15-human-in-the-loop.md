# Chapter 15 — Human in the loop

This is the requirement that ends the hand-written loop, and it is the clearest payoff for
everything in Part III. A graph can stop in the middle of a node, hand a question to a
person, and continue — possibly minutes later, in a different process — with their answer.

## `interrupt` and `Command(resume=...)`

Inside a node, `interrupt(payload)` stops the graph and surfaces the payload:

```python
def review(state) -> Command[Literal["__end__"]]:
    decision = interrupt({"draft": state["draft"], "ticket": state["ticket_id"]})
    if decision == "approve":
        return Command(update={"trail": ["approved"]}, goto=END)
    return Command(update={"draft": str(decision), "trail": ["edited"]}, goto=END)
```

That annotation is not decoration. It is where LangGraph reads this node's outgoing
edges from — nothing called `add_edge` for them — so it must list exactly the
destinations the code can reach. Both branches here end, so `Literal["__end__"]` is the
whole list. Adding `"draft"` to it because a reviewer's edit *feels* like it should
re-draft would declare an edge the code never takes, and put this node in a loop as far
as anything reading the graph's shape is concerned. [Appendix D](../appendices/d-graph-shape.md)
checks for exactly this.

Run it and `invoke` returns early:

```
paused at: ('review',)
interrupt payload: {'draft': 'Thanks for reporting T-1001. Refunds are issued to the
                    original payment method within 5 working days.', 'ticket': 'T-1001'}
```

The payload is whatever you passed — it is what your UI shows the reviewer. Resume by
invoking the **same thread** with a `Command`:

```python
graph.invoke(Command(resume="approve"), config)
```

```
trail: ['classify', 'retrieve', 'draft', 'approved']
next after resume: ()
```

Whatever you pass as `resume` becomes the return value of `interrupt()` inside the node. Send
something else and the other branch runs:

```python
graph.invoke(Command(resume="Rewritten by a human."), config)
```

```
draft: Rewritten by a human.
trail: ['classify', 'retrieve', 'draft', 'edited']
```

Approve, edit, or reject is then just a matter of what the reviewer sends back — no extra
graph machinery.

**A checkpointer is mandatory.** Without one there is nowhere to keep the paused state, and
this does not work at all.

## The rule that surprises everyone

> **The node re-runs from the beginning when resumed.**

`interrupt` is not a coroutine suspension. On resume, LangGraph re-executes the node from
its first line, and this time `interrupt()` returns the value you supplied instead of
stopping.

Recording every line that executes, across a pause and a resume:

```
after first invoke : ['before-interrupt']
after resume       : ['before-interrupt', 'before-interrupt', 'after-interrupt']

'before-interrupt' ran 2 times
'after-interrupt'  ran 1 times
```

One logical review, and the code above `interrupt()` ran **twice**. So:

```python
def review(state):
    ticket = fetch_ticket(state["id"])       # runs twice
    send_slack_message("reviewing...")       # sends twice
    decision = interrupt({"draft": ...})     # stops here, then returns on resume
    return {...}
```

Two rules follow:

- **Put `interrupt()` as early in the node as possible**, ideally first.
- **Keep side effects out of interrupt nodes**, or after the `interrupt()` call.

This is the same idempotency requirement as Chapter 14, in its most concentrated form.

## Detecting the pause

Two ways, and they are for different jobs.

The result of `invoke` contains `__interrupt__` when the graph paused — convenient for a
synchronous caller that just invoked it:

```python
out = graph.invoke(state, config)
if "__interrupt__" in out:
    show_to_reviewer(out["__interrupt__"][0].value)
```

For a background process asking "does this thread need attention?", read the snapshot:

```python
snap = graph.get_state(config)
```

```
next: ('review',)
interrupts: (Interrupt(value={'draft': '...', 'ticket': 'T-1001'},
                       id='fcbe78fb8957b8fa8138d3ed70cba9a7'),)
```

`snapshot.interrupts` is the reliable signal. As Chapter 14 noted, this is what distinguishes
a thread waiting on a person from a thread that crashed — do not try to infer it from node
names.

## Static interrupts

You can also pause at a node boundary without changing node code, at compile time:

```python
graph = builder.compile(checkpointer=saver, interrupt_before=["escalate"])
```

Resume with `invoke(None, config)` — there is no value to inject, so no `Command` is needed.

Use `interrupt_before` for debugging and for blanket "approve every X" policies. Use
`interrupt()` when you need to *ask something specific* and use the answer. The dynamic form
is almost always what a product needs; the static form is what you want at 2 a.m. when you
want to see the state just before a node runs.

## Designing the approval

The mechanism is easy. The design is where these systems succeed or fail.

**Ask rarely.** An agent that asks about everything is worse than no agent — the reviewer
becomes a rubber stamp, and rubber stamps approve the one bad action too. Interrupt on the
irreversible and the expensive: sending a message, spending money, deleting data, escalating
to a customer. Chapter 8's confidence check is the sort of gate worth having.

**Give the reviewer enough to decide.** The payload should contain the proposed action *and
the evidence for it*. A draft with no ticket context cannot be judged, so it will be
approved.

**Offer more than yes/no.** Approve, edit, reject-with-reason. The edit path is the highest
value one, because the correction is usually small and a rejection throws away all the work.

**Have a timeout policy.** Threads paused for a human can sit forever. Decide what happens to
a request nobody answers in a week — expire it, escalate it, or close the ticket — and build
it, because "wait indefinitely" is a decision too, just not a good one.

## In a web application

The pattern that works:

1. `POST /tickets/{id}/triage` → `invoke(state, config)`. If the result has `__interrupt__`,
   store the thread id against a review task and return "pending review".
2. The reviewer's UI reads `get_state(config).interrupts` to render the request.
3. `POST /reviews/{thread_id}` → `invoke(Command(resume=decision), config)`.

Nothing is held open between steps. The web process can restart between (1) and (3); the
state is in the checkpointer, not in memory. That is the whole point.

Two operational notes: the checkpointer must be shared across your web workers, which means
Postgres and not SQLite; and step 3 must be idempotent at the HTTP level, because a reviewer
double-clicking "approve" will send it twice.

## Try it

Pause, inspect, and resume — three separate calls on one thread:

```bash
uv run python -c "
from examples.triage.graph import build_hitl
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

g = build_hitl(checkpointer=InMemorySaver())
cfg = {'configurable': {'thread_id': 'demo'}}
out = g.invoke({'ticket_id':'T-1001','body':'billing refund'}, cfg)
print('paused at:', g.get_state(cfg).next)
print('asking   :', out['__interrupt__'][0].value['draft'])
print('resumed  :', g.invoke(Command(resume='approve'), cfg)['trail'])
"
```

Now take the edit path instead, and watch the draft change:

```bash
uv run python -c "
from examples.triage.graph import build_hitl
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
g = build_hitl(checkpointer=InMemorySaver())
cfg = {'configurable': {'thread_id': 'demo'}}
g.invoke({'ticket_id':'T-1001','body':'billing refund'}, cfg)
final = g.invoke(Command(resume='Rewritten by a human.'), cfg)
print('draft:', final['draft'])
print('trail:', final['trail'])
"
```

Then prove the re-run rule to yourself, because it is the one that bites: add
`print('side effect!')` as the **first** line of `review` in
[`examples/triage/graph.py`](../examples/triage/graph.py) and run the first command again.
It prints twice for one logical review.

## Takeaways

- `interrupt(payload)` pauses mid-node; `invoke(Command(resume=value), config)` continues,
  and `value` becomes what `interrupt()` returned. **A checkpointer is mandatory.**
- **The node re-runs from the top on resume.** Put `interrupt()` first and keep side effects
  out of interrupt nodes.
- Detect a pause with `__interrupt__` in the invoke result, or `snapshot.interrupts` for a
  background sweeper — the latter is what distinguishes "waiting on a person" from "crashed".
- `interrupt_before=[...]` pauses at a node boundary with no code change; resume with
  `invoke(None, config)`. Good for debugging, weaker for products.
- Interrupt on the **irreversible and expensive**, not on everything — a reviewer asked too
  often becomes a rubber stamp.
- Send the evidence with the request, offer approve/edit/reject, and decide what happens when
  nobody answers.
- In a web app nothing is held open: pause, store the thread id, resume later. That requires
  a shared checkpointer (Postgres) and an idempotent resume endpoint.

---

Previous: [Chapter 14 — Durability and resumption](14-durability-and-resumption.md) ·
Next: [Chapter 16 — The debugging mindset](16-debugging-mindset.md)
