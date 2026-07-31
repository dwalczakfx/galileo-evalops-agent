from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from evalops_agent.config import Settings
from evalops_agent.instrumentation import InstrumentedSession, TelemetryUploadError
from evalops_agent.models import Scope


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


SCOPE = Scope(
    project_name="project-a",
    project_id="project-id",
    source_stream_name="production",
    source_stream_id="source-id",
    telemetry_stream_name="evalops-agent",
    telemetry_stream_id="telemetry-id",
)


class InstrumentationTests(unittest.TestCase):
    @patch("evalops_agent.instrumentation.agent_control.shutdown")
    @patch("evalops_agent.instrumentation.agent_control.init")
    @patch("evalops_agent.instrumentation.galileo_context")
    def test_session_binds_controls_and_cleans_up(
        self,
        context: MagicMock,
        init_control: MagicMock,
        shutdown_control: MagicMock,
    ) -> None:
        context_manager = MagicMock()
        logger = MagicMock()
        context.return_value = context_manager
        context.get_logger_instance.return_value = logger

        logger.flush.return_value = [{"id": "trace-id"}]
        with patch.dict(
            os.environ,
            {"AGENT_CONTROL_RUNTIME_AUTH_MODE": "api_key"},
            clear=False,
        ):
            with InstrumentedSession(settings(), SCOPE, "test-session") as session:
                session.ensure_started()
                self.assertEqual(session.flush_turn(), 1)
                self.assertEqual(
                    os.environ["AGENT_CONTROL_RUNTIME_AUTH_MODE"],
                    "auto",
                )
            self.assertEqual(
                os.environ["AGENT_CONTROL_RUNTIME_AUTH_MODE"],
                "api_key",
            )

        context.assert_called_once_with(
            project="project-a",
            log_stream="evalops-agent",
        )
        logger.enable_agent_control.assert_called_once()
        init_control.assert_called_once()
        self.assertEqual(init_control.call_args.kwargs["target_id"], "telemetry-id")
        self.assertEqual(init_control.call_args.kwargs["target_type"], "log_stream")
        self.assertEqual(init_control.call_args.kwargs["agent_version"], "0.3.0")
        context.start_session.assert_called_once()
        context.clear_session.assert_called_once()
        self.assertEqual(logger.flush.call_count, 2)
        logger.flush.assert_any_call(on_error=unittest.mock.ANY)
        logger.disable_agent_control.assert_called_once()
        shutdown_control.assert_called_once()
        context_manager.__exit__.assert_called_once()

    @patch("evalops_agent.instrumentation.agent_control.shutdown")
    @patch("evalops_agent.instrumentation.agent_control.init")
    @patch("evalops_agent.instrumentation.galileo_context")
    def test_turn_flush_surfaces_ingestion_failure(
        self,
        context: MagicMock,
        init_control: MagicMock,
        shutdown_control: MagicMock,
    ) -> None:
        context_manager = MagicMock()
        logger = MagicMock()
        context.return_value = context_manager
        context.get_logger_instance.return_value = logger

        flush_attempt = 0

        def failed_flush(*args, **kwargs):
            nonlocal flush_attempt
            flush_attempt += 1
            on_error = kwargs.get("on_error")
            if flush_attempt == 1 and on_error is not None:
                on_error(RuntimeError("ingest rejected"))
                return []
            return [{"id": "retry-uploaded"}]

        logger.flush.side_effect = failed_flush
        with InstrumentedSession(settings(), SCOPE, "test-session") as session:
            session.ensure_started()
            with self.assertRaisesRegex(TelemetryUploadError, "ingest rejected"):
                session.flush_turn()

    @patch("evalops_agent.instrumentation.agent_control.shutdown")
    @patch("evalops_agent.instrumentation.agent_control.init")
    @patch("evalops_agent.instrumentation.galileo_context")
    def test_turn_flush_rejects_empty_capture(
        self,
        context: MagicMock,
        init_control: MagicMock,
        shutdown_control: MagicMock,
    ) -> None:
        context_manager = MagicMock()
        logger = MagicMock()
        context.return_value = context_manager
        context.get_logger_instance.return_value = logger
        logger.flush.side_effect = [[], []]

        with InstrumentedSession(settings(), SCOPE, "test-session") as session:
            session.ensure_started()
            with self.assertRaisesRegex(TelemetryUploadError, "captured no trace"):
                session.flush_turn()

    @patch("evalops_agent.instrumentation.agent_control.shutdown")
    @patch("evalops_agent.instrumentation.agent_control.init")
    @patch("evalops_agent.instrumentation.galileo_context")
    def test_shutdown_upload_failure_is_visible(
        self,
        context: MagicMock,
        init_control: MagicMock,
        shutdown_control: MagicMock,
    ) -> None:
        context_manager = MagicMock()
        logger = MagicMock()
        context.return_value = context_manager
        context.get_logger_instance.return_value = logger

        def failed_flush(*args, **kwargs):
            callback = kwargs.get("on_error")
            if callback is not None:
                callback(RuntimeError("final ingest rejected"))
            return []

        logger.flush.side_effect = failed_flush
        with self.assertRaisesRegex(TelemetryUploadError, "final ingest rejected"):
            with InstrumentedSession(settings(), SCOPE, "test-session") as session:
                session.ensure_started()

    @patch("evalops_agent.instrumentation.agent_control.shutdown")
    @patch("evalops_agent.instrumentation.agent_control.init")
    @patch("evalops_agent.instrumentation.galileo_context")
    def test_quit_without_request_does_not_create_empty_session(
        self,
        context: MagicMock,
        init_control: MagicMock,
        shutdown_control: MagicMock,
    ) -> None:
        context_manager = MagicMock()
        logger = MagicMock()
        context.return_value = context_manager
        context.get_logger_instance.return_value = logger

        with InstrumentedSession(settings(), SCOPE, "test-session"):
            pass

        context.start_session.assert_not_called()
        context.clear_session.assert_not_called()
        logger.flush.assert_not_called()
        shutdown_control.assert_called_once()

    def test_requires_dedicated_telemetry_stream(self) -> None:
        scope = Scope(
            project_name="project-a",
            project_id="project-id",
            source_stream_name="production",
            source_stream_id="source-id",
            telemetry_stream_name="evalops-agent",
            telemetry_stream_id=None,
        )
        with self.assertRaises(ValueError):
            InstrumentedSession(settings(), scope, "test-session")


if __name__ == "__main__":
    unittest.main()
