from __future__ import annotations

import unittest
from pathlib import Path

from evalops_agent.config import ConfigurationError, Settings


def values(**overrides: str) -> dict[str, str]:
    base = {
        "GALILEO_API_URL": "https://api.example.test",
        "GALILEO_CONSOLE_URL": "https://console.example.test",
        "GALILEO_API_KEY": "galileo-secret",
        "GALILEO_PROJECT": "project-a",
        "GALILEO_LOG_STREAM": "production",
        "OPENAI_API_KEY": "openai-secret",
        "EVALOPS_MODEL": "test-model",
        "AGENT_CONTROL_URL": "https://control.example.test",
        "AGENT_CONTROL_API_KEY_HEADER": "Galileo-API-Key",
    }
    base.update(overrides)
    return base


class SettingsTests(unittest.TestCase):
    def test_defaults_are_cost_bounded(self) -> None:
        settings = Settings.from_mapping(values())
        self.assertEqual(settings.max_traces_per_query, 20)
        self.assertEqual(settings.max_detailed_traces, 5)
        self.assertEqual(settings.max_experiment_rows, 20)
        self.assertEqual(settings.max_management_streams, 10)
        self.assertEqual(settings.max_management_resources, 20)
        self.assertEqual(settings.max_session_sample, 5)
        self.assertEqual(settings.max_coverage_rows, 30)
        self.assertEqual(settings.max_generation_calls, 50)
        self.assertEqual(settings.max_evaluator_calls, 100)

    def test_rejects_api_key_as_header_name(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping(
                values(AGENT_CONTROL_API_KEY_HEADER="galileo-secret")
            )

    def test_public_summary_has_no_secrets(self) -> None:
        settings = Settings.from_mapping(values())
        rendered = repr(settings.public_summary())
        self.assertNotIn("galileo-secret", rendered)
        self.assertNotIn("openai-secret", rendered)

    def test_candidate_limit_must_cover_result_limit(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping(
                values(
                    EVALOPS_MAX_TRACES_PER_QUERY="20",
                    EVALOPS_MAX_TRACE_CANDIDATES="10",
                )
            )

    def test_rejects_invalid_runtime_auth_mode(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping(
                values(AGENT_CONTROL_RUNTIME_AUTH_MODE="unsupported")
            )

    def test_rejects_relative_service_url(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping(values(AGENT_CONTROL_URL="control.local"))

    def test_requires_separate_source_and_telemetry_streams(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping(
                values(
                    GALILEO_LOG_STREAM="evalops-agent",
                    EVALOPS_LOG_STREAM="evalops-agent",
                )
            )

    def test_env_example_contains_all_required_deployment_keys(self) -> None:
        example = (
            Path(__file__).resolve().parents[1] / ".env.example"
        ).read_text(encoding="utf-8")
        keys = {
            line.split("=", 1)[0]
            for line in example.splitlines()
            if line and not line.startswith("#") and "=" in line
        }
        self.assertTrue(
            {
                "GALILEO_API_URL",
                "GALILEO_CONSOLE_URL",
                "GALILEO_API_KEY",
                "GALILEO_PROJECT",
                "GALILEO_LOG_STREAM",
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "EVALOPS_MODEL",
                "AGENT_CONTROL_URL",
                "AGENT_CONTROL_API_KEY_HEADER",
                "AGENT_CONTROL_RUNTIME_AUTH_MODE",
                "EVALOPS_AGENT_NAME",
                "EVALOPS_LOG_STREAM",
            }.issubset(keys)
        )


if __name__ == "__main__":
    unittest.main()
