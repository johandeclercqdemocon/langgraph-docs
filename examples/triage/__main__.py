"""Run the triage example in each of its four shapes.

    uv run python -m examples.triage
"""

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from .graph import build_agent, build_hitl, build_linear, build_routed


def main() -> None:
    print("== linear (ch 2) ==")
    out = build_linear().invoke({"ticket_id": "T-1001", "body": "refund, billing issue"})
    print(out["trail"], "->", out["draft"], "\n")

    print("== routed (ch 6) ==")
    for body in ("billing refund please", "my toaster is sentient"):
        out = build_routed().invoke({"ticket_id": "T-1001", "body": body})
        print(f"{body!r:30} {out['trail']} escalated={out.get('escalated', False)}")
    print()

    print("== agent (ch 10) ==")
    out = build_agent().invoke(
        {"ticket_id": "T-1001", "body": "billing", "messages": [HumanMessage("refund?")]}
    )
    for m in out["messages"]:
        print(f"  {type(m).__name__:13} {str(m.content)[:60]}")
    print()

    print("== human in the loop (ch 15) ==")
    graph = build_hitl(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "demo"}}
    out = graph.invoke({"ticket_id": "T-1001", "body": "billing refund"}, config)
    print("  paused at:", graph.get_state(config).next)
    print("  asking:   ", out["__interrupt__"][0].value["draft"][:60])
    out = graph.invoke(Command(resume="approve"), config)
    print("  resumed:  ", out["trail"])


if __name__ == "__main__":
    main()
