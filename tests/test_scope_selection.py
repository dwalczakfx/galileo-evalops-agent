from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from evalops_agent.cli import build_parser, select_scope
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
        }
    )


class ScopeSelectionTests(unittest.TestCase):
    def test_configured_scope_is_used_without_prompting(self) -> None:
        project = SimpleNamespace(id="project-id", name="project-a")
        source = SimpleNamespace(id="source-id", name="production")
        telemetry = SimpleNamespace(id="telemetry-id", name="evalops-agent")
        service = MagicMock()
        service.get_project.return_value = project
        service.get_log_stream.side_effect = (
            lambda _project_id, name: source if name == "production" else telemetry
        )

        with patch("builtins.input") as user_input:
            scope = select_scope(
                settings(),
                service,
                project_arg=None,
                stream_arg=None,
                select_interactively=False,
                allow_recovery=True,
            )

        user_input.assert_not_called()
        service.list_projects.assert_not_called()
        service.list_log_streams.assert_not_called()
        self.assertEqual(scope.project_name, "project-a")
        self.assertEqual(scope.source_stream_name, "production")

    def test_select_scope_opens_project_and_stream_pickers(self) -> None:
        first_project = SimpleNamespace(id="project-a-id", name="project-a")
        selected_project = SimpleNamespace(id="project-b-id", name="project-b")
        selected_stream = SimpleNamespace(id="staging-id", name="staging")
        telemetry = SimpleNamespace(id="telemetry-id", name="evalops-agent")
        service = MagicMock()
        service.list_projects.return_value = [first_project, selected_project]
        service.list_log_streams.return_value = [selected_stream]
        service.get_log_stream.return_value = telemetry

        with patch("builtins.input", side_effect=["2", "1"]):
            scope = select_scope(
                settings(),
                service,
                project_arg=None,
                stream_arg=None,
                select_interactively=True,
                allow_recovery=True,
            )

        service.get_project.assert_not_called()
        service.list_log_streams.assert_called_once_with("project-b-id")
        self.assertEqual(scope.project_name, "project-b")
        self.assertEqual(scope.source_stream_name, "staging")

    def test_invalid_scope_fails_cleanly_when_picker_is_unavailable(self) -> None:
        service = MagicMock()
        service.get_project.return_value = None

        with self.assertRaisesRegex(LookupError, "--select-scope"):
            select_scope(
                settings(),
                service,
                project_arg=None,
                stream_arg=None,
                select_interactively=False,
                allow_recovery=False,
            )

        service.list_projects.assert_not_called()

    def test_select_scope_is_accepted_before_or_after_command(self) -> None:
        parser = build_parser()
        for argv in (["--select-scope", "chat"], ["chat", "--select-scope"]):
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertTrue(args.select_scope)


if __name__ == "__main__":
    unittest.main()
