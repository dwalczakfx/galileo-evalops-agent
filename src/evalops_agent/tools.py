from __future__ import annotations

import json
import re
import hashlib
import math
from typing import Any

from agent_control import ControlSteerError, ControlViolationError, control
from galileo import log

from .agent_control_api import AgentControlService
from .approvals import ApprovalDenied, ApprovalGate
from .config import Settings
from .galileo_api import GalileoService
from .management import (
    analyze_coverage,
    build_environment_diff,
    build_project_doctor_report,
    estimate_evaluation_budget,
    evaluate_release_gate,
)
from .models import BudgetExceeded, OperationPreview, Scope, TimeWindow
from .security import sanitize


SAFE_GROUP_BY = {
    "model",
    "prompt_version",
    "environment",
    "user_tier",
    "session_type",
    "status_code",
}
SAFE_COLUMN_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
SAFE_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")
UNSAFE_REGEX_EXTENSION = re.compile(r"\(\?(?:[=!<]|P[=<])|\\[1-9]")
NESTED_REGEX_QUANTIFIER = re.compile(
    r"\((?:[^()\\]|\\.)*(?:[|+*{])(?:[^()\\]|\\.)*\)\s*(?:[+*]|\{)"
)


def _compile_bounded_regex(pattern: str) -> re.Pattern[str]:
    """Compile the intentionally small regex subset used for local previews."""
    if len(pattern) > 200:
        raise BudgetExceeded("Regex pattern exceeds the 200-character safety limit.")
    if UNSAFE_REGEX_EXTENSION.search(pattern):
        raise ValueError(
            "Lookarounds, named groups, and backreferences are not supported "
            "in locally simulated controls."
        )
    if NESTED_REGEX_QUANTIFIER.search(pattern):
        raise ValueError(
            "Nested or ambiguous quantified groups are not supported because "
            "they can cause excessive regex runtime."
        )
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern: {exc}") from exc


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_available_metrics",
            "description": (
                "Profile configured metrics and actual numeric value coverage in one "
                "bounded recent trace sample. Prefer metrics_with_numeric_values "
                "when recommending an investigation."
            ),
            "parameters": {
                "type": "object",
                "properties": {"hours": {"type": "integer", "minimum": 1}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_metric_trend",
            "description": "Query already-computed aggregate metrics for the selected project and Log Stream.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "minimum": 1},
                    "group_by": {
                        "type": ["string", "null"],
                        "description": "Optional metadata or standard column for a bounded breakdown.",
                    },
                },
                "required": ["hours"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_low_scoring_traces",
            "description": "Return a bounded set below a 0–1 normalized quality threshold. Use search_metric_traces for high cost, token, or latency investigations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                    "hours": {"type": "integer", "minimum": 1},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["metric", "threshold", "hours", "limit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_metric_traces",
            "description": "Return a bounded recent sample where one metric is below or above a numeric threshold. Use below for quality failures and above for high cost, token use, or latency.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "comparison": {"type": "string", "enum": ["below", "above"]},
                    "threshold": {"type": "number"},
                    "hours": {"type": "integer", "minimum": 1},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["metric", "comparison", "threshold", "hours", "limit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trace_details",
            "description": "Inspect a trace returned by the immediately preceding bounded trace search.",
            "parameters": {
                "type": "object",
                "properties": {"trace_id": {"type": "string"}},
                "required": ["trace_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_datasets",
            "description": "List dataset metadata in the selected project.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_experiments",
            "description": "List experiment metadata and available aggregate results in the selected project.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_prompts",
            "description": "List prompt metadata in the selected project so the user never has to guess prompt names.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_experiments",
            "description": "Compare two existing experiments in the selected project and calculate numeric candidate-minus-baseline deltas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "baseline_name": {"type": "string"},
                    "candidate_name": {"type": "string"},
                },
                "required": ["baseline_name", "candidate_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_prompt_version",
            "description": "Approval-gated write: create a new version of an existing prompt by replacing or adding its system message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt_name": {"type": "string"},
                    "system_prompt": {"type": "string", "maxLength": 8000},
                },
                "required": ["prompt_name", "system_prompt"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_regression_dataset",
            "description": "Approval-gated write: create or extend a dataset from trace IDs returned by a prior search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_name": {"type": "string"},
                    "trace_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["dataset_name", "trace_ids"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_experiment",
            "description": "Approval-gated write: run a bounded experiment using an existing dataset and prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_name": {"type": "string"},
                    "dataset_name": {"type": "string"},
                    "prompt_name": {"type": "string"},
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                },
                "required": ["experiment_name", "dataset_name", "prompt_name", "metrics"],
                "additionalProperties": False,
            },
        },
    },
]


TOOL_SCHEMAS.extend(
    [
        {
            "type": "function",
            "function": {
                "name": "run_project_doctor",
                "description": (
                    "Run a bounded, rules-based health and hygiene audit of only "
                    "the selected Galileo project."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stale_days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 365,
                        }
                    },
                    "required": ["stale_days"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "estimate_evaluation_budget",
                "description": (
                    "Estimate generation and evaluator calls before running an "
                    "experiment or enabling a large evaluation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dataset_name": {"type": ["string", "null"]},
                        "rows": {"type": ["integer", "null"], "minimum": 1},
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 10,
                        },
                        "runs": {"type": "integer", "minimum": 1, "maximum": 10},
                        "sample_percent": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    "required": [
                        "dataset_name",
                        "rows",
                        "metrics",
                        "runs",
                        "sample_percent",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_dataset_coverage",
                "description": (
                    "Compare previously inspected failure traces with one small "
                    "dataset and identify likely regression-coverage gaps."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dataset_name": {"type": "string"},
                        "trace_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 20,
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "minimum": 0.05,
                            "maximum": 1,
                        },
                    },
                    "required": [
                        "dataset_name",
                        "trace_ids",
                        "similarity_threshold",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "evaluate_release_readiness",
                "description": (
                    "Apply explicit user-provided numeric release criteria to a "
                    "baseline-versus-candidate experiment comparison."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "baseline_name": {"type": "string"},
                        "candidate_name": {"type": "string"},
                        "criteria": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 10,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "metric": {"type": "string"},
                                    "source": {
                                        "type": "string",
                                        "enum": ["candidate", "baseline", "delta"],
                                    },
                                    "operator": {
                                        "type": "string",
                                        "enum": [">=", ">", "<=", "<"],
                                    },
                                    "value": {"type": "number"},
                                },
                                "required": [
                                    "metric",
                                    "source",
                                    "operator",
                                    "value",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": [
                        "baseline_name",
                        "candidate_name",
                        "criteria",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compare_project_environments",
                "description": (
                    "Compare the selected Galileo project with one exact target "
                    "project using bounded resource metadata and no trace copying."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_project_name": {"type": "string"},
                    },
                    "required": ["target_project_name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "bootstrap_missing_log_streams",
                "description": (
                    "Approval-gated write: create selected missing Log Streams from "
                    "the immediately preceding environment comparison."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_project_name": {"type": "string"},
                        "stream_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 10,
                        },
                    },
                    "required": ["target_project_name", "stream_names"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_agent_control_agents",
                "description": (
                    "List a bounded set of Agent Control agents so the user can "
                    "choose an exact attachment target without guessing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_agent_control",
                "description": (
                    "Build, validate, and locally simulate a regex-based Agent "
                    "Control proposal. This does not create the control."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string", "maxLength": 1000},
                        "selector_path": {
                            "type": "string",
                            "enum": ["input", "output"],
                        },
                        "regex_pattern": {"type": "string", "maxLength": 200},
                        "action": {
                            "type": "string",
                            "enum": ["observe", "steer", "deny"],
                        },
                        "stage": {
                            "type": "string",
                            "enum": ["pre", "post"],
                        },
                        "step_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 10,
                        },
                        "trace_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 10,
                        },
                    },
                    "required": [
                        "name",
                        "description",
                        "selector_path",
                        "regex_pattern",
                        "action",
                        "stage",
                        "step_names",
                        "trace_ids",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_agent_control_from_proposal",
                "description": (
                    "Approval-gated write: create a validated control proposal and "
                    "attach it to one exact Agent Control agent."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "agent_name": {"type": "string"},
                    },
                    "required": ["proposal_id", "agent_name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "accept_signal_handoff",
                "description": (
                    "Create a bounded investigation plan from user-provided Galileo "
                    "Signal context. No organization or Signals API scan is performed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "signal_name": {"type": "string"},
                        "metric": {"type": "string"},
                        "threshold": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "hours": {"type": "integer", "minimum": 1},
                        "signal_url": {"type": ["string", "null"]},
                        "notes": {"type": ["string", "null"], "maxLength": 2000},
                    },
                    "required": [
                        "signal_name",
                        "metric",
                        "threshold",
                        "hours",
                        "signal_url",
                        "notes",
                    ],
                    "additionalProperties": False,
                },
            },
        },
    ]
)


class ToolRegistry:
    def __init__(
        self,
        settings: Settings,
        scope: Scope,
        service: GalileoService,
        approval: ApprovalGate,
    ) -> None:
        self.settings = settings
        self.scope = scope
        self.service = service
        self.approval = approval
        self.control_service = AgentControlService(settings)
        self.allowed_trace_ids: set[str] = set()
        self.inspected_trace_ids: set[str] = set()
        self._cache: dict[str, Any] = {}

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "list_available_metrics": self.list_available_metrics,
            "query_metric_trend": self.query_metric_trend,
            "search_low_scoring_traces": self.search_low_scoring_traces,
            "search_metric_traces": self.search_metric_traces,
            "get_trace_details": self.get_trace_details,
            "list_datasets": self.list_datasets,
            "list_experiments": self.list_experiments,
            "list_prompts": self.list_prompts,
            "compare_experiments": self.compare_experiments,
            "create_prompt_version": self.create_prompt_version,
            "create_regression_dataset": self.create_regression_dataset,
            "run_experiment": self.run_experiment,
            "run_project_doctor": self.run_project_doctor,
            "estimate_evaluation_budget": self.estimate_evaluation_budget,
            "analyze_dataset_coverage": self.analyze_dataset_coverage,
            "evaluate_release_readiness": self.evaluate_release_readiness,
            "compare_project_environments": self.compare_project_environments,
            "bootstrap_missing_log_streams": self.bootstrap_missing_log_streams,
            "list_agent_control_agents": self.list_agent_control_agents,
            "propose_agent_control": self.propose_agent_control,
            "create_agent_control_from_proposal": self.create_agent_control_from_proposal,
            "accept_signal_handoff": self.accept_signal_handoff,
        }
        if name not in handlers:
            return {"ok": False, "error": f"Unknown tool {name!r}."}
        try:
            result = handlers[name](**arguments)
            return {"ok": True, "scope": self.scope.public_dict(), "result": result}
        except (ControlSteerError, ControlViolationError):
            raise
        except Exception as exc:
            return {
                "ok": False,
                "scope": self.scope.public_dict(),
                "error": sanitize(str(exc), self.settings.secret_values(), 1000),
            }

    @log(span_type="tool", name="galileo.list_available_metrics")
    def list_available_metrics(self, hours: int | None = None) -> dict[str, Any]:
        selected_hours = hours or self.settings.default_lookback_hours
        window = TimeWindow.recent_hours(
            selected_hours,
            self.settings.max_lookback_hours,
        )
        cache_key = json.dumps(["metric-profile", selected_hours])
        was_cached = cache_key in self._cache
        if cache_key not in self._cache:
            self._cache[cache_key] = self.service.profile_metric_values(
                self.scope,
                window,
                limit=self.settings.max_trace_candidates,
            )
        return {
            "cached": was_cached,
            **self._cache[cache_key],
            "note": (
                "This is one bounded recent sample from the selected Log Stream, "
                "not an exhaustive stream or organization scan."
            ),
        }

    @log(span_type="tool", name="galileo.query_metric_trend")
    def query_metric_trend(self, hours: int, group_by: str | None = None) -> dict[str, Any]:
        if group_by is not None and group_by not in SAFE_GROUP_BY:
            raise ValueError(
                f"group_by must be one of: {', '.join(sorted(SAFE_GROUP_BY))}."
            )
        window = TimeWindow.recent_hours(hours, self.settings.max_lookback_hours)
        cache_key = json.dumps(["metrics", hours, group_by])
        was_cached = cache_key in self._cache
        if cache_key not in self._cache:
            self._cache[cache_key] = self.service.query_metrics(
                self.scope,
                window,
                group_by=group_by,
                interval_minutes=60 if hours <= 48 else 1440,
            )
        return {
            "window": window.public_dict(),
            "cached": was_cached,
            "metrics": self._cache[cache_key],
        }

    @log(span_type="tool", name="galileo.search_low_scoring_traces")
    def search_low_scoring_traces(
        self,
        metric: str,
        threshold: float,
        hours: int,
        limit: int,
    ) -> dict[str, Any]:
        if not 0 <= threshold <= 1:
            raise ValueError("Metric threshold must be between 0 and 1.")
        if limit < 1:
            raise ValueError("Trace limit must be at least one.")
        if not SAFE_COLUMN_NAME.fullmatch(metric):
            raise ValueError("Metric name contains unsupported characters or is too long.")
        bounded_limit = min(limit, self.settings.max_traces_per_query)
        window = TimeWindow.recent_hours(hours, self.settings.max_lookback_hours)
        search_result = self.service.search_low_scoring_traces(
            self.scope,
            window,
            metric=metric,
            threshold=threshold,
            limit=bounded_limit,
        )
        traces = search_result["traces"]
        found_ids = {
            str(trace.get("id"))
            for trace in traces
            if isinstance(trace, dict) and trace.get("id")
        }
        self.allowed_trace_ids = found_ids
        return {
            "window": window.public_dict(),
            "metric": metric,
            "threshold": threshold,
            "requested_limit": limit,
            "applied_limit": bounded_limit,
            "count": len(traces),
            "traces": traces,
            "candidate_search": {
                key: value
                for key, value in search_result.items()
                if key != "traces"
            },
        }

    @log(span_type="tool", name="galileo.search_metric_traces")
    def search_metric_traces(
        self,
        metric: str,
        comparison: str,
        threshold: float,
        hours: int,
        limit: int,
    ) -> dict[str, Any]:
        if comparison not in {"below", "above"}:
            raise ValueError("comparison must be 'below' or 'above'.")
        if not math.isfinite(threshold):
            raise ValueError("Metric threshold must be a finite number.")
        if limit < 1:
            raise ValueError("Trace limit must be at least one.")
        if not SAFE_COLUMN_NAME.fullmatch(metric):
            raise ValueError("Metric name contains unsupported characters or is too long.")
        bounded_limit = min(limit, self.settings.max_traces_per_query)
        window = TimeWindow.recent_hours(hours, self.settings.max_lookback_hours)
        search_result = self.service.search_metric_traces(
            self.scope,
            window,
            metric=metric,
            comparison=comparison,
            threshold=threshold,
            limit=bounded_limit,
        )
        traces = search_result["traces"]
        self.allowed_trace_ids = {
            str(trace.get("id"))
            for trace in traces
            if isinstance(trace, dict) and trace.get("id")
        }
        return {
            "window": window.public_dict(),
            "metric": metric,
            "comparison": comparison,
            "threshold": threshold,
            "requested_limit": limit,
            "applied_limit": bounded_limit,
            "count": len(traces),
            "traces": traces,
            "candidate_search": {
                key: value
                for key, value in search_result.items()
                if key != "traces"
            },
        }

    @log(span_type="tool", name="galileo.get_trace_details")
    @control(step_name="inspect_production_trace")
    def get_trace_details(self, trace_id: str) -> dict[str, Any]:
        if trace_id not in self.allowed_trace_ids:
            raise PermissionError(
                "Trace details may be retrieved only for IDs returned by the latest bounded search."
            )
        detail_count = int(self._cache.get("detail_count", 0))
        if detail_count >= self.settings.max_detailed_traces:
            raise BudgetExceeded(
                f"Detailed trace limit of {self.settings.max_detailed_traces} has been reached."
            )
        result = self.service.get_trace_details(self.scope, trace_id)
        self._cache["detail_count"] = detail_count + 1
        self._cache[f"trace_detail:{trace_id}"] = result
        self.inspected_trace_ids.add(trace_id)
        return sanitize(result, self.settings.secret_values(), self.settings.max_output_chars)

    @log(span_type="tool", name="galileo.list_datasets")
    def list_datasets(self) -> list[dict[str, Any]]:
        return self.service.list_datasets(self.scope, limit=50)

    @log(span_type="tool", name="galileo.list_experiments")
    def list_experiments(self) -> list[dict[str, Any]]:
        return self.service.list_experiments(self.scope)

    @log(span_type="tool", name="galileo.list_prompts")
    def list_prompts(self) -> list[dict[str, Any]]:
        return self.service.list_prompts(self.scope, limit=50)

    @log(span_type="tool", name="galileo.compare_experiments")
    def compare_experiments(
        self,
        baseline_name: str,
        candidate_name: str,
    ) -> dict[str, Any]:
        return self.service.compare_experiments(
            self.scope,
            baseline_name=baseline_name,
            candidate_name=candidate_name,
        )

    @log(span_type="tool", name="galileo.create_prompt_version")
    @control(step_name="write_prompt_version")
    def create_prompt_version(self, prompt_name: str, system_prompt: str) -> dict[str, Any]:
        if not SAFE_RESOURCE_NAME.fullmatch(prompt_name):
            raise ValueError("Prompt name contains unsupported characters.")
        if not system_prompt.strip():
            raise ValueError("System prompt cannot be empty.")
        if len(system_prompt) > 8000:
            raise BudgetExceeded("System prompt exceeds the 8,000-character limit.")
        prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:12]
        preview_text = sanitize(
            system_prompt,
            self.settings.secret_values(),
            500,
        )
        self.approval.require(
            OperationPreview(
                operation="Create prompt version",
                project=self.scope.project_name,
                resource=prompt_name,
                records=1,
                details={
                    "Prompt SHA-256 prefix": prompt_hash,
                    "System prompt preview": preview_text,
                },
            )
        )
        return self.service.create_prompt_version(
            self.scope,
            prompt_name=prompt_name,
            system_prompt=system_prompt,
        )

    @log(span_type="tool", name="galileo.create_regression_dataset")
    @control(step_name="write_regression_dataset")
    def create_regression_dataset(self, dataset_name: str, trace_ids: list[str]) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(trace_ids))
        if not unique_ids:
            raise ValueError("At least one trace ID is required.")
        if len(unique_ids) > self.settings.max_dataset_rows:
            raise BudgetExceeded(
                f"Dataset write contains {len(unique_ids)} rows; limit is {self.settings.max_dataset_rows}."
            )
        unknown = [trace_id for trace_id in unique_ids if trace_id not in self.allowed_trace_ids]
        if unknown:
            raise PermissionError("Dataset contains trace IDs outside the latest bounded search.")
        uninspected = [
            trace_id
            for trace_id in unique_ids
            if trace_id not in self.inspected_trace_ids
        ]
        if uninspected:
            raise PermissionError(
                "Dataset rows must come from traces inspected in this session."
            )
        if not SAFE_RESOURCE_NAME.fullmatch(dataset_name):
            raise ValueError("Dataset name contains unsupported characters.")
        self.approval.require(
            OperationPreview(
                operation="Create or extend regression dataset",
                project=self.scope.project_name,
                resource=dataset_name,
                records=len(unique_ids),
                details={"Source Log Stream": self.scope.source_stream_name},
            )
        )
        return self.service.create_or_extend_dataset_from_traces(
            self.scope,
            dataset_name=dataset_name,
            trace_ids=unique_ids,
        )

    @log(span_type="tool", name="galileo.run_experiment")
    @control(step_name="run_bounded_experiment")
    def run_experiment(
        self,
        experiment_name: str,
        dataset_name: str,
        prompt_name: str,
        metrics: list[str],
    ) -> dict[str, Any]:
        if not SAFE_RESOURCE_NAME.fullmatch(experiment_name):
            raise ValueError("Experiment name contains unsupported characters.")
        if not 1 <= len(metrics) <= 3:
            raise BudgetExceeded("Experiments support between one and three metrics.")
        dataset = self.service.get_dataset(self.scope, dataset_name)
        if dataset is None:
            raise LookupError(f"Dataset {dataset_name!r} was not found.")
        rows = self.service.dataset_row_count(dataset)
        if rows <= 0:
            raise ValueError("The selected dataset is empty or its size could not be determined.")
        if rows > self.settings.max_experiment_rows:
            raise BudgetExceeded(
                f"Dataset has {rows} rows; experiment limit is {self.settings.max_experiment_rows}."
            )
        generation_calls = rows
        evaluator_calls = rows * len(metrics)
        if generation_calls > self.settings.max_generation_calls:
            raise BudgetExceeded(
                f"Experiment requires {generation_calls} generation calls; "
                f"configured limit is {self.settings.max_generation_calls}."
            )
        if evaluator_calls > self.settings.max_evaluator_calls:
            raise BudgetExceeded(
                f"Experiment requires up to {evaluator_calls} evaluator calls; "
                f"configured limit is {self.settings.max_evaluator_calls}."
            )
        self.approval.require(
            OperationPreview(
                operation="Run Galileo experiment",
                project=self.scope.project_name,
                resource=experiment_name,
                records=rows,
                estimated_generation_calls=generation_calls,
                estimated_evaluator_calls=evaluator_calls,
                details={
                    "Dataset": dataset_name,
                    "Prompt": prompt_name,
                    "Metrics": ", ".join(metrics),
                    "Model": self.settings.model,
                },
            )
        )
        return self.service.run_experiment(
            self.scope,
            name=experiment_name,
            dataset_name=dataset_name,
            prompt_name=prompt_name,
            metrics=metrics,
        )

    @staticmethod
    def _bounded_collection_count(value: Any) -> int | None:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            for key in ("controls", "agents", "items", "data", "results"):
                items = value.get(key)
                if isinstance(items, list):
                    return len(items)
        return None

    @log(span_type="tool", name="galileo.run_project_doctor")
    def run_project_doctor(self, stale_days: int) -> dict[str, Any]:
        if not 1 <= stale_days <= 365:
            raise ValueError("stale_days must be between 1 and 365.")
        cache_key = json.dumps(["project_doctor", stale_days])
        if cache_key in self._cache:
            cached = dict(self._cache[cache_key])
            cached["cached"] = True
            return cached

        snapshot = self.service.project_snapshot(
            self.scope.project_name,
            stream_limit=self.settings.max_management_streams,
            resource_limit=self.settings.max_management_resources,
            session_sample=self.settings.max_session_sample,
            include_activity=True,
        )
        try:
            window = TimeWindow.recent_hours(
                self.settings.default_lookback_hours,
                self.settings.max_lookback_hours,
            )
            snapshot["selected_stream_metric_summary"] = self.service.query_metrics(
                self.scope,
                window,
                interval_minutes=1440,
            )
        except Exception as exc:
            snapshot["selected_stream_metric_summary"] = {
                "audit_error": sanitize(
                    str(exc),
                    self.settings.secret_values(),
                    500,
                )
            }

        control_coverage: dict[str, Any] = {
            "configured": bool(self.settings.agent_control_url),
        }
        if self.settings.agent_control_url:
            for label, stream_id in (
                ("source_log_stream", self.scope.source_stream_id),
                ("evalops_telemetry_log_stream", self.scope.telemetry_stream_id),
            ):
                if not stream_id:
                    continue
                try:
                    result = self.control_service.list_controls_for_target(
                        target_type="log_stream",
                        target_id=stream_id,
                        limit=self.settings.max_management_resources,
                    )
                    control_coverage[label] = {
                        "attached_control_count": self._bounded_collection_count(result),
                    }
                except Exception as exc:
                    control_coverage[label] = {
                        "audit_error": sanitize(
                            str(exc),
                            self.settings.secret_values(),
                            500,
                        )
                    }
        snapshot["agent_control_coverage"] = control_coverage
        snapshot["telemetry_stream_known"] = bool(self.scope.telemetry_stream_id)

        report = build_project_doctor_report(
            snapshot,
            telemetry_stream_name=self.scope.telemetry_stream_name,
            stale_days=stale_days,
        )
        report["agent_control_coverage"] = control_coverage
        report["cached"] = False
        self._cache[cache_key] = report
        return report

    @log(span_type="tool", name="galileo.estimate_evaluation_budget")
    def estimate_evaluation_budget(
        self,
        dataset_name: str | None,
        rows: int | None,
        metrics: list[str],
        runs: int,
        sample_percent: int,
    ) -> dict[str, Any]:
        if not metrics:
            raise ValueError("At least one metric is required.")
        if len(metrics) > 10:
            raise BudgetExceeded("Cost planning supports at most ten metrics.")
        if not 1 <= runs <= 10:
            raise ValueError("runs must be between 1 and 10.")
        if not 1 <= sample_percent <= 100:
            raise ValueError("sample_percent must be between 1 and 100.")
        if dataset_name:
            dataset = self.service.get_dataset(self.scope, dataset_name)
            if dataset is None:
                raise LookupError(f"Dataset {dataset_name!r} was not found.")
            resolved_rows = self.service.dataset_row_count(dataset)
            if resolved_rows <= 0:
                raise ValueError("The selected dataset is empty.")
            source = {"dataset": dataset_name}
        elif rows is not None and rows > 0:
            resolved_rows = rows
            source = {"user_provided_rows": rows}
        else:
            raise ValueError("Provide either dataset_name or a positive rows value.")
        result = estimate_evaluation_budget(
            rows=resolved_rows,
            metric_count=len(metrics),
            runs=runs,
            sample_percent=sample_percent,
            max_generation_calls=self.settings.max_generation_calls,
            max_evaluator_calls=self.settings.max_evaluator_calls,
        )
        result["metrics"] = list(dict.fromkeys(metrics))
        result["row_source"] = source
        if not result["within_budget"]:
            result["recommendation"] = (
                "Reduce sample_percent, metrics, or runs before requesting an experiment."
            )
        else:
            result["recommendation"] = (
                "The plan is within configured call limits; an experiment still "
                "requires a separate write preview and approval."
            )
        return result

    @log(span_type="tool", name="galileo.analyze_dataset_coverage")
    @control(step_name="analyze_regression_coverage")
    def analyze_dataset_coverage(
        self,
        dataset_name: str,
        trace_ids: list[str],
        similarity_threshold: float,
    ) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(trace_ids))
        if not unique_ids:
            raise ValueError("At least one trace ID is required.")
        if not 0.05 <= similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be between 0.05 and 1.")
        unknown = [
            trace_id
            for trace_id in unique_ids
            if trace_id not in self.inspected_trace_ids
        ]
        if unknown:
            raise PermissionError(
                "Coverage analysis accepts only trace IDs that were searched and "
                "inspected in this session."
            )
        traces = [
            self._cache[f"trace_detail:{trace_id}"]
            for trace_id in unique_ids
        ]
        dataset_rows = self.service.dataset_rows_bounded(
            self.scope,
            dataset_name,
            limit=self.settings.max_coverage_rows,
        )
        report = analyze_coverage(
            traces,
            dataset_rows,
            similarity_threshold=similarity_threshold,
        )
        report["dataset"] = dataset_name
        self._cache["latest_coverage_report"] = report
        return report

    @log(span_type="tool", name="galileo.evaluate_release_readiness")
    def evaluate_release_readiness(
        self,
        baseline_name: str,
        candidate_name: str,
        criteria: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not 1 <= len(criteria) <= 10:
            raise BudgetExceeded("Release gates require between one and ten criteria.")
        valid_sources = {"candidate", "baseline", "delta"}
        valid_operators = {">=", ">", "<=", "<"}
        for criterion in criteria:
            if criterion.get("source") not in valid_sources:
                raise ValueError("Invalid release criterion source.")
            if criterion.get("operator") not in valid_operators:
                raise ValueError("Invalid release criterion operator.")
            if not SAFE_COLUMN_NAME.fullmatch(str(criterion.get("metric", ""))):
                raise ValueError("Release criterion metric name is invalid.")
        comparison = self.service.compare_experiments(
            self.scope,
            baseline_name=baseline_name,
            candidate_name=candidate_name,
        )
        report = evaluate_release_gate(comparison, criteria)
        self._cache["latest_release_gate"] = report
        return report

    @log(span_type="tool", name="galileo.compare_project_environments")
    def compare_project_environments(
        self,
        target_project_name: str,
    ) -> dict[str, Any]:
        if target_project_name == self.scope.project_name:
            raise ValueError("Target project must differ from the selected source project.")
        source = self.service.project_snapshot(
            self.scope.project_name,
            stream_limit=self.settings.max_management_streams,
            resource_limit=self.settings.max_management_resources,
            session_sample=1,
            include_activity=False,
        )
        target = self.service.project_snapshot(
            target_project_name,
            stream_limit=self.settings.max_management_streams,
            resource_limit=self.settings.max_management_resources,
            session_sample=1,
            include_activity=False,
        )
        report = build_environment_diff(source, target)
        self._cache["latest_environment_diff"] = report
        return report

    @log(span_type="tool", name="galileo.bootstrap_missing_log_streams")
    @control(step_name="bootstrap_galileo_environment")
    def bootstrap_missing_log_streams(
        self,
        target_project_name: str,
        stream_names: list[str],
    ) -> dict[str, Any]:
        latest = self._cache.get("latest_environment_diff")
        if not isinstance(latest, dict):
            raise PermissionError(
                "Run an environment comparison before requesting bootstrap changes."
            )
        if latest.get("target_project", {}).get("name") != target_project_name:
            raise PermissionError(
                "Target project does not match the latest environment comparison."
            )
        allowed = set(
            latest.get("safe_bootstrap_candidates", {}).get("log_streams", [])
        )
        unique_names = list(dict.fromkeys(stream_names))
        if not 1 <= len(unique_names) <= self.settings.max_management_streams:
            raise BudgetExceeded(
                f"Bootstrap supports 1–{self.settings.max_management_streams} Log Streams."
            )
        if any(not SAFE_RESOURCE_NAME.fullmatch(name) for name in unique_names):
            raise ValueError("One or more Log Stream names are invalid.")
        unauthorized = [name for name in unique_names if name not in allowed]
        if unauthorized:
            raise PermissionError(
                "Bootstrap includes names that were not missing in the latest comparison."
            )
        self.approval.require(
            OperationPreview(
                operation="Bootstrap missing Galileo Log Streams",
                project=target_project_name,
                resource=", ".join(unique_names),
                records=len(unique_names),
                details={
                    "Source project": self.scope.project_name,
                    "Trace data copied": "no",
                    "Existing resources modified": "no",
                    "Collaborators changed": "no",
                },
            )
        )
        created = self.service.create_missing_log_streams(
            target_project_name=target_project_name,
            stream_names=unique_names,
        )
        return {
            "target_project": target_project_name,
            "requested": unique_names,
            "created": created,
        }

    @log(span_type="tool", name="agent_control.list_agents")
    def list_agent_control_agents(self) -> dict[str, Any]:
        result = self.control_service.list_agents(
            limit=self.settings.max_management_resources,
        )
        items: Any = result.get("agents", []) if isinstance(result, dict) else []
        names = {
            str(item.get("agent_name") or item.get("name"))
            for item in items
            if isinstance(item, dict) and (item.get("agent_name") or item.get("name"))
        }
        self._cache["listed_agent_control_agents"] = names
        return result

    @log(span_type="tool", name="agent_control.propose_control")
    def propose_agent_control(
        self,
        name: str,
        description: str,
        selector_path: str,
        regex_pattern: str,
        action: str,
        stage: str,
        step_names: list[str],
        trace_ids: list[str],
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}", name):
            raise ValueError(
                "Control name must be 3–80 characters using letters, digits, . _ : or -."
            )
        if selector_path not in {"input", "output"}:
            raise ValueError("selector_path must be input or output.")
        if action not in {"observe", "steer", "deny"}:
            raise ValueError("action must be observe, steer, or deny.")
        if stage not in {"pre", "post"}:
            raise ValueError("stage must be pre or post.")
        if not 1 <= len(step_names) <= 10:
            raise BudgetExceeded("A control proposal supports 1–10 step names.")
        if any(not SAFE_RESOURCE_NAME.fullmatch(step) for step in step_names):
            raise ValueError("One or more Agent Control step names are invalid.")
        compiled = _compile_bounded_regex(regex_pattern)
        unknown = [
            trace_id
            for trace_id in trace_ids
            if trace_id not in self.inspected_trace_ids
        ]
        if unknown:
            raise PermissionError(
                "Control simulation accepts only traces already inspected in this session."
            )

        action_definition: dict[str, Any] = {"decision": action}
        if action == "steer":
            action_definition["steering_context"] = {
                "message": description,
            }
        definition = {
            "description": description,
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["llm"],
                "step_names": list(dict.fromkeys(step_names)),
                "stages": [stage],
            },
            "condition": {
                "selector": {"path": selector_path},
                "evaluator": {
                    "name": "regex",
                    "config": {"pattern": regex_pattern},
                },
            },
            "action": action_definition,
            "tags": ["evalops-generated", "requires-review"],
        }
        validation = self.control_service.validate_control(definition)
        server_validated = bool(
            isinstance(validation, dict)
            and (
                validation.get("success") is True
                or validation.get("valid") is True
            )
        )
        simulation = []
        for trace_id in list(dict.fromkeys(trace_ids))[:10]:
            trace = self._cache[f"trace_detail:{trace_id}"]
            selected = trace.get(selector_path, "")
            rendered = json.dumps(selected, ensure_ascii=False, default=str)
            simulation.append(
                {
                    "trace_id": trace_id,
                    "matched": bool(compiled.search(rendered)),
                }
            )
        canonical = json.dumps(
            {"name": name, "definition": definition},
            sort_keys=True,
            ensure_ascii=False,
        )
        proposal_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        proposal = {
            "proposal_id": proposal_id,
            "name": name,
            "definition": definition,
            "validation": validation,
            "server_validated": server_validated,
            "simulation": {
                "method": "local_regex_preview",
                "trace_count": len(simulation),
                "matched_count": sum(item["matched"] for item in simulation),
                "results": simulation,
                "warning": (
                    "This preview does not establish false-positive or false-negative "
                    "rates; review representative non-failures before publishing."
                ),
            },
        }
        if server_validated:
            proposals = self._cache.setdefault("control_proposals", {})
            proposals[proposal_id] = proposal
        return proposal

    @log(span_type="tool", name="agent_control.create_control")
    @control(step_name="write_agent_control_policy")
    def create_agent_control_from_proposal(
        self,
        proposal_id: str,
        agent_name: str,
    ) -> dict[str, Any]:
        proposals = self._cache.get("control_proposals", {})
        proposal = proposals.get(proposal_id) if isinstance(proposals, dict) else None
        if not isinstance(proposal, dict):
            raise PermissionError(
                "Control creation requires a proposal validated in this session."
            )
        if proposal.get("server_validated") is not True:
            raise PermissionError(
                "Control creation requires successful Agent Control server validation."
            )
        listed_agents = self._cache.get("listed_agent_control_agents", set())
        if not isinstance(listed_agents, set) or agent_name not in listed_agents:
            raise PermissionError(
                "List Agent Control agents in this session and select an exact "
                "returned agent before attaching a control."
            )
        self.approval.require(
            OperationPreview(
                operation="Create and attach Agent Control",
                project=self.scope.project_name,
                resource=proposal["name"],
                records=1,
                details={
                    "Agent": agent_name,
                    "Proposal ID": proposal_id,
                    "Action": proposal["definition"]["action"]["decision"],
                    "Execution": proposal["definition"]["execution"],
                    "Simulation traces": proposal["simulation"]["trace_count"],
                },
            )
        )
        return self.control_service.create_and_attach_control(
            name=proposal["name"],
            definition=proposal["definition"],
            agent_name=agent_name,
        )

    @log(span_type="tool", name="galileo.accept_signal_handoff")
    def accept_signal_handoff(
        self,
        signal_name: str,
        metric: str,
        threshold: float,
        hours: int,
        signal_url: str | None,
        notes: str | None,
    ) -> dict[str, Any]:
        if not signal_name.strip():
            raise ValueError("Signal name cannot be empty.")
        if not 0 <= threshold <= 1:
            raise ValueError("Signal threshold must be between 0 and 1.")
        window = TimeWindow.recent_hours(hours, self.settings.max_lookback_hours)
        _, available = self.service.resolve_metric_column(self.scope, metric)
        handoff = {
            "signal_name": signal_name,
            "signal_url": signal_url,
            "notes": notes,
            "project": self.scope.project_name,
            "log_stream": self.scope.source_stream_name,
            "metric": metric,
            "threshold": threshold,
            "window": window.public_dict(),
            "available_metrics": available,
            "signals_api_query_performed": False,
            "next_steps": [
                "Query the existing aggregate metric trend for the handoff window.",
                "Search a bounded recent sample below the signal threshold.",
                "Inspect only selected returned trace IDs.",
                "Offer coverage, dataset, experiment, or control actions after evidence review.",
            ],
        }
        self._cache["signal_handoff"] = handoff
        return handoff
