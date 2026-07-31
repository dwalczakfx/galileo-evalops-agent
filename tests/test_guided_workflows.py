from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from evalops_agent.cli import build_parser, main, print_app_intro
from evalops_agent.models import Scope
from evalops_agent.presentation import (
    DEMO_OPTIONS,
    choose_demo_option,
)
from evalops_agent.use_cases import (
    GUIDED_USE_CASES,
    choose_use_case,
)


class GuidedWorkflowTests(unittest.TestCase):
    def test_guided_use_case_keys_are_unique(self) -> None:
        keys = [use_case.key for use_case in GUIDED_USE_CASES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertGreaterEqual(len(keys), 5)

    def test_guided_use_case_can_be_selected_by_number(self) -> None:
        selected = choose_use_case(lambda _: "1")
        self.assertEqual(selected, GUIDED_USE_CASES[0])

    def test_custom_question_returns_no_predefined_use_case(self) -> None:
        self.assertIsNone(choose_use_case(lambda _: "0"))

    def test_demo_options_have_presenter_ready_steps(self) -> None:
        keys = [option.key for option in DEMO_OPTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        for option in DEMO_OPTIONS:
            self.assertTrue(option.steps)
            for step in option.steps:
                self.assertTrue(step.prompt)
                self.assertTrue(step.presenter_note)
                self.assertTrue(step.capability)

    def test_demo_can_be_selected_by_key(self) -> None:
        selected = choose_demo_option(lambda _: "quality-drop")
        self.assertEqual(selected.key, "quality-drop")

    def test_cli_accepts_exact_demo_scenario(self) -> None:
        args = build_parser().parse_args(
            ["demo", "--scenario", "quality-drop", "--print-only"]
        )
        self.assertEqual(args.command, "demo")
        self.assertEqual(args.scenario, "quality-drop")
        self.assertTrue(args.print_only)

    def test_setup_accepts_agent_control_install_option(self) -> None:
        args = build_parser().parse_args(["setup", "--with-agent-control"])
        self.assertEqual(args.command, "setup")
        self.assertTrue(args.with_agent_control)

    def test_chat_intro_explains_purpose_and_safety_before_menu(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            print_app_intro(
                Scope(
                    project_name="project-a",
                    project_id="project-id",
                    source_stream_name="production",
                    source_stream_id="stream-id",
                    telemetry_stream_name="evalops-agent",
                    telemetry_stream_id="telemetry-id",
                )
            )
        rendered = output.getvalue()
        self.assertIn("Purpose:", rendered)
        self.assertIn("every remote", rendered)
        self.assertIn("evalops-agent", rendered)

    @patch("evalops_agent.cli.Settings.load")
    def test_demo_preview_does_not_load_credentials(self, load_settings) -> None:
        with redirect_stdout(StringIO()):
            with self.assertRaises(SystemExit) as exit_result:
                main(
                    [
                        "demo",
                        "--scenario",
                        "project-doctor",
                        "--print-only",
                    ]
                )
        self.assertEqual(exit_result.exception.code, 0)
        load_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
