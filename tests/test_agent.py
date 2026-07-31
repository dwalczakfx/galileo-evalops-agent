from __future__ import annotations

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace

from evalops_agent.agent import EvalOpsAgent
from evalops_agent.config import Settings


def settings() -> Settings:
    return Settings.from_mapping(
        {
            "GALILEO_API_URL": "https://api.example.test",
            "GALILEO_API_KEY": "galileo-secret",
            "GALILEO_PROJECT": "project-a",
            "GALILEO_LOG_STREAM": "production",
            "OPENAI_API_KEY": "openai-secret",
            "EVALOPS_MODEL": "test-model",
            "AGENT_CONTROL_URL": "https://control.example.test",
            "AGENT_CONTROL_API_KEY_HEADER": "Galileo-API-Key",
        }
    )


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        rendered = {"role": "assistant"}
        if self.content is not None:
            rendered["content"] = self.content
        if self.tool_calls is not None:
            rendered["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return rendered


class FakeCompletions:
    def __init__(self, messages):
        self._messages = iter(messages)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=next(self._messages))]
        )


class FakeTools:
    def __init__(self):
        self.executed = []

    def execute(self, name, arguments):
        self.executed.append((name, arguments))
        return {"ok": True}


class AgentTests(unittest.TestCase):
    def test_tool_budget_counts_calls_not_model_rounds(self) -> None:
        tool_calls = [
            SimpleNamespace(
                id=f"call-{index}",
                function=SimpleNamespace(
                    name="list_datasets",
                    arguments=json.dumps({}),
                ),
            )
            for index in range(2)
        ]
        completions = FakeCompletions(
            [
                FakeMessage(tool_calls=tool_calls),
                FakeMessage(content="Stopped safely after one tool call."),
            ]
        )
        agent = object.__new__(EvalOpsAgent)
        agent.settings = replace(settings(), max_tool_calls_per_turn=1)
        agent.tools = FakeTools()
        agent.messages = [{"role": "system", "content": "test"}]
        agent.client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        result = EvalOpsAgent.chat_turn.__wrapped__(agent, "inspect")

        self.assertEqual(result, "Stopped safely after one tool call.")
        self.assertEqual(len(agent.tools.executed), 1)
        self.assertEqual(completions.calls[-1]["tool_choice"], "none")
        tool_messages = [
            message for message in agent.messages if message["role"] == "tool"
        ]
        self.assertEqual(len(tool_messages), 2)
        self.assertIn("not executed", tool_messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
