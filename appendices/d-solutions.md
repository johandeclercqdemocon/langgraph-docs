# Appendix D — Solutions to the exercises

Where a number appears here it is the one the book measured — the same runs the chapters
report. Several exercises ask for a judgement rather than a fact; those answers give the
reasoning that matters. Where an exercise asks you to find something, one answer is given;
others often exist.

---

## Chapter 1 — Why LangGraph

**1.** A chain stops expressing the task at the first point where **step N+1 depends on a
decision made at step N** in a way that is not a fixed sequence — a loop whose length is not
known, a branch that depends on a computed value, or a step you need to pause and resume. That
is the boundary.

**2.** **Explicit state** you can inspect and modify (costs a schema to design); **arbitrary
control flow** — loops, branches, fan-out (costs you having to bound it yourself); and
**persistence with resumption and interrupts** (costs a checkpointer and a thread identity).

**3.** **LangChain** provides the components — models, prompts, tools, retrievers — and the
common compositions. **LangGraph** provides the runtime: state, control flow, persistence and
interruption, for shapes that are not a chain.

**4.** A fixed pipeline with no branching — a chain is simpler and faster to reason about. And
a single model call with a tool loop that the prebuilt agent already handles: writing the
graph yourself buys nothing until you need to change its shape.

## Chapter 2 — Your first graph

**1.** A **state schema**, a **`StateGraph`** built from it, at least one **node** function,
**edges** (including from `START` and to `END`), and a **compile** step producing the runnable.

**2.** You stopped thinking about a sequence of function calls and started thinking about
**state and transitions**. The node no longer knows what runs next; the graph does — which is
what makes the control flow inspectable and changeable.

**3.** A **runnable object** with the LangGraph interface — `invoke`, `stream`, `get_state`,
`update_state` — plus validation that the graph is well-formed. Compilation is where structural
errors surface, before any node runs.

**4.** Because the structure is **declared as data** rather than implied by call order.
`get_graph().draw_ascii()` (or Mermaid) renders it. A chain of arbitrary Python has no such
declaration — its control flow exists only when it executes.

## Chapter 3 — State and reducers

**1.** Without a reducer the key is **overwritten** — last write wins, and under parallel
execution which write is "last" is not something you should rely on. With two nodes writing
the same key you lose one of them silently.

**2.** `operator.add` on a list appends. Replace is correct for a value that has one current
answer (a status, a decision); append is correct for an accumulation (messages, results,
errors). Choosing wrongly is the most common state bug.

**3.** Because it determines what can be parallel, what can be resumed, what a checkpoint
contains, and what a reducer must handle. Every other design decision in the graph follows
from it, which is why it is worth getting right before writing nodes.

**4.** A non-commutative reducer — string concatenation, or a list append where order carries
meaning — produces **different results depending on which branch finishes first**. Serially it
looks fine; under parallelism it is non-deterministic, and the bug appears only under load.

## Chapter 4 — The execution model

**1.** A superstep runs all currently-active nodes **against the same snapshot of state**, then
applies all their updates through the reducers, then determines which nodes are active next.
Between supersteps: reducers run, the checkpoint is written, and the next frontier is computed.

**2.** Have two parallel nodes each read a key that the other writes. Neither sees the other's
value — both see the value from the start of the superstep. That is the guarantee, and it is
what makes parallel nodes safe to write.

**3.** Because "what does this node see" has a precise answer — the previous superstep's
committed state — rather than depending on timing. Once you know that, fan-out, reducers and
race-free parallelism all follow rather than being surprises.

**4.** Trace the frontier: `START`'s successors run in superstep 1, their successors in
superstep 2, and nodes at the same depth run **together**. Verify with `stream` and observe the
event boundaries.

## Chapter 5 — Nodes

**1.** It receives the **current state** (matching the schema) and returns a **partial state
update** — a dict of the keys it wants to change. It does not return the whole state and does
not mutate its argument.

**2.** Because returning only what changed is what lets the reducers merge updates from
parallel nodes correctly. Returning the whole state would overwrite keys the node never
considered, and would make parallel execution impossible to reason about.

**3.** The run raises and stops. **The checkpoint from the last completed superstep survives**,
so the thread can be inspected and resumed — which is the practical difference from an
exception in an ordinary function.

**4.** It should not perform its own control flow decisions about what runs next — that belongs
in edges — and it should not hold state between invocations. The first belongs in a conditional
edge, the second in state or the Store.

## Chapter 6 — Edges and routing

**1.** A **node name** (or a list of names, or `END`). It is a routing decision, not a value —
the function inspects state and names the next node.

**2.** Measured: asking for `c` produced **`b` and `c`**. The cause is that a normal edge into
`c` still exists alongside the conditional route, so `c` is reachable by two paths and `b` was
also active. Routing does not *remove* edges; it adds a decision on top of the graph you
declared.

**3.** A **conditional edge** expresses "where do we go next" and keeps the decision in the
graph structure, where it is visible and drawable. A **node that decides** hides the control
flow inside a function. Use the edge when the decision is about routing; use a node when the
decision is a computation whose *result* is then routed on.

**4.** The node writes a value into state; the conditional edge reads that key and returns a
node name. Tracing one run shows the decision as a distinct step, which is exactly why it is
worth keeping in the edge.

## Chapter 7 — Parallelism and `Send`

**1.** A reducer that **accumulates** — typically `operator.add` on a list — because every
dispatched branch writes to the same key and you want all of them.

**2.** Parallel edges fan out to a **fixed, known set** of nodes. `Send` fans out to a
**dynamic number** of instances of the same node, one per item, with per-item input. You need
`Send` whenever the width depends on data.

**3.** One update wins and the other is lost, silently and non-deterministically. That is the
canonical parallelism bug, and it is a reducer problem rather than a concurrency problem.

**4.** Bound the number of items dispatched. Without a bound, one large input fans out to
hundreds of model calls at once — the cost is linear in the fan-out and arrives all at once,
which is also how you hit provider rate limits.

## Chapter 8 — Loops, limits and termination

**1.** A **conditional edge** that returns either the loop node or `END`, based on a state
key. Termination is expressed as a routing decision on state, not as a `break`.

**2.** `GraphRecursionError` after the configured number of supersteps. It protects you from an
infinite loop consuming money and time indefinitely — it is a **safety net**, not a design.

**3.** A satisfaction condition (the work is done), a **counter** (bounded attempts), and a
budget (tokens or cost). Only the counter and the budget are safe alone; a satisfaction
condition alone can never terminate if the condition is never met.

**4.** Because the model can always decide to continue, and a model that is confused will
continue confidently. A bound must be something the model cannot influence — a counter or a
budget enforced in code.

## Chapter 9 — Subgraphs

**1.** The subgraph has its own state schema; keys shared with the parent are mapped, and the
rest are private to it. That mapping is the interface between them.

**2.** **Reuse** — the same sub-workflow invoked from several places — or **isolation**, where a
sub-workflow's state should not pollute the parent's schema. Both are design reasons rather
than length reasons.

**3.** Subgraph steps appear as nested events in streaming, and their state is checkpointed as
part of the parent thread — so resumption works through a subgraph boundary, and streaming can
show or hide the internal steps depending on how you subscribe.

**4.** When it is only about file length — splitting a graph into subgraphs for tidiness adds
a state-mapping boundary you now have to maintain. Use modules and functions for organisation;
use subgraphs for reuse and isolation.

## Chapter 10 — The prebuilt agent

**1.** A graph with a model node and a tool node, a conditional edge routing on whether the
model produced tool calls, and an edge from the tool node back to the model.

**2.** What you would get wrong first: pairing `tool_call_id`s correctly, handling **parallel
tool calls** in one response, appending messages in the right order, and terminating when there
are no tool calls. All are fiddly and all are already correct in the prebuilt.

**3.** When you need a step that is not "model then tools" — a validation node, a retrieval
step before the model, a different loop bound per tool, or an interrupt at a specific point.
At that moment build the graph; until then the prebuilt is the same graph, written correctly.

**4.** Set `recursion_limit` at invocation, or add a step counter in state with a conditional
edge to `END`. Verify by giving it a task that would otherwise loop and confirming it stops.

## Chapter 11 — Checkpointers and threads

**1.** A **checkpointer** on compile, and a **`thread_id`** in the config at invocation.
Without the first there is nothing to save; without the second there is no identity to resume.

**2.** A thread is **one conversation or one run's history** — an ordered series of checkpoints
under a single id. It is the design because everything about persistence, resumption, time
travel and multi-tenancy is scoped by it, and it must be chosen before you write handlers.

**3.** Each checkpoint stores the **full state** at a superstep boundary, plus metadata about
which node produced it and what comes next. What is not stored: anything you kept outside
state — module-level variables, open connections, or values held in a closure.

**4.** A durable one — Postgres or SQLite — because the in-memory checkpointer loses everything
on restart, which defeats resumption and human-in-the-loop entirely. The in-memory one is for
tests and examples.

## Chapter 12 — Time travel

**1.** It is still there. Checkpoints form a history, and resuming from an earlier one creates a
new branch rather than deleting the old — which is what makes the operation safe to try.

**2.** A **fork**: two divergent futures from a common past. It enables what-if exploration,
re-running a step with a corrected value, and A/B comparison of a decision point without
re-running everything before it.

**3.** Because state is committed at **superstep boundaries** and each commit is a checkpoint.
Once you persist state at every boundary, "go back to boundary N" is already possible — time
travel is reading that history rather than a separate mechanism.

**4.** Recovering from a bad decision in a long-running workflow: rather than restarting an
expensive multi-step process, roll back to the checkpoint before the faulty step, correct the
state, and continue. Also: replaying a customer's run for support without re-charging for the
early steps.

## Chapter 13 — Store: memory across threads

**1.** The **checkpointer** persists one thread's execution state so it can be resumed. The
**Store** persists arbitrary data **across** threads, keyed by a namespace, so it outlives any
single conversation.

**2.** Write under a namespace containing the user id, then read it from a different
`thread_id`. The checkpointer cannot do this because its data is scoped **to a thread** — that
scoping is the whole point, and it is why cross-conversation memory needs a different tool.

**3.** The namespace must contain the **user or tenant identifier**, taken from the session
rather than from anything the model produced. Getting that wrong is how one user's memory
reaches another.

**4.** State is scoped to a thread, so "long-term memory" in state is forgotten the moment a
new conversation starts — and if you work around that by reusing one thread forever, the
checkpoint grows without bound and every run replays a larger history.

## Chapter 14 — Durability and resumption

**1.** From the last completed **superstep** boundary, because that is where state was
committed. Anything the interrupted superstep had partially done is not in the checkpoint and
runs again.

**2.** It guarantees that **committed state** survives a crash and that the run can continue
from the last boundary. It does **not** guarantee that a node's side effects happened exactly
once — that is your problem.

**3.** A node that sends an email or charges a card will do it twice if it re-executes. Making
it safe means **idempotency**: record in state that it happened and check first, or use an
idempotency key the downstream service honours.

**4.** Side effects performed **before** the node returns are not covered by the checkpoint —
the state update lands only on success, so a crash after the side effect but before the return
replays it. The fix is the same idempotency discipline, and it is easy to forget precisely
because durability sounds like it has solved the problem.

## Chapter 15 — Human in the loop

**1.** A **checkpointer** and a **`thread_id`**. Without the first there is no state to pause
into; without the second the resume cannot find it.

**2.** The graph **persists its entire state and returns**. Execution does not live in a
thread, a socket or memory — it lives in the checkpointer, which is why the resume can happen
minutes later from a different process or machine.

**3.** `update_state` before resuming. It is better than approve/reject when the interesting
case is "nearly right" — forcing a binary decision makes reviewers reject and restart rather
than correct, which is slower and loses the work already done.

**4.** Request-scoped: the HTTP handler, the resume call, the response. **Not** request-scoped:
the compiled graph, the checkpointer and the Store. Compiling the graph per request — and
therefore creating a new checkpointer — is the mistake that makes resumption silently
impossible.

## Chapter 16 — The debugging mindset

**1.** The **graph structure** (does it build, are the edges what you think), **state** (is the
value what you expect at this boundary), **a node's logic**, **the model**, and **the
surrounding integration**. Cheapest probes: draw the graph; `get_state` at a checkpoint;
call the node as a plain function; call the model directly; and run the graph with fakes.

**2.** Pin the model and temperature, and pin any retrieval or tool results by faking them.
Then the only remaining variation is your own code, which is what you are trying to debug.

**3.** Because the checkpoint contains **the whole state at a defined boundary**, already
recorded, for every superstep — including runs that already happened. Print statements only
show what you thought to print, only on runs you instrumented in advance.

**4.** `get_state_history` and inspect the state at each checkpoint until it first becomes
wrong. That interval contains the node that broke it — the same bisection idea, with the
history already captured for you.

## Chapter 17 — When the graph won't build or run

**1.** Compile raises: an unreachable node, a node that is never a target, or an edge naming a
node that does not exist. The message names the node, and the fix is structural.

**2.** It has no path from `START`, or the entry point was never set — so there is nothing to
run and no error, because a graph with no active nodes simply finishes.

**3.** It returned something that is **not a dict** (a bare value, or `None` from a function
that forgot to return), or it returned a **key not in the state schema**, which is rejected
rather than silently ignored.

**4.** Compile-time errors are structural and caught before anything runs; runtime errors
depend on the data taking a particular path. **Prefer compile-time** — which is an argument for
expressing routing in edges, where it is validated, rather than in node logic.

## Chapter 18 — Streaming and observing

**1.** They are **state updates per superstep** — which node ran and what it wrote — not model
tokens. That is the default mode, and it is what makes streaming useful for observing progress
through a graph.

**2.** Token streaming comes from **inside a node**, from the model call itself, and must be
surfaced through a different stream mode. The graph's own events are at superstep granularity;
tokens are finer than any graph event.

**3.** Typically that a key was written by a node you did not expect, or written twice, or that
a branch ran which you thought was excluded — all of which are invisible in the final output
and obvious in the sequence of updates.

**4.** Per-node latency, which nodes ran (and how often), token usage per model call, retries,
and where the run terminated — whether by reaching `END` or by hitting a limit.

## Chapter 19 — When state is wrong

**1.** The **checkpoint history**. Walk it until the key first holds the wrong value; the node
that ran in that superstep is the culprit. This beats reasoning about the code because it is
evidence.

**2.** A **missing reducer** (one parallel write overwrote the other) or a **non-commutative
reducer** (both writes landed but in an order that produced the wrong result). Both are silent
and both are invisible in serial runs.

**3.** Compare the state before and after each superstep in the history — the superstep where
it changed identifies the node, since a superstep's updates are attributable to the nodes that
ran in it.

**4.** A reducer that is order-dependent — string concatenation, or an append where the
consumer assumes an order. Serially, one branch always finishes first and the result looks
stable; in parallel the order varies and so does the answer.

## Chapter 20 — Runaway loops and cost

**1.** A **counter in state** with a conditional edge to `END`; the **`recursion_limit`**; and
a **token or cost budget** checked in a node. The first is the design, the second is the safety
net, the third is what actually protects the bill.

**2.** Because it is a fixed number of supersteps with no relation to your task's semantics —
it stops runaway execution but tells you nothing about whether the work was done. Designing
termination means expressing the *actual* completion condition.

**3.** Measured: **twice for one review**. The cause is a node reachable by two paths in one
superstep, or a retry that re-executed a node whose result was not checkpointed — either way
the model is called more times than the graph's shape suggests. Streaming the events shows the
duplication.

**4.** Accumulate `usage_metadata` into state at every model call, and check it in a
conditional edge before dispatching more work. Enforcing it in an edge rather than inside a
node means the check cannot be skipped by a different path.

## Chapter 21 — Errors, retries and caching

**1.** The **whole node**, from its start, with the same input state. Anything the node did
before failing — including side effects — happens again.

**2.** It must be **deterministic and free of side effects** given the same input. Caching a
node that writes to a database, or one whose output depends on the current time, produces
results that are wrong in ways that are very hard to trace.

**3.** An error that should **fail the run** is one where continuing produces a meaningless
result. An error that belongs **in state** is one the graph can route on — a tool that failed,
a validation that did not pass — so a later node can retry differently or ask a human.

**4.** A retried node re-executes from the last checkpoint, so it sees the state as it was
*before* its own partial updates — which is correct, and surprises people who expect the
partial work to have been saved.

## Chapter 22 — Cookbook

**1.** The node returned an update for a key that is **not in the state schema**, or returned
nothing. Both leave state unchanged with no error visible in the output.

**2.** State from the first run persisted under the same `thread_id`, so the second invocation
started from an existing history rather than fresh. Either use a new thread id, or reset the
state deliberately.

**3.** A node ran twice — reachable by two paths in one superstep, or re-executed by a retry.
Stream the events and count the model calls; the graph's declared shape and its actual
execution have diverged.

**4.** Missing or wrong **reducers**; state written outside the schema; **thread_id** reuse or
misuse; and unbounded loops. Nearly everything reduces to "state was not designed" or "the
graph's shape is not what you believe".

## Chapter 23 — Structuring a real project

**1.** The state schema, the node functions, the graph construction and the configuration each
move into their own module. The boundary is that **nodes are plain functions of state** — they
should be importable and testable without the graph.

**2.** Compile **once at startup**, not per request. Compiling per request recreates the
checkpointer, which silently breaks resumption (Chapter 15), and wastes work on every call.

**3.** Both are process-level dependencies constructed at startup and injected — never created
inside a node or a request handler, because both must outlive any single run.

**4.** The web layer owns auth, tenancy, request parsing and the `thread_id`; the graph owns
state and control flow. What must not cross: request objects inward, and raw state outward —
the boundary carries plain data plus the thread identity.

## Chapter 24 — Testing graphs

**1.** Nodes are **plain functions of state**, so calling one with a dict is an ordinary unit
test. What would have made it hard: reading configuration from module scope, or reaching for
the graph from inside the node.

**2.** Because routing is where the graph's logic lives, it is **pure and deterministic**, and
it is cheap to test exhaustively — every state shape, every branch, no model calls. A routing
bug is a whole-run failure, and this test catches it in microseconds.

**3.** The model, and any tool that touches the network. What remains under test is the
**structure**: which nodes ran, in what order, and what state resulted — which is what you
actually want to assert about a graph.

**4.** A checkpointer, a thread id, and a way to interrupt mid-run — then assert that resuming
produces the same outcome as an uninterrupted run. It is the only test that exercises
durability, and it is the one nobody writes until after an incident.

## Chapter 25 — Observability

**1.** The full sequence of supersteps with each node's input state, output update and latency
— including nodes that ran unexpectedly. Logs show what you instrumented; the trace shows the
actual execution shape.

**2.** Log the thread id, the node name, the state keys written, token usage, and the
superstep index, correlated per run. That reconstructs most of a trace at the cost of doing it
by hand.

**3.** Runs terminating by **recursion limit** rather than reaching `END`; nodes executing more
often than the graph's shape predicts; and checkpoint write failures, which silently disable
resumption.

**4.** Because the trace tells you *what happened* and the checkpoint tells you *the exact
state at that moment* — together you can not only see the failure but resume from just before
it, with corrected state.

## Chapter 26 — Deployment

**1.** A **durable checkpointer** and Store (not in-memory), configuration and secrets from the
environment, a compiled graph at startup, concurrency limits, and observability. Locally you
have none of these and everything still works, which is what makes the gap easy to miss.

**2.** Postgres for both, in most cases: it is durable, shared across replicas, and
transactional. Defend it against SQLite by the requirement that **multiple replicas share
state** — SQLite on a local disk cannot.

**3.** State must live **entirely in the checkpointer and Store**, not in process memory, so
any replica can serve any thread. If a node depends on module-level state, horizontal scaling
silently produces inconsistent behaviour depending on which replica handles the request.

**4.** Using the in-memory checkpointer, or compiling the graph per request. Both work
perfectly in development and in a single-replica test, and both mean a resume silently starts
from nothing.

## Chapter 27 — Performance and cost

**1.** Measured overhead is a fraction of a millisecond per superstep — negligible beside a
model call of hundreds of milliseconds. It would only matter for a graph with many supersteps
and no model calls, which is not what LangGraph is for.

**2.** The **model calls** dominate. Within the graph itself, checkpoint writes are the next
term, which is why checkpointer choice matters more than node efficiency.

**3.** Input tokens, and specifically **state that grows and is resent** — message history
accumulating in state and being passed to the model on every superstep. The graph's own
overhead is not a cost term.

**4.** Trim what goes into the model (not everything in state needs to be in the prompt); bound
loops; cache deterministic nodes; and choose a cheaper model per node where the step allows.
Trimming context is first because it reduces cost and latency together.

## Chapter 28 — Security and multi-tenancy

**1.** From the **authenticated session**, and never from the model, the user's message, or the
graph state — anything the model can influence can be manipulated. It belongs in the config
passed at invocation, and in the Store namespace.

**2.** Because state carries everything the run has seen, and it is persisted under a thread
id. If thread ids are guessable or reused across tenants, one tenant's conversation, retrieved
documents and tool results become readable by another.

**3.** Give the node a narrow, validated interface and take its authority-bearing parameters
from configuration rather than from the model's arguments. Constraining the model is advisory;
constraining the node is enforcement.

**4.** A `thread_id` derived from something user-supplied and not namespaced by tenant — for
example a bare conversation id. Two tenants can then collide on the same id, and the second
resumes into the first's state.

## Chapter 29 — Patterns

**1.** Each pattern fits a task whose **control-flow shape** matches it — a fixed pipeline, a
bounded loop, a fan-out and reduce, a supervisor delegating to workers — and fails when the
task's shape is more dynamic (too rigid) or less (needless machinery and non-determinism).

**2.** Usually determinism, cost and debuggability improve, because an explicit pattern bounds
what can happen. The exercise matters because "an agent" is the default reach and is often more
freedom than the task needs.

**3.** Because the execution model is supersteps over shared state, the natural shapes are
those expressible as node activation over that state: sequences, branches, bounded loops, and
fan-out with a reducer. Patterns that need something else — true streaming pipelines, or
unbounded recursion — are not natural here.

**4.** A good answer names the constraint that forced the choice and says what the neighbouring
patterns would have cost in determinism, money or complexity.

## Chapter 30 — The Functional API

**1.** The imperative version reads as ordinary Python — sequential statements rather than
nodes and edges — while the graph version makes the structure explicit and drawable.

**2.** It keeps the runtime guarantees: checkpointing, resumption, interrupts and streaming.
It gives up the **explicit structure** — you can no longer draw the graph or inspect the
routing without reading the code.

**3.** Clearly better when the control flow is genuinely sequential with a little branching, and
expressing it as a graph is ceremony. Clearly worse when several people must reason about the
control flow, or when the shape is the thing that changes most — there, the drawable structure
is the point.

**4.** Both compile to the same underlying runtime, so a Functional-API workflow checkpoints,
resumes and interrupts identically. Demonstrate by attaching a checkpointer and resuming one.

## Chapter 31 — The ecosystem

**1.** `langgraph` (the runtime), checkpointer packages (Postgres, SQLite), `langchain-core`
for the component interfaces, and the platform/CLI tooling for deployment. The boundary is that
the runtime does not depend on any particular model or component library.

**2.** Checkpointers live in their own packages so the core does not depend on a database
driver; component interfaces live in `langchain-core`. The split keeps the runtime installable
without dragging in a stack you may not use.

**3.** The API has moved quickly, so a large share of tutorials and answers online target
versions that no longer exist. The method: check the installed version, read the current API
reference or the source, and verify anything you copy before trusting it.

**4.** A plain state machine or a workflow engine (Temporal, Airflow) is better when the work is
long-running, heavily side-effecting and not model-centric — those give you far stronger
durability and operational tooling, at the cost of the LLM-specific ergonomics.

## Chapter 32 — Anti-patterns

**1.** Common findings: state keys without reducers that are written in parallel; long-term
memory kept in state instead of the Store; the graph compiled per request; loops bounded only
by `recursion_limit`; nodes with side effects that are not idempotent; and no test on the
routing functions.

**2.** Usually: **missing reducers under parallelism** (silent, non-deterministic, and worst
under load), **compiling per request** (silently breaks resumption and human-in-the-loop), and
**unbounded loops** (costs real money before anyone notices).

**3.** Both come from **treating state as incidental** rather than as the design. Missing
reducers, writes outside the schema, memory in the wrong place and parallel races are all the
same failure to decide, up front, what state is and who may write each part of it.

**4.** A type checker catches state-schema mismatches and node return types — real value, since
returning the wrong shape is common. It cannot catch whether a reducer is *correct*, whether a
loop terminates, whether a `thread_id` is safely scoped, or whether a node is idempotent. Those
are design questions.
