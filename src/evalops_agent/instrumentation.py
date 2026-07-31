from __future__ import annotations

import os
import sys
import uuid
from typing import Any

import agent_control
from galileo import galileo_context

from . import __version__
from .config import Settings
from .models import Scope


class TelemetryUploadError(RuntimeError):
    """Raised when a completed agent turn cannot be uploaded to Galileo."""


class InstrumentedSession:
    def __init__(self, settings: Settings, scope: Scope, session_name: str) -> None:
        if not scope.telemetry_stream_id:
            raise ValueError("The EvalOps telemetry Log Stream has not been created.")
        self.settings = settings
        self.scope = scope
        self.session_name = session_name
        self._context: Any = None
        self._logger: Any = None
        self._agent_control_initialized = False
        self._session_started = False
        self._had_runtime_auth_mode = False
        self._previous_runtime_auth_mode: str | None = None

    def _set_runtime_auth_mode(self) -> None:
        key = "AGENT_CONTROL_RUNTIME_AUTH_MODE"
        self._had_runtime_auth_mode = key in os.environ
        self._previous_runtime_auth_mode = os.environ.get(key)
        os.environ[key] = self.settings.agent_control_runtime_auth_mode

    def _restore_runtime_auth_mode(self) -> None:
        key = "AGENT_CONTROL_RUNTIME_AUTH_MODE"
        if self._had_runtime_auth_mode and self._previous_runtime_auth_mode is not None:
            os.environ[key] = self._previous_runtime_auth_mode
        else:
            os.environ.pop(key, None)

    def __enter__(self) -> "InstrumentedSession":
        self._context = galileo_context(
            project=self.scope.project_name,
            log_stream=self.scope.telemetry_stream_name,
        )
        self._context.__enter__()
        try:
            self._logger = galileo_context.get_logger_instance()
            self._set_runtime_auth_mode()
            self._logger.enable_agent_control()
            agent_control.init(
                agent_name=self.settings.agent_name,
                agent_description="Cost-bounded Galileo EvalOps operator",
                agent_version=__version__,
                server_url=self.settings.agent_control_url,
                api_key=self.settings.galileo_api_key,
                api_key_header=self.settings.agent_control_api_key_header,
                observability_enabled=True,
                observability_sink_name="registered",
                target_type="log_stream",
                target_id=self.scope.telemetry_stream_id,
            )
            self._agent_control_initialized = True
        except Exception:
            try:
                agent_control.shutdown()
            except Exception:
                pass
            if self._logger is not None:
                try:
                    self._logger.disable_agent_control()
                except Exception:
                    pass
            self._restore_runtime_auth_mode()
            try:
                self._context.__exit__(*sys.exc_info())
            except Exception:
                pass
            raise
        return self

    def ensure_started(self) -> None:
        """Start the Galileo session only when the first real request is run."""
        if self._session_started:
            return
        metadata = {
            "application": "evalops-agent",
            "source_project": self.scope.project_name,
            "source_log_stream": self.scope.source_stream_name,
        }
        galileo_context.start_session(
            name=self.session_name,
            external_id=str(uuid.uuid4()),
            metadata=metadata,
        )
        self._session_started = True

    def flush_turn(self) -> int:
        """Upload a completed turn and fail visibly when ingestion does not succeed."""
        if self._logger is None:
            raise TelemetryUploadError("The Galileo logger is not initialized.")
        if not self._session_started:
            raise TelemetryUploadError(
                "The Galileo session has not started because no agent request ran."
            )

        errors: list[Exception] = []
        uploaded = self._logger.flush(on_error=errors.append)
        if errors:
            raise TelemetryUploadError(
                f"Galileo trace upload failed: {errors[0]}"
            ) from errors[0]

        uploaded_count = len(uploaded or [])
        if uploaded_count == 0:
            raise TelemetryUploadError(
                "The agent turn completed, but the Galileo logger captured no trace."
            )
        return uploaded_count

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        cleanup_errors: list[Exception] = []
        try:
            if self._agent_control_initialized:
                try:
                    # Stops the policy refresh loop and flushes pending control
                    # observability events before Galileo performs its final flush.
                    agent_control.shutdown()
                except Exception as shutdown_error:
                    cleanup_errors.append(shutdown_error)
                finally:
                    self._agent_control_initialized = False
            if self._logger is not None:
                # Upload any trace left by an interrupted turn. Normal completed
                # turns are flushed immediately by the CLI.
                if self._session_started:
                    try:
                        self._logger.flush(on_error=cleanup_errors.append)
                    except Exception as flush_error:
                        cleanup_errors.append(flush_error)
                try:
                    self._logger.disable_agent_control()
                except Exception as disable_error:
                    cleanup_errors.append(disable_error)
            if self._session_started:
                try:
                    galileo_context.clear_session()
                except Exception as session_error:
                    cleanup_errors.append(session_error)
        finally:
            self._restore_runtime_auth_mode()
            if self._context is not None:
                try:
                    self._context.__exit__(exc_type, exc, traceback)
                except Exception as context_error:
                    cleanup_errors.append(context_error)
        if exc_type is None and cleanup_errors:
            raise TelemetryUploadError(
                f"Instrumentation shutdown failed: {cleanup_errors[0]}"
            ) from cleanup_errors[0]
