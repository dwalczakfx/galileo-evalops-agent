from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any


TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
STOP_WORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "has",
    "have",
    "into",
    "not",
    "that",
    "the",
    "their",
    "then",
    "this",
    "was",
    "were",
    "with",
    "you",
    "your",
}


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(value: Any) -> int | None:
    parsed = _as_datetime(value)
    if parsed is None:
        return None
    return max(0, (datetime.now(timezone.utc) - parsed).days)


def _finding(
    finding_id: str,
    severity: str,
    category: str,
    title: str,
    evidence: dict[str, Any],
    recommendation: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "category": category,
        "title": title,
        "evidence": evidence,
        "recommendation": recommendation,
        "next_action": next_action,
    }


def build_project_doctor_report(
    snapshot: dict[str, Any],
    *,
    telemetry_stream_name: str,
    stale_days: int,
) -> dict[str, Any]:
    """Create a transparent rules-based audit from one bounded project snapshot."""
    findings: list[dict[str, Any]] = []
    streams = snapshot.get("log_streams", [])
    datasets = snapshot.get("datasets", [])
    prompts = snapshot.get("prompts", [])
    experiments = snapshot.get("experiments", [])

    stream_names = {str(stream.get("name")) for stream in streams}
    if (
        telemetry_stream_name not in stream_names
        and not snapshot.get("telemetry_stream_known")
    ):
        findings.append(
            _finding(
                "telemetry-stream-missing",
                "high",
                "observability",
                "The dedicated EvalOps telemetry Log Stream is missing",
                {"expected_stream": telemetry_stream_name},
                "Create the telemetry Log Stream before operating the management agent.",
                "run setup",
            )
        )

    for stream in streams:
        name = str(stream.get("name", "unknown"))
        safe_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "stream"
        audit_error = stream.get("audit_error")
        if audit_error:
            findings.append(
                _finding(
                    f"stream-audit-error-{safe_id}",
                    "medium",
                    "audit",
                    f"Could not fully audit Log Stream {name!r}",
                    {"error": audit_error},
                    "Verify access and retry only this Log Stream.",
                    "inspect stream metadata",
                )
            )
            continue

        if stream.get("sampled_trace_count", 0) == 0:
            findings.append(
                _finding(
                    f"no-traces-{safe_id}",
                    "medium",
                    "observability",
                    f"No traces were found in Log Stream {name!r}",
                    {"trace_sample_limit": stream.get("trace_sample_limit", 1)},
                    "Verify instrumentation and ingestion before enabling more evaluations.",
                    "run a telemetry smoke test",
                )
            )
        else:
            age = _age_days(stream.get("latest_trace_at"))
            if age is not None and age > stale_days:
                findings.append(
                    _finding(
                        f"stale-stream-{safe_id}",
                        "low",
                        "hygiene",
                        f"Log Stream {name!r} has no recent trace activity",
                        {"latest_trace_age_days": age, "stale_after_days": stale_days},
                        "Confirm whether this stream is intentionally inactive.",
                        "review stream ownership",
                    )
                )

        empty_sessions = int(stream.get("empty_sessions_in_sample", 0) or 0)
        if empty_sessions:
            findings.append(
                _finding(
                    f"empty-sessions-{safe_id}",
                    "high" if empty_sessions > 1 else "medium",
                    "observability",
                    f"Log Stream {name!r} contains sessions without traces",
                    {
                        "empty_sessions": empty_sessions,
                        "sessions_sampled": stream.get("sampled_session_count", 0),
                    },
                    "Check trace finalization, flush results, and ingestion errors.",
                    "inspect instrumentation lifecycle",
                )
            )

        metrics = stream.get("enabled_metrics", [])
        if not metrics and name != telemetry_stream_name:
            findings.append(
                _finding(
                    f"metrics-missing-{safe_id}",
                    "medium",
                    "evaluation",
                    f"Log Stream {name!r} has no enabled server metrics",
                    {"enabled_metrics": []},
                    "Choose metrics based on release decisions before enabling them.",
                    "estimate metric budget",
                )
            )

    empty_datasets = [
        item.get("name")
        for item in datasets
        if item.get("num_rows") == 0
    ]
    if not datasets:
        findings.append(
            _finding(
                "no-datasets",
                "medium",
                "coverage",
                "The project has no evaluation datasets",
                {"dataset_count": 0},
                "Convert verified production failures into a bounded regression dataset.",
                "run coverage-gap workflow",
            )
        )
    elif empty_datasets:
        findings.append(
            _finding(
                "empty-datasets",
                "medium",
                "hygiene",
                "Some datasets contain no rows",
                {"datasets": empty_datasets},
                "Populate, repurpose, or manually review the empty datasets.",
                "inspect dataset metadata",
            )
        )

    if not prompts:
        findings.append(
            _finding(
                "no-prompts",
                "low",
                "release",
                "The project has no managed prompts",
                {"prompt_count": 0},
                "Manage candidate prompts in Galileo to make releases reproducible.",
                "create a managed prompt",
            )
        )

    if prompts and not experiments:
        findings.append(
            _finding(
                "prompts-without-experiments",
                "medium",
                "release",
                "Managed prompts exist but no experiments were found",
                {"prompt_count": len(prompts), "experiment_count": 0},
                "Run a bounded baseline experiment before releasing prompt changes.",
                "run release-readiness workflow",
            )
        )

    incomplete = [
        {
            "name": item.get("name"),
            "status": item.get("status"),
        }
        for item in experiments
        if str(item.get("status", "")).lower()
        not in {"", "completed", "complete", "succeeded", "success"}
    ]
    if incomplete:
        findings.append(
            _finding(
                "incomplete-experiments",
                "medium",
                "release",
                "Some recent experiments are not complete",
                {"experiments": incomplete[:10]},
                "Review experiment errors before using results for a release decision.",
                "inspect experiment results",
            )
        )

    metric_summary = snapshot.get("selected_stream_metric_summary") or {}
    if metric_summary.get("ems_captured_error"):
        findings.append(
            _finding(
                "metric-evaluation-errors",
                "high",
                "evaluation",
                "Galileo reported metric evaluation errors on the selected Log Stream",
                {"ems_captured_error": True},
                "Inspect evaluator errors before recomputing or trusting affected metrics.",
                "review metric errors",
            )
        )

    severity_order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda item: (severity_order[item["severity"]], item["id"]))
    counts = Counter(item["severity"] for item in findings)
    return {
        "project": snapshot.get("project"),
        "audit_type": "bounded_rules_based_project_doctor",
        "health_score": None,
        "finding_counts": {
            "high": counts.get("high", 0),
            "medium": counts.get("medium", 0),
            "low": counts.get("low", 0),
            "total": len(findings),
        },
        "inventory": {
            "log_streams": len(streams),
            "datasets": len(datasets),
            "prompts": len(prompts),
            "experiments": len(experiments),
            "collaborators": len(snapshot.get("collaborators", [])),
        },
        "findings": findings,
        "sampling": snapshot.get("sampling", {}),
        "limitations": [
            "No organization-wide traces were queried.",
            "Only the configured number of project resources and recent records were sampled.",
            "Findings are deterministic checks, not an opaque AI-generated health score.",
        ],
    }


def _resource_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item["name"]): item
        for item in items
        if item.get("name")
    }


def build_environment_diff(
    source: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    resource_types = ("log_streams", "datasets", "prompts", "experiments")
    resources: dict[str, Any] = {}
    for resource_type in resource_types:
        source_index = _resource_index(source.get(resource_type, []))
        target_index = _resource_index(target.get(resource_type, []))
        resources[resource_type] = {
            "missing_in_target": sorted(source_index.keys() - target_index.keys()),
            "only_in_target": sorted(target_index.keys() - source_index.keys()),
            "shared": sorted(source_index.keys() & target_index.keys()),
        }

    prompt_drift = []
    source_prompts = _resource_index(source.get("prompts", []))
    target_prompts = _resource_index(target.get("prompts", []))
    for name in sorted(source_prompts.keys() & target_prompts.keys()):
        source_version = source_prompts[name].get("selected_version_number")
        target_version = target_prompts[name].get("selected_version_number")
        if source_version != target_version:
            prompt_drift.append(
                {
                    "name": name,
                    "source_version": source_version,
                    "target_version": target_version,
                }
            )

    stream_metric_drift = []
    source_streams = _resource_index(source.get("log_streams", []))
    target_streams = _resource_index(target.get("log_streams", []))
    for name in sorted(source_streams.keys() & target_streams.keys()):
        source_metrics = set(source_streams[name].get("enabled_metrics", []))
        target_metrics = set(target_streams[name].get("enabled_metrics", []))
        if source_metrics != target_metrics:
            stream_metric_drift.append(
                {
                    "name": name,
                    "missing_in_target": sorted(source_metrics - target_metrics),
                    "only_in_target": sorted(target_metrics - source_metrics),
                }
            )

    def collaborator_roles(snapshot: dict[str, Any]) -> dict[str, str]:
        return {
            str(item["email"]): str(item.get("role"))
            for item in snapshot.get("collaborators", [])
            if item.get("email")
        }

    source_roles = collaborator_roles(source)
    target_roles = collaborator_roles(target)
    collaborator_drift = []
    for email in sorted(source_roles.keys() | target_roles.keys()):
        if source_roles.get(email) != target_roles.get(email):
            collaborator_drift.append(
                {
                    "email": email,
                    "source_role": source_roles.get(email),
                    "target_role": target_roles.get(email),
                }
            )

    return {
        "source_project": source.get("project"),
        "target_project": target.get("project"),
        "resources": resources,
        "prompt_version_drift": prompt_drift,
        "stream_metric_drift": stream_metric_drift,
        "collaborator_role_drift": collaborator_drift,
        "safe_bootstrap_candidates": {
            "log_streams": resources["log_streams"]["missing_in_target"],
        },
        "excluded_automatic_actions": [
            "Trace data is never copied.",
            "Dataset content is never copied by the bootstrap operation.",
            "Collaborators are never changed automatically.",
            "Existing resources are never deleted or overwritten.",
        ],
        "sampling": {
            "source": source.get("sampling", {}),
            "target": target.get("sampling", {}),
        },
    }


def estimate_evaluation_budget(
    *,
    rows: int,
    metric_count: int,
    runs: int,
    sample_percent: int,
    max_generation_calls: int,
    max_evaluator_calls: int,
) -> dict[str, Any]:
    sampled_rows = min(rows, max(1, math.ceil(rows * sample_percent / 100)))
    generation_calls = sampled_rows * runs
    evaluator_calls = generation_calls * metric_count
    within_budget = (
        generation_calls <= max_generation_calls
        and evaluator_calls <= max_evaluator_calls
    )
    return {
        "input_rows": rows,
        "sample_percent": sample_percent,
        "sampled_rows": sampled_rows,
        "metrics": metric_count,
        "runs": runs,
        "estimated_generation_calls": generation_calls,
        "estimated_evaluator_calls": evaluator_calls,
        "configured_limits": {
            "generation_calls": max_generation_calls,
            "evaluator_calls": max_evaluator_calls,
        },
        "within_budget": within_budget,
        "formula": "sampled_rows × runs; evaluator calls = generation calls × metrics",
        "monetary_cost": None,
        "monetary_cost_note": (
            "A currency estimate is not produced because evaluator and model pricing "
            "is not available from the selected project metadata."
        ),
    }


def _resolve_numeric_metric(
    values: dict[str, float],
    requested: str,
) -> tuple[str, float]:
    if requested in values:
        return requested, values[requested]
    matches = [
        (key, value)
        for key, value in values.items()
        if key.rsplit(".", 1)[-1] == requested
    ]
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(sorted(values)) or "none"
    raise ValueError(
        f"Metric {requested!r} is not uniquely available. Numeric metrics: {available}."
    )


def evaluate_release_gate(
    comparison: dict[str, Any],
    criteria: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate = comparison.get("candidate", {})
    baseline = comparison.get("baseline", {})
    candidate_values = _flatten_numbers(candidate.get("aggregate_metrics", {}))
    baseline_values = _flatten_numbers(baseline.get("aggregate_metrics", {}))
    deltas = comparison.get("numeric_deltas_candidate_minus_baseline", {})
    delta_values = {
        key: float(value)
        for key, value in deltas.items()
        if isinstance(value, bool | int | float) and not isinstance(value, bool)
    }
    results = []
    for criterion in criteria:
        source = criterion["source"]
        values = {
            "candidate": candidate_values,
            "baseline": baseline_values,
            "delta": delta_values,
        }[source]
        resolved_metric, actual = _resolve_numeric_metric(values, criterion["metric"])
        target = float(criterion["value"])
        operator = criterion["operator"]
        passed = {
            ">=": actual >= target,
            ">": actual > target,
            "<=": actual <= target,
            "<": actual < target,
        }[operator]
        results.append(
            {
                "metric": resolved_metric,
                "source": source,
                "operator": operator,
                "target": target,
                "actual": actual,
                "passed": passed,
            }
        )
    passed_count = sum(item["passed"] for item in results)
    return {
        "decision": "GO" if results and passed_count == len(results) else "HOLD",
        "criteria_passed": passed_count,
        "criteria_total": len(results),
        "criteria": results,
        "baseline": comparison.get("baseline"),
        "candidate": comparison.get("candidate"),
        "numeric_deltas_candidate_minus_baseline": deltas,
        "decision_rule": "GO only when every explicit user-provided criterion passes.",
    }


def _flatten_numbers(value: Any, prefix: str = "") -> dict[str, float]:
    flattened: dict[str, float] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_numbers(item, child))
    elif isinstance(value, bool | int | float) and not isinstance(value, bool):
        flattened[prefix] = float(value)
    return flattened


def evidence_tokens(value: Any) -> set[str]:
    parts: list[str] = []

    def collect(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                normalized_key = str(child_key).lower()
                if any(
                    marker in normalized_key
                    for marker in ("scenario", "failure", "error", "tag", "input", "output")
                ):
                    collect(child, normalized_key)
        elif isinstance(item, list):
            for child in item[:20]:
                collect(child, key)
        elif isinstance(item, str):
            parts.append(item)

    collect(value)
    tokens = {
        token
        for token in TOKEN_PATTERN.findall(" ".join(parts).lower())
        if token not in STOP_WORDS
    }
    return set(sorted(tokens)[:200])


def analyze_coverage(
    trace_records: list[dict[str, Any]],
    dataset_rows: list[dict[str, Any]],
    *,
    similarity_threshold: float,
) -> dict[str, Any]:
    dataset_token_sets = [evidence_tokens(row) for row in dataset_rows]
    results = []
    for trace in trace_records:
        trace_tokens = evidence_tokens(trace)
        best_index: int | None = None
        best_score = 0.0
        best_overlap: set[str] = set()
        for index, row_tokens in enumerate(dataset_token_sets):
            union = trace_tokens | row_tokens
            score = len(trace_tokens & row_tokens) / len(union) if union else 0.0
            if score > best_score:
                best_index = index
                best_score = score
                best_overlap = trace_tokens & row_tokens
        results.append(
            {
                "trace_id": trace.get("id"),
                "covered": best_score >= similarity_threshold,
                "best_dataset_row_index": best_index,
                "similarity": round(best_score, 4),
                "evidence_terms": sorted(best_overlap)[:12],
                "trace_signature_terms": sorted(trace_tokens)[:20],
            }
        )
    gaps = [item for item in results if not item["covered"]]
    return {
        "method": "deterministic_token_jaccard",
        "similarity_threshold": similarity_threshold,
        "trace_count": len(trace_records),
        "dataset_rows_compared": len(dataset_rows),
        "covered_count": len(results) - len(gaps),
        "gap_count": len(gaps),
        "results": results,
        "gap_trace_ids": [item["trace_id"] for item in gaps if item.get("trace_id")],
        "limitations": [
            "This is a bounded lexical coverage check, not a semantic guarantee.",
            "The agent should inspect evidence before creating regression rows.",
        ],
    }
