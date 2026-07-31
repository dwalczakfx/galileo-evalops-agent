from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = APP_DIR / ".env"
HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
RUNTIME_AUTH_MODES = {"auto", "none", "api_key", "jwt"}


class ConfigurationError(ValueError):
    """Raised when required configuration is missing or unsafe."""


def _int_value(values: Mapping[str, str], key: str, default: int, minimum: int, maximum: int) -> int:
    raw = values.get(key, str(default))
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{key} must be an integer.") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigurationError(f"{key} must be between {minimum} and {maximum}.")
    return parsed


def _first(values: Mapping[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = values.get(key)
        if value:
            return value
    return default


def _validate_http_url(name: str, value: str | None, *, required: bool) -> None:
    if not value:
        if required:
            raise ConfigurationError(f"{name} is required.")
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"{name} must be an absolute http:// or https:// URL.")


@dataclass(frozen=True)
class Settings:
    galileo_api_url: str
    galileo_console_url: str
    galileo_api_key: str
    default_project: str
    default_source_stream: str
    telemetry_stream: str
    demo_stream: str
    openai_api_key: str
    openai_base_url: str | None
    model: str
    max_completion_tokens: int
    agent_control_url: str | None
    agent_control_api_key_header: str
    agent_control_runtime_auth_mode: str
    agent_name: str
    default_lookback_hours: int
    max_lookback_days: int
    max_traces_per_query: int
    max_trace_candidates: int
    max_detailed_traces: int
    max_dataset_rows: int
    max_experiment_rows: int
    max_tool_calls_per_turn: int
    max_steering_retries: int
    max_output_chars: int
    max_management_streams: int
    max_management_resources: int
    max_session_sample: int
    max_coverage_rows: int
    max_generation_calls: int
    max_evaluator_calls: int
    env_file: Path

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Settings":
        selected = Path(
            env_file
            or os.environ.get("EVALOPS_ENV_FILE")
            or DEFAULT_ENV_FILE
        ).expanduser()
        if selected.exists():
            load_dotenv(selected, override=False)
        return cls.from_mapping(os.environ, selected)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str], env_file: str | Path = DEFAULT_ENV_FILE) -> "Settings":
        settings = cls(
            galileo_api_url=_first(values, "GALILEO_API_URL"),
            galileo_console_url=_first(values, "GALILEO_CONSOLE_URL"),
            galileo_api_key=_first(values, "GALILEO_API_KEY"),
            default_project=_first(values, "GALILEO_PROJECT", "GALILEO_PROJECT_NAME"),
            default_source_stream=_first(values, "GALILEO_LOG_STREAM"),
            telemetry_stream=_first(values, "EVALOPS_LOG_STREAM", default="evalops-agent"),
            demo_stream=_first(values, "EVALOPS_DEMO_STREAM", default="evalops-demo-source"),
            openai_api_key=_first(values, "OPENAI_API_KEY"),
            openai_base_url=_first(values, "OPENAI_BASE_URL") or None,
            model=_first(values, "EVALOPS_MODEL"),
            max_completion_tokens=_int_value(values, "EVALOPS_MAX_COMPLETION_TOKENS", 800, 64, 8000),
            agent_control_url=_first(values, "AGENT_CONTROL_URL") or None,
            agent_control_api_key_header=_first(
                values,
                "AGENT_CONTROL_API_KEY_HEADER",
                "API_KEY_HEADER",
                default="Galileo-API-Key",
            ),
            agent_control_runtime_auth_mode=_first(
                values,
                "AGENT_CONTROL_RUNTIME_AUTH_MODE",
                default="auto",
            ),
            agent_name=_first(values, "EVALOPS_AGENT_NAME", default="galileo-evalops-agent"),
            default_lookback_hours=_int_value(values, "EVALOPS_DEFAULT_LOOKBACK_HOURS", 24, 1, 168),
            max_lookback_days=_int_value(values, "EVALOPS_MAX_LOOKBACK_DAYS", 7, 1, 90),
            max_traces_per_query=_int_value(values, "EVALOPS_MAX_TRACES_PER_QUERY", 20, 1, 100),
            max_trace_candidates=_int_value(values, "EVALOPS_MAX_TRACE_CANDIDATES", 50, 1, 100),
            max_detailed_traces=_int_value(values, "EVALOPS_MAX_DETAILED_TRACES", 5, 1, 20),
            max_dataset_rows=_int_value(values, "EVALOPS_MAX_DATASET_ROWS", 20, 1, 100),
            max_experiment_rows=_int_value(values, "EVALOPS_MAX_EXPERIMENT_ROWS", 20, 1, 100),
            max_tool_calls_per_turn=_int_value(values, "EVALOPS_MAX_TOOL_CALLS_PER_TURN", 8, 1, 20),
            max_steering_retries=_int_value(values, "EVALOPS_MAX_STEERING_RETRIES", 2, 0, 5),
            max_output_chars=_int_value(values, "EVALOPS_MAX_OUTPUT_CHARS", 12000, 1000, 50000),
            max_management_streams=_int_value(
                values, "EVALOPS_MAX_MANAGEMENT_STREAMS", 10, 1, 25
            ),
            max_management_resources=_int_value(
                values, "EVALOPS_MAX_MANAGEMENT_RESOURCES", 20, 5, 50
            ),
            max_session_sample=_int_value(
                values, "EVALOPS_MAX_SESSION_SAMPLE", 5, 1, 20
            ),
            max_coverage_rows=_int_value(
                values, "EVALOPS_MAX_COVERAGE_ROWS", 30, 1, 100
            ),
            max_generation_calls=_int_value(
                values, "EVALOPS_MAX_GENERATION_CALLS", 50, 1, 10000
            ),
            max_evaluator_calls=_int_value(
                values, "EVALOPS_MAX_EVALUATOR_CALLS", 100, 1, 50000
            ),
            env_file=Path(env_file),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        required = {
            "GALILEO_API_URL": self.galileo_api_url,
            "GALILEO_API_KEY": self.galileo_api_key,
            "GALILEO_PROJECT or GALILEO_PROJECT_NAME": self.default_project,
            "GALILEO_LOG_STREAM": self.default_source_stream,
            "OPENAI_API_KEY": self.openai_api_key,
            "EVALOPS_MODEL": self.model,
            "AGENT_CONTROL_URL": self.agent_control_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ConfigurationError(
                "Missing required configuration: "
                + ", ".join(missing)
                + f". Copy {APP_DIR / '.env.example'} to {self.env_file} "
                "and fill the required values, or pass --env-file."
            )
        _validate_http_url("GALILEO_API_URL", self.galileo_api_url, required=True)
        _validate_http_url(
            "GALILEO_CONSOLE_URL",
            self.galileo_console_url,
            required=False,
        )
        _validate_http_url("OPENAI_BASE_URL", self.openai_base_url, required=False)
        _validate_http_url(
            "AGENT_CONTROL_URL",
            self.agent_control_url,
            required=True,
        )
        if not HEADER_NAME_PATTERN.fullmatch(self.agent_control_api_key_header):
            raise ConfigurationError("AGENT_CONTROL_API_KEY_HEADER is not a valid HTTP header name.")
        if self.agent_control_api_key_header == self.galileo_api_key:
            raise ConfigurationError(
                "AGENT_CONTROL_API_KEY_HEADER contains the API key. "
                "Set it to an HTTP header name such as Galileo-API-Key."
            )
        if self.agent_control_runtime_auth_mode not in RUNTIME_AUTH_MODES:
            raise ConfigurationError(
                "AGENT_CONTROL_RUNTIME_AUTH_MODE must be one of: "
                + ", ".join(sorted(RUNTIME_AUTH_MODES))
                + "."
            )
        if self.max_trace_candidates < self.max_traces_per_query:
            raise ConfigurationError(
                "EVALOPS_MAX_TRACE_CANDIDATES must be greater than or equal to "
                "EVALOPS_MAX_TRACES_PER_QUERY."
            )
        if self.default_source_stream == self.telemetry_stream:
            raise ConfigurationError(
                "EVALOPS_LOG_STREAM must differ from GALILEO_LOG_STREAM so the "
                "agent does not analyze and write telemetry to the same stream."
            )

    @property
    def max_lookback_hours(self) -> int:
        return self.max_lookback_days * 24

    def public_summary(self) -> dict[str, object]:
        return {
            "env_file": str(self.env_file),
            "galileo_api_url": self.galileo_api_url,
            "galileo_console_url": self.galileo_console_url,
            "default_project": self.default_project,
            "default_source_stream": self.default_source_stream,
            "telemetry_stream": self.telemetry_stream,
            "demo_stream": self.demo_stream,
            "model": self.model,
            "management_stream_limit": self.max_management_streams,
            "management_resource_limit": self.max_management_resources,
            "generation_call_limit": self.max_generation_calls,
            "evaluator_call_limit": self.max_evaluator_calls,
            "agent_control_url_configured": bool(self.agent_control_url),
            "agent_control_header_valid": bool(
                HEADER_NAME_PATTERN.fullmatch(self.agent_control_api_key_header)
            ),
        }

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.galileo_api_key, self.openai_api_key) if value)
