from __future__ import annotations

import json
from typing import Any

from agent_control import ControlSteerError, ControlViolationError, control
from galileo import log
from galileo.openai import openai

from .config import Settings
from .models import Scope
from .prompts import SYSTEM_PROMPT
from .security import compact_json
from .tools import TOOL_SCHEMAS, ToolRegistry


class EvalOpsAgent:
    def __init__(self, settings: Settings, scope: Scope, tools: ToolRegistry) -> None:
        self.settings = settings
        self.scope = scope
        self.tools = tools
        self.client = openai.OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            max_retries=1,
            timeout=45,
        )
        scope_prompt = (
            f"\nSelected project: {scope.project_name}\n"
            f"Selected source Log Stream: {scope.source_stream_name}\n"
            f"Maximum lookback: {settings.max_lookback_days} days\n"
            f"Maximum traces per search: {settings.max_traces_per_query}\n"
            f"Maximum detailed traces: {settings.max_detailed_traces}\n"
        )
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT + scope_prompt}
        ]

    @log(span_type="agent", name="evalops_user_request_control")
    @control(step_name="evalops_user_request")
    def guard_user_request(self, user_input: str) -> str:
        return user_input

    @log(span_type="agent", name="evalops_agent_turn")
    def chat_turn(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        tool_calls_used = 0
        while True:
            response = self.client.chat.completions.create(
                model=self.settings.model,
                messages=self.messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_completion_tokens=self.settings.max_completion_tokens,
            )
            message = response.choices[0].message
            assistant_message = message.model_dump(exclude_none=True)
            self.messages.append(assistant_message)
            if not message.tool_calls:
                return message.content or "I could not produce an answer from the available evidence."
            budget_exhausted = False
            for index, tool_call in enumerate(message.tool_calls):
                if tool_calls_used >= self.settings.max_tool_calls_per_turn:
                    budget_exhausted = True
                    result = {
                        "ok": False,
                        "error": (
                            "The configured per-turn tool-call limit was reached; "
                            "this tool was not executed."
                        ),
                    }
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": compact_json(
                                result,
                                self.settings.secret_values(),
                                self.settings.max_output_chars,
                            ),
                        }
                    )
                    continue
                tool_calls_used += 1
                try:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    result = {"ok": False, "error": f"Invalid tool arguments: {exc}"}
                else:
                    try:
                        result = self.tools.execute(tool_call.function.name, arguments)
                    except (ControlSteerError, ControlViolationError) as exc:
                        # Preserve a structurally valid tool-call conversation before
                        # handing the control decision to the bounded retry handler.
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": compact_json(
                                    {"ok": False, "controlled": True, "error": str(exc)},
                                    self.settings.secret_values(),
                                    self.settings.max_output_chars,
                                ),
                            }
                        )
                        for pending in message.tool_calls[index + 1 :]:
                            self.messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": pending.id,
                                    "content": compact_json(
                                        {
                                            "ok": False,
                                            "controlled": True,
                                            "error": (
                                                "Not executed because Agent Control "
                                                "interrupted the tool batch."
                                            ),
                                        },
                                        self.settings.secret_values(),
                                        self.settings.max_output_chars,
                                    ),
                                }
                            )
                        raise
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": compact_json(
                            result,
                            self.settings.secret_values(),
                            self.settings.max_output_chars,
                        ),
                    }
                )
            if budget_exhausted or tool_calls_used >= self.settings.max_tool_calls_per_turn:
                final = self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=self.messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="none",
                    max_completion_tokens=self.settings.max_completion_tokens,
                )
                final_message = final.choices[0].message
                self.messages.append(final_message.model_dump(exclude_none=True))
                return final_message.content or (
                    "I stopped after the configured limit of "
                    f"{self.settings.max_tool_calls_per_turn} tool calls."
                )

    def run_with_steering(self, user_input: str) -> str:
        steering_attempts = 0
        current_input = user_input
        while True:
            try:
                controlled_input = self.guard_user_request(current_input)
                return self.chat_turn(controlled_input)
            except ControlViolationError as exc:
                return f"Blocked by Agent Control ({exc.control_name}): {exc.message}"
            except ControlSteerError as exc:
                if steering_attempts >= self.settings.max_steering_retries:
                    return (
                        "Agent Control requested another correction, but the configured "
                        "steering retry limit was reached."
                    )
                steering_attempts += 1
                current_input = (
                    "Correct the previous approach using this trusted Agent Control guidance:\n"
                    f"{exc.steering_context}\n\nOriginal user request:\n{user_input}"
                )
