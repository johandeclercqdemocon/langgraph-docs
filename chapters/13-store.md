# Chapter 13 — Store: memory across threads

A checkpointer remembers a *conversation*. It is scoped to a `thread_id`, so a user who
starts a new conversation gets a blank slate — which is correct for the conversation and
wrong for the user. "You told me last week you prefer short answers" cannot live in a
thread.

The **Store** is the other kind of memory: key-value data scoped to whatever you choose,
readable from any thread.

## The two memories

| | Checkpointer | Store |
|---|---|---|
| Scope | one thread | any namespace you define |
| Holds | the whole graph state | facts you explicitly put there |
| Written by | the runtime, every superstep | your code, deliberately |
| Lifetime | the conversation | as long as you keep it |
| Analogy | working memory | long-term memory |

You will usually want both, and they are configured together:

```python
graph = builder.compile(checkpointer=InMemorySaver(), store=InMemoryStore())
```

## Using it

The store reaches nodes through `runtime` (Chapter 5's third signature):

```python
def remember(state, runtime: Runtime[Ctx]):
    namespace = ("prefs", runtime.context.user_id)
    runtime.store.put(namespace, "tone", {"value": state["said"]})
    hit = runtime.store.get(namespace, "tone")
    return {"recalled": hit.value["value"] if hit else "nothing"}
```

Three operations cover most use: `put(namespace, key, value)`, `get(namespace, key)`, and
`search(namespace, ...)` for querying. `get` returns an item whose `.value` is your dict, or
`None`.

Written on thread `t1`, read on thread `t2`, same user:

```
thread2 recalled: prefers terse replies
raw store:        {'value': 'prefers terse replies'}
other user sees:  None
```

The fact crossed the thread boundary, and a different user's namespace is empty.

## Namespaces are the design

The namespace is a tuple, and it is the whole access-control and organisation story:

```python
("prefs", user_id)                 # per user
("prefs", org_id, user_id)         # per user within an organisation
("kb", org_id)                     # shared across an organisation
```

Two rules matter more than they look.

**Put the tenant in the namespace, not the key.** `("prefs", user_id)` is enforceable;
`("prefs",)` with keys like `f"{user_id}:tone"` is a prefix-matching bug away from a
cross-tenant leak. Chapter 28 returns to this.

**Derive the namespace from context, never from state.** Context is set by your application
at invoke time; state can be influenced by model output and user input. A namespace built
from state is a path traversal waiting to happen.

## Semantic search

A store can be configured with an embedding model, making `search` semantic rather than
exact:

```python
store = InMemoryStore(index={"embed": embeddings, "dims": 1536})
results = store.search(("prefs", user_id), query="how do they like replies formatted?")
```

This is what turns the store into the retrieval half of a RAG system, and it is worth
knowing before you reach for a separate vector database — for per-user memory, the store you
already have is often enough.

Two caveats. Embedding on `put` costs an API call, so a write-heavy store has a real bill.
And `InMemoryStore`'s search is a brute-force scan — fine for hundreds of items per
namespace, not for millions. `PostgresStore` is the production option, as with checkpointers.

## What to put in it

The hard part is not the API, it is deciding what deserves to be remembered. A store that
accumulates everything becomes a slow, expensive, contradictory pile.

Useful things:

- **Stated preferences.** "Reply in Dutch", "always CC my manager."
- **Stable facts.** Plan tier, timezone, account id.
- **Outcomes worth reusing.** "This customer's SIP issue was a realm mismatch" — so the next
  ticket starts warmer.

Bad candidates:

- **Anything derivable.** If it is in your database, read your database. A second copy in
  the store will drift.
- **Whole conversations.** That is what the checkpointer is for.
- **Model speculation.** An agent that writes its guesses to long-term memory will read them
  back later as fact. This is the most damaging failure mode of agent memory, because it is
  self-reinforcing and invisible.

That last point deserves a design rule: **write to the store from deterministic code where
you can.** If a model decides what to remember, constrain it with a schema and treat what it
writes as a claim, not a fact.

## Forgetting

Memory that only grows is a liability — for contradictions, for cost, and for privacy law.
Decide up front:

- **Deletion.** `store.delete(namespace, key)`. A user asking to be forgotten must be
  satisfiable, which in practice means being able to enumerate every namespace holding their
  data. Design for that on day one; it is painful to retrofit.
- **Updating rather than appending.** Preferences change. Overwrite `("prefs", user)/"tone"`
  rather than appending a list of every tone ever mentioned, or the model will read
  contradictory instructions and pick arbitrarily.
- **Expiry.** Facts go stale. Store a timestamp alongside the value so a reader can judge.

## Try it

Watch a fact cross a thread boundary while staying inside its namespace:

```bash
uv run python -c "
from dataclasses import dataclass
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.runtime import Runtime

@dataclass
class Ctx: user_id: str
class S(TypedDict):
    said: str
    recalled: str

def remember(state, runtime: Runtime[Ctx]):
    ns = ('prefs', runtime.context.user_id)
    runtime.store.put(ns, 'tone', {'value': state['said']})
    hit = runtime.store.get(ns, 'tone')
    return {'recalled': hit.value['value'] if hit else 'nothing'}

store = InMemoryStore()
g = (StateGraph(S, context_schema=Ctx).add_node('remember', remember)
     .add_edge(START,'remember').add_edge('remember',END)
     .compile(checkpointer=InMemorySaver(), store=store))

g.invoke({'said':'prefers terse replies'}, {'configurable':{'thread_id':'t1'}}, context=Ctx(user_id='u1'))
out = g.invoke({'said':'x'}, {'configurable':{'thread_id':'t2'}}, context=Ctx(user_id='u1'))
print('thread2 recalled:', out['recalled'])
print('other user sees:', store.get(('prefs','u2'), 'tone'))
"
```

Note that thread `t2` sent `'x'` and still recalled the earlier value — the store outlived
the thread. Now change the second call's `user_id` to `'u2'` and watch the memory disappear:
that is the namespace doing its job.

## Takeaways

- Checkpointer = one conversation. **Store = facts that outlive it.** Most real applications
  need both, and they are configured together on `compile()`.
- Reach the store through `runtime.store` inside a node; `put`, `get`, and `search` cover
  most needs.
- **The namespace tuple is the design.** Put the tenant in the namespace, not the key, and
  derive it from **context, never from state**.
- A store with an embedding index gives semantic `search` — often enough for per-user memory
  without a separate vector database. Embedding on write costs money;
  `InMemoryStore.search` is a linear scan.
- Store stated preferences, stable facts, and reusable outcomes. Do not store anything
  derivable, whole conversations, or model speculation.
- **Prefer writing to the store from deterministic code.** An agent that remembers its own
  guesses will later read them as fact.
- Plan deletion, in-place updates, and staleness from the start.

---

Previous: [Chapter 12 — Time travel](12-time-travel.md) ·
Next: [Chapter 14 — Durability and resumption](14-durability-and-resumption.md)
