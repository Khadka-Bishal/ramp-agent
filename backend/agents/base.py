from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import anthropic

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Awaitable[Any]]


@dataclass
class AgentEvent:
    role: str
    type: str  # agent_message, tool_call, tool_result, status_change, error
    data: dict
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentOutput:
    role: str
    result: dict
    events: list[AgentEvent] = field(default_factory=list)


class BaseAgent:
    role: str = "agent"
    system_prompt: str = ""
    max_iterations: int = 50
    model: str = "claude-sonnet-4-20250514"

    def __init__(self, tools: list[ToolDef] | None = None):
        self.tools = tools or []
        self._events: list[AgentEvent] = []
        self._event_callback: Callable[[AgentEvent], Any] | None = None
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._messages: list[dict] = []
        self._done = False
        self._result: dict = {}
        self._interrupted = False

    def on_event(self, callback: Callable[[AgentEvent], Any]) -> None:
        self._event_callback = callback

    def _emit(self, type_: str, data: dict) -> AgentEvent:
        event = AgentEvent(role=self.role, type=type_, data=data)
        self._events.append(event)
        if self._event_callback:
            self._event_callback(event)
        return event

    def _build_tools_schema(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in self.tools
        ]

    def _find_tool(self, name: str) -> ToolDef | None:
        for t in self.tools:
            if t.name == name:
                return t
        return None

    async def run(self, context: dict) -> AgentOutput:
        self._messages = [{"role": "user", "content": json.dumps(context)}]
        self._done = False
        self._emit("status_change", {"status": f"{self.role}_started"})
        return await self._loop()

    async def resume(self, user_message: str) -> AgentOutput:
        """Continue the conversation with a follow-up message."""
        if self._messages and self._messages[-1]["role"] == "user":
            if isinstance(self._messages[-1]["content"], list):
                self._messages[-1]["content"].append(
                    {"type": "text", "text": user_message}
                )
            else:
                self._messages[-1]["content"] += f"\n\n{user_message}"
        else:
            self._messages.append({"role": "user", "content": user_message})

        self._done = False
        self._events = []
        self._emit("status_change", {"status": f"{self.role}_resumed"})
        return await self._loop()

    async def _loop(self) -> AgentOutput:
        tools_schema = self._build_tools_schema()
        iterations = 0

        while iterations < self.max_iterations and not self._done:
            if self._interrupted:
                self._done = True
                self._result = {"status": "interrupted", "summary": "Run interrupted"}
                break

            iterations += 1

            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": 16384,
                "system": self.system_prompt,
                "messages": self._messages,
            }
            if tools_schema:
                kwargs["tools"] = tools_schema

            response = await self._client.messages.create(**kwargs)

            if self._interrupted:
                self._done = True
                self._result = {"status": "interrupted", "summary": "Run interrupted"}
                break

            has_tool_use = any(block.type == "tool_use" for block in response.content)

            text_parts = []
            tool_results = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    self._emit("agent_message", {"content": block.text})

                elif block.type == "tool_use":
                    tool_def = self._find_tool(block.name)
                    self._emit(
                        "tool_call",
                        {
                            "tool": block.name,
                            "input": block.input,
                            "id": block.id,
                        },
                    )

                    if tool_def is None:
                        result_str = f"Error: unknown tool '{block.name}'"
                        tool_content = result_str
                    else:
                        try:
                            result = await tool_def.handler(**block.input)
                            if isinstance(result, list):
                                tool_content = result
                                result_str = "[Media Content Array]"
                            else:
                                tool_content = (
                                    json.dumps(result)
                                    if not isinstance(result, str)
                                    else result
                                )
                                result_str = tool_content
                        except Exception as exc:
                            result_str = f"Error: {exc}"
                            tool_content = result_str
                            logger.exception("Tool %s failed", block.name)

                    self._emit(
                        "tool_result",
                        {
                            "tool": block.name,
                            "id": block.id,
                            "result": result_str[:5000],
                        },
                    )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_content,
                        }
                    )

            if has_tool_use:
                self._messages.append(
                    {"role": "assistant", "content": response.content}
                )
                self._messages.append({"role": "user", "content": tool_results})
                continue

            # No tool use — agent is done
            final_text = "\n".join(text_parts)
            if not self._done:
                self._result = self._parse_output(final_text)
            self._emit("status_change", {"status": f"{self.role}_completed"})
            return AgentOutput(role=self.role, result=self._result, events=self._events)

        if self._done:
            self._emit("status_change", {"status": f"{self.role}_completed"})
            return AgentOutput(role=self.role, result=self._result, events=self._events)

        self._emit(
            "error", {"message": f"Max iterations ({self.max_iterations}) reached"}
        )
        return AgentOutput(
            role=self.role,
            result={"error": "max_iterations_reached"},
            events=self._events,
        )

    def mark_done(self, result: dict) -> str:
        """Called by the 'complete' tool handler to signal completion."""
        self._done = True
        self._result = result
        return "Session complete."

    async def interrupt(self) -> None:
        self._interrupted = True
        self._done = True
        try:
            await self._client.close()
        except Exception:
            logger.exception("Failed to close model client during interrupt")

    def _parse_output(self, text: str) -> dict:
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        return {"summary": text}
