"""A deterministic chat model, so every example in this book runs offline.

Real models make bad teaching material: they cost money, they are slow, and they
give a different answer every time you run the chapter's command. `ScriptedModel`
replays a fixed list of replies instead. Tool calls are real `AIMessage` tool
calls, so `ToolNode` and the prebuilt agent drive it exactly as they would drive
Claude or GPT.

Swap it for a real model by changing one line -- see `triage/graph.py`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ScriptedModel(BaseChatModel):
    """Replays `script` one entry per call, then repeats the last entry forever.

    Each entry is either a string (plain reply) or a dict with `text` and/or
    `tool_calls`, where a tool call is `{"name": ..., "args": {...}}`.
    """

    script: list[Any]
    # A one-element list, not an int, so that copies made by `.bind_tools()` keep
    # counting from where the original left off. `create_agent` re-binds tools on
    # every step; with a plain int the script would reset to entry 0 each time and
    # a tool-calling first entry would loop forever.
    cursor: list[int] = [0]
    # Set by .bind_tools(); recorded so examples can show what the model was offered.
    bound_tools: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    @property
    def calls(self) -> int:
        return self.cursor[0]

    def _next(self) -> AIMessage:
        idx = min(self.cursor[0], len(self.script) - 1)
        self.cursor[0] += 1
        entry = self.script[idx]
        if isinstance(entry, str):
            entry = {"text": entry}
        tool_calls = [
            {"name": tc["name"], "args": tc.get("args", {}), "id": f"call_{idx}_{i}"}
            for i, tc in enumerate(entry.get("tool_calls", []))
        ]
        return AIMessage(
            content=entry.get("text", ""),
            tool_calls=tool_calls,
            # Fixed token counts keep the cost arithmetic in Chapter 27 reproducible.
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Emit one chunk per word, so Chapter 18's token streaming is observable."""
        msg = self._next()
        words = str(msg.content).split(" ")
        for i, word in enumerate(words):
            text = word if i == len(words) - 1 else word + " "
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))
        if msg.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=msg.tool_calls)
            )

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedModel":
        """Record the tool names and return *self*, deliberately.

        Returning a copy here would be the natural implementation and it is wrong.
        `create_agent` re-binds tools on every step, and because this is a pydantic
        model, any copy gets a fresh `cursor` -- so the script would restart at
        entry 0 every step. If entry 0 contains a tool call, that is an infinite
        loop that only stops at the recursion limit. The script is fixed and
        ignores the tools anyway, so sharing one instance is both simpler and
        correct.
        """
        self.bound_tools = [
            getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools
        ]
        return self
