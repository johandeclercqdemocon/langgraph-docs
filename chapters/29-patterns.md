# Chapter 29 — Patterns

Six shapes cover most LangGraph applications. Each is a paragraph of wiring you have already
seen — the value is in knowing which one a problem wants, and what each costs.

## 1. Chain

Deterministic steps in order. No branching, no model deciding anything.

```
START -> extract -> validate -> transform -> store -> END
```

Worth stating because it is under-used. A great many "agents" are chains with one model call
in the middle, and building them as chains makes them testable, cheap and predictable. If the
model is not choosing the control flow, do not give it the control flow.

**Use when:** the steps are known in advance.
**Cost:** none. This is the baseline.

## 2. Router

Classify, then branch. One model call (or none), then deterministic paths.

```
START -> classify -> (billing | technical | escalate) -> END
```

The book's `build_routed()`. The classifier can be a model, but as Chapter 27 noted, a lookup
table is free, instant and testable — try that first.

**Use when:** distinct request types need distinct handling.
**Cost:** one classification, and the risk of misrouting. Add a low-confidence path to a
human rather than forcing a choice.

## 3. Tool-calling agent

The loop: model, tools, model, until it stops. Chapter 10, or `create_agent`.

**Use when:** the sequence of steps genuinely cannot be known in advance.
**Cost:** the highest variance of anything here — unbounded steps, unbounded cost, hardest to
test. Always set `recursion_limit` and a step budget.

The honest advice: **try a router or a chain first.** A surprising number of problems reached
for an agent when a router would have been cheaper, faster and more predictable.

## 4. Orchestrator–worker (map-reduce)

Fan out with `Send`, aggregate with a reducer. Chapter 7.

```python
def fan_out(state):
    return [Send("grade", {"criterion": c, "answer": state["answer"]}) for c in state["criteria"]]
```

**Use when:** *n* independent pieces of work, where *n* is known at runtime — grading against
several criteria, summarising many documents, querying several retrievers.

**Cost:** *n* parallel model calls. Cap with `max_concurrency` and validate the length of
what you are fanning out over.

This is the pattern with the best latency payoff in the book: *n* round trips become one
superstep.

## 5. Reflection

Generate, critique, revise, repeat.

```
generate -> critique -> (revise -> critique | END)
```

Genuinely improves output on writing and code tasks. Two disciplines make it safe:

**Cap the iterations.** The exit condition is a model's quality judgement, and it can be
wrong in the direction of never being satisfied. Two or three rounds, hard-capped in state.

**Give the critic different instructions from the generator**, and ideally a different
prompt entirely. A critic told merely to "review this" against the same context tends to
approve.

**Cost:** two to three times the model calls for one answer. Reserve it for output that
justifies that.

## 6. Supervisor

A coordinating node routes between specialists, each usually an agent of its own.

```
supervisor -> (researcher | writer | checker) -> supervisor -> ... -> END
```

Implemented cleanly with `Command`: the supervisor updates state and names the next worker in
one return (Chapter 6).

**Use when:** genuinely distinct skills with distinct tools, and you have already found a
single agent insufficient.

**Cost:** high, and frequently underestimated. Every hand-off is a model call; context must
be passed explicitly between specialists; and debugging spans several loops. This is the most
over-applied pattern in the ecosystem.

**Try a router of specialised sub-chains first.** It gets most of the benefit — the right
prompt and tools for the job — without the coordination overhead of a model deciding hand-offs
each round.

## RAG, which is not a separate pattern

Retrieval is a node. That is all.

```
START -> retrieve -> generate -> END        # a chain
```

Make it an agent only when the model should decide *whether* and *what* to retrieve — in
which case retrieval is a tool and you are back to pattern 3. Add a grading step and a
re-retrieval loop only after you have measured that the simple version is insufficient.

## Choosing

| Signal | Pattern |
|---|---|
| Steps known in advance | Chain |
| Distinct request types | Router |
| One task, several independent inputs | Orchestrator–worker |
| Output quality justifies revision | Reflection |
| Steps genuinely unknowable in advance | Agent |
| Distinct skills, agent proven insufficient | Supervisor |

Read that top to bottom and stop at the first match. The list is ordered by cost and by how
easy the result is to test, and the discipline of taking the first match rather than the most
interesting one is most of what separates an agent that ships from one that does not.

Patterns also compose: a router whose branches are chains, one of which is an agent, is a
completely normal and healthy design.

## Try it

Compare a router and an agent on the same task and note what you gave up:

```bash
uv run python -c "
from examples.triage.graph import build_routed, build_agent
from langchain_core.messages import HumanMessage

r = build_routed().invoke({'ticket_id':'T-1','body':'billing refund'})
print('router :', r['trail'], '->', r['draft'][:50])

a = build_agent().invoke({'ticket_id':'T-1','body':'billing','messages':[HumanMessage('refund?')]})
print('agent  :', a['trail'], '->', str(a['messages'][-1].content)[:50])
"
```

The router took a fixed, testable path. The agent took a path decided at runtime — more
flexible, and the reason Chapters 20 and 24 exist.

## Takeaways

- Six patterns cover most applications: chain, router, agent, orchestrator–worker, reflection,
  supervisor.
- **Choose the first match reading down the cost-ordered list**, not the most interesting one.
- Chains are under-used. If the model is not choosing the control flow, do not give it the
  control flow.
- Routers beat agents whenever request types are distinct — cheaper, faster, testable. Route
  low confidence to a human.
- Orchestrator–worker with `Send` is the best latency win available: *n* round trips become
  one superstep. Cap concurrency.
- Reflection works but costs 2–3× per answer. Hard-cap iterations and give the critic
  genuinely different instructions.
- **Supervisor is the most over-applied pattern.** Try a router of specialised chains first.
- RAG is not a pattern — retrieval is a node. Make it a tool only when the model should
  decide whether to retrieve.
- Patterns compose. A router whose branches are chains, one of which is an agent, is normal.

---

Previous: [Chapter 28 — Security and multi-tenancy](28-security-and-multi-tenancy.md) ·
Next: [Chapter 30 — The Functional API](30-functional-api.md)
