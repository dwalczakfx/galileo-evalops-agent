from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from galileo import Dataset, Experiment, LogStream, Message, MessageRole, Project, Prompt
from galileo.config import GalileoPythonConfig
from galileo.datasets import Datasets
from galileo.resources.api.datasets import (
    update_dataset_content_datasets_dataset_id_content_patch as update_dataset_content,
)
from galileo.resources.api.trace import (
    get_trace_projects_project_id_traces_trace_id_get as get_trace_by_id,
    query_metrics_v2_projects_project_id_metrics_search_v2_post as query_metrics_v2,
)
from galileo.resources.models import (
    DatasetCopyRecordData,
    LogRecordsMetricsQueryRequest,
    LogRecordsSortClause,
    UpdateDatasetContentRequest,
)
from galileo.search import get_traces

from .config import Settings
from .models import BudgetExceeded, Scope, TimeWindow
from .security import sanitize


class GalileoService:
    """Fixed-scope facade over documented Galileo SDK and API operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._metric_catalog_cache: dict[tuple[str, str], dict[str, str]] = {}
        self._session_datasets: dict[tuple[str, str], Dataset] = {}

    def get_project(self, name: str) -> Project | None:
        return Project.get(name=name)

    def list_projects(self) -> list[Project]:
        # Metadata only. This never queries traces or metrics.
        return Project.list()

    def get_log_stream(self, project_id: str, name: str) -> LogStream | None:
        return LogStream.get(name=name, project_id=project_id)

    def list_log_streams(self, project_id: str, limit: int = 100) -> list[LogStream]:
        return LogStream.list(project_id=project_id, limit=min(limit, 100), starting_token=0)

    def create_log_stream(self, project_name: str, name: str) -> LogStream:
        return LogStream(name=name, project_name=project_name).create()

    def project_snapshot(
        self,
        project_name: str,
        *,
        stream_limit: int,
        resource_limit: int,
        session_sample: int,
        include_activity: bool,
    ) -> dict[str, Any]:
        """Read a bounded project inventory without querying organization-wide traces."""
        project = self.get_project(project_name)
        if project is None:
            raise LookupError(f"Project {project_name!r} was not found.")

        streams = self.list_log_streams(project.id, limit=stream_limit)
        stream_summaries = []
        for stream in streams:
            summary = self._resource_summary(stream)
            try:
                summary["enabled_metrics"] = sorted(
                    str(metric) for metric in stream.get_metrics()
                )
                if include_activity:
                    traces = stream.get_traces(
                        sort=LogRecordsSortClause(
                            column_id="created_at",
                            ascending=False,
                        ),
                        limit=1,
                        starting_token=0,
                    )
                    trace_records = list(traces)
                    summary["sampled_trace_count"] = len(trace_records)
                    summary["trace_sample_limit"] = 1
                    if trace_records:
                        summary["latest_trace_at"] = trace_records[0].get("created_at")

                    sessions = stream.get_sessions(
                        sort=LogRecordsSortClause(
                            column_id="created_at",
                            ascending=False,
                        ),
                        limit=session_sample,
                        starting_token=0,
                    )
                    session_records = list(sessions)
                    summary["sampled_session_count"] = len(session_records)
                    summary["session_sample_limit"] = session_sample
                    summary["empty_sessions_in_sample"] = sum(
                        self._session_trace_count(record) == 0
                        for record in session_records
                    )
            except Exception as exc:
                summary["audit_error"] = sanitize(
                    str(exc),
                    self.settings.secret_values(),
                    500,
                )
            stream_summaries.append(summary)

        datasets = Dataset.list(
            project_id=project.id,
            limit=min(resource_limit, 50),
        )
        prompts = Prompt.list(
            project_id=project.id,
            limit=min(resource_limit, 50),
        )
        experiments = Experiment.list(project_id=project.id)[:resource_limit]

        collaborators = []
        try:
            for collaborator in project.list_collaborators()[:resource_limit]:
                role = getattr(collaborator, "role", None)
                collaborators.append(
                    {
                        "user_id": getattr(collaborator, "user_id", None),
                        "email": getattr(collaborator, "email", None),
                        "role": getattr(role, "value", role),
                        "created_at": getattr(collaborator, "created_at", None),
                    }
                )
        except Exception as exc:
            collaborators = [
                {
                    "audit_error": sanitize(
                        str(exc),
                        self.settings.secret_values(),
                        500,
                    )
                }
            ]

        return sanitize(
            {
                "project": self._resource_summary(project),
                "log_streams": stream_summaries,
                "datasets": [self._resource_summary(item) for item in datasets],
                "prompts": [self._prompt_summary(item) for item in prompts],
                "experiments": [
                    self._experiment_summary(item)
                    for item in experiments
                ],
                "collaborators": collaborators,
                "sampling": {
                    "stream_limit": stream_limit,
                    "resource_limit_per_type": resource_limit,
                    "session_sample_per_stream": session_sample if include_activity else 0,
                    "activity_inspection": include_activity,
                    "automatic_pagination": False,
                },
            },
            self.settings.secret_values(),
            self.settings.max_output_chars * 3,
        )

    @staticmethod
    def _session_trace_count(record: dict[str, Any]) -> int | None:
        for key in (
            "metrics_num_traces",
            "num_traces",
            "metrics/num_traces",
            "trace_count",
        ):
            raw = record.get(key)
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                return int(raw)
        return None

    def create_missing_log_streams(
        self,
        *,
        target_project_name: str,
        stream_names: list[str],
    ) -> list[dict[str, Any]]:
        project = self.get_project(target_project_name)
        if project is None:
            raise LookupError(f"Target project {target_project_name!r} was not found.")
        created = []
        for name in stream_names:
            existing = self.get_log_stream(project.id, name)
            if existing is not None:
                continue
            stream = LogStream(name=name, project_id=project.id).create()
            created.append(self._resource_summary(stream))
        return created

    def resolve_scope(
        self,
        project_name: str,
        source_stream_name: str,
        telemetry_stream_name: str,
    ) -> Scope:
        project = self.get_project(project_name)
        if project is None:
            raise LookupError(f"Galileo project {project_name!r} was not found.")
        source = self.get_log_stream(project.id, source_stream_name)
        if source is None:
            raise LookupError(
                f"Log Stream {source_stream_name!r} was not found in project {project_name!r}."
            )
        telemetry = self.get_log_stream(project.id, telemetry_stream_name)
        return Scope(
            project_name=project.name,
            project_id=project.id,
            source_stream_name=source.name,
            source_stream_id=source.id,
            telemetry_stream_name=telemetry_stream_name,
            telemetry_stream_id=telemetry.id if telemetry else None,
        )

    def query_metrics(
        self,
        scope: Scope,
        window: TimeWindow,
        *,
        group_by: str | None = None,
        interval_minutes: int = 60,
    ) -> dict[str, Any]:
        body = LogRecordsMetricsQueryRequest(
            start_time=window.start,
            end_time=window.end,
            log_stream_id=scope.source_stream_id,
            filters=[],
            interval=max(5, min(interval_minutes, 1440)),
            group_by=group_by,
        )
        response = query_metrics_v2.sync(
            project_id=scope.project_id,
            client=GalileoPythonConfig.get().api_client,
            body=body,
        )
        if response is None:
            raise RuntimeError("Galileo returned no metrics response.")
        if not hasattr(response, "aggregate_metrics"):
            raise RuntimeError(f"Galileo rejected the metrics query: {response}")
        catalog = self.metric_catalog(scope)
        raw = response.to_dict()
        return sanitize(
            {
                "available_metrics": sorted(catalog.values()),
                "group_by_columns": raw.get("group_by_columns", []),
                "aggregate_metrics": self._friendly_metric_mapping(
                    raw.get("aggregate_metrics", {}),
                    catalog,
                ),
                "bucketed_metrics": self._friendly_metric_mapping(
                    raw.get("bucketed_metrics", {}),
                    catalog,
                ),
                "ems_captured_error": raw.get("ems_captured_error", False),
            },
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def metric_catalog(self, scope: Scope, sample_limit: int = 3) -> dict[str, str]:
        """Map server metric column IDs to friendly aliases using a tiny trace sample."""
        cache_key = (scope.project_id, scope.source_stream_id)
        if cache_key in self._metric_catalog_cache:
            return dict(self._metric_catalog_cache[cache_key])
        response = get_traces(
            project_id=scope.project_id,
            log_stream_id=scope.source_stream_id,
            limit=min(sample_limit, 3),
            starting_token=0,
        )
        records = [] if not isinstance(response.records, list) else response.records
        catalog: dict[str, str] = {
            "duration_ns": "duration_ns",
            "cost": "cost",
            "num_input_tokens": "num_input_tokens",
            "num_output_tokens": "num_output_tokens",
            "num_total_tokens": "num_total_tokens",
        }
        for record in records:
            data = record.to_dict()
            metric_info = data.get("metric_info") or {}
            if not isinstance(metric_info, dict):
                continue
            for column_id, info in metric_info.items():
                if isinstance(info, dict) and info.get("metric_key_alias"):
                    catalog[str(column_id)] = str(info["metric_key_alias"])
        self._metric_catalog_cache[cache_key] = catalog
        return dict(catalog)

    def resolve_metric_column(self, scope: Scope, metric: str) -> tuple[str, list[str]]:
        catalog = self.metric_catalog(scope)
        normalized = metric.lower().strip()
        for column_id, alias in catalog.items():
            if alias.lower() == normalized or column_id.lower() == normalized:
                return column_id, sorted(set(catalog.values()))
        # Let users omit common implementation suffixes while remaining exact
        # when there is only one unambiguous match.
        matches = [
            (column_id, alias)
            for column_id, alias in catalog.items()
            if alias.lower().removesuffix("_gpt") == normalized
        ]
        if len(matches) == 1:
            return matches[0][0], sorted(set(catalog.values()))
        available = ", ".join(sorted(set(catalog.values()))) or "none"
        raise ValueError(
            f"Metric {metric!r} is not available on the selected Log Stream. "
            f"Available metrics: {available}."
        )

    def search_low_scoring_traces(
        self,
        scope: Scope,
        window: TimeWindow,
        *,
        metric: str,
        threshold: float,
        limit: int,
    ) -> dict[str, Any]:
        metric_column, _ = self.resolve_metric_column(scope, metric)
        # The server-side metric filter currently returns an internal error for
        # some hosted streams. Keep the operation cost-predictable by reading one
        # bounded page from the selected stream and filtering it locally.
        response = get_traces(
            project_id=scope.project_id,
            log_stream_id=scope.source_stream_id,
            filters=[],
            sort=LogRecordsSortClause(column_id="created_at", ascending=False),
            limit=self.settings.max_trace_candidates,
            starting_token=0,
        )
        records = [] if not isinstance(response.records, list) else response.records
        matches: list[tuple[float, dict[str, Any]]] = []
        in_window = 0
        for record in records:
            data = record.to_dict()
            created_at = self._as_datetime(data.get("created_at"))
            if created_at is None or not window.start <= created_at <= window.end:
                continue
            in_window += 1
            score = self._metric_score(data.get("metric_info"), metric_column)
            if score is None or score >= threshold:
                continue
            data["selected_metric"] = {"name": metric, "score": score}
            matches.append(
                (
                    score,
                    sanitize(data, self.settings.secret_values(), 2500),
                )
            )
        matches.sort(key=lambda item: item[0])
        return {
            "traces": [item[1] for item in matches[:limit]],
            "candidates_examined": len(records),
            "candidates_in_time_window": in_window,
            "candidate_limit": self.settings.max_trace_candidates,
            "search_mode": "bounded_recent_sample",
            "exhaustive": False,
        }

    @staticmethod
    def _friendly_metric_mapping(value: Any, catalog: dict[str, str]) -> Any:
        secondary_suffixes = (
            "_ems_error_code",
            "_error_message",
            "_scorer_version_id",
            "_input_tokens",
            "_output_tokens",
            "_total_tokens",
            "_metric_cost",
            "_model_alias",
            "_num_judges",
        )
        if isinstance(value, dict):
            friendly: dict[str, Any] = {}
            for raw_key, item in value.items():
                key = str(raw_key)
                for column_id, alias in catalog.items():
                    key = key.replace(column_id, alias)
                if key.endswith(secondary_suffixes):
                    continue
                friendly[key] = GalileoService._friendly_metric_mapping(item, catalog)
            return friendly
        if isinstance(value, list):
            return [
                GalileoService._friendly_metric_mapping(item, catalog)
                for item in value[:50]
            ]
        return value

    def get_trace_details(self, scope: Scope, trace_id: str, span_limit: int = 50) -> dict[str, Any]:
        response = get_trace_by_id.sync(
            project_id=scope.project_id,
            trace_id=trace_id,
            client=GalileoPythonConfig.get().api_client,
        )
        if response is None or not hasattr(response, "to_dict"):
            raise LookupError(f"Trace {trace_id!r} was not found.")
        data = response.to_dict()
        spans = data.get("spans")
        if isinstance(spans, list):
            data["spans"] = spans[: min(span_limit, 100)]
        return sanitize(
            data,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    @staticmethod
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

    @staticmethod
    def _metric_score(metric_info: Any, column_id: str) -> float | None:
        if not isinstance(metric_info, dict):
            return None
        info = metric_info.get(column_id)
        if not isinstance(info, dict):
            return None
        for key in ("multijudge_average", "value", "score"):
            raw = info.get(key)
            if isinstance(raw, list) and raw:
                raw = raw[0]
            if isinstance(raw, bool | int | float):
                return float(raw)
        return None

    def list_datasets(self, scope: Scope, limit: int = 50) -> list[dict[str, Any]]:
        datasets = Dataset.list(project_id=scope.project_id, limit=min(limit, 50))
        return [self._resource_summary(item) for item in datasets]

    def get_dataset(self, scope: Scope, name: str) -> Dataset | None:
        cached = self._session_datasets.get((scope.project_id, name))
        if cached is not None:
            return cached
        # Dataset.get(name=...) is not project-scoped in this SDK version. Select
        # from the already project-scoped list to prevent cross-project access.
        return next(
            (dataset for dataset in Dataset.list(project_id=scope.project_id, limit=100) if dataset.name == name),
            None,
        )

    def create_or_extend_dataset_from_traces(
        self,
        scope: Scope,
        *,
        dataset_name: str,
        trace_ids: list[str],
    ) -> dict[str, Any]:
        dataset = self.get_dataset(scope, dataset_name)
        if dataset is None:
            # Create with one trace-derived row, then append the remaining trace
            # records through the copy API so the server preserves trace fields.
            first = self.get_trace_details(scope, trace_ids[0], span_limit=1)
            row = {
                "input": first.get("input", ""),
                "output": first.get("output", ""),
                "trace_id": trace_ids[0],
                "source_project": scope.project_name,
                "source_log_stream": scope.source_stream_name,
            }
            # The high-level Dataset(...).create() convenience method does not
            # accept a project in this SDK version. Use the datasets service so
            # the new resource is associated with the exact selected project.
            dataset = Datasets().create(
                name=dataset_name,
                content=[row],
                project_id=scope.project_id,
            )
            self._session_datasets[(scope.project_id, dataset_name)] = dataset
            remaining = trace_ids[1:]
        else:
            remaining = trace_ids
        if remaining:
            body = UpdateDatasetContentRequest(
                edits=[
                    DatasetCopyRecordData(
                        ids=remaining,
                        project_id=scope.project_id,
                        prepend=False,
                    )
                ]
            )
            update_dataset_content.sync(
                dataset_id=dataset.id,
                client=GalileoPythonConfig.get().api_client,
                body=body,
            )
        return self._resource_summary(dataset)

    def list_experiments(self, scope: Scope) -> list[dict[str, Any]]:
        return [
            self._experiment_summary(item)
            for item in Experiment.list(project_id=scope.project_id)[:50]
        ]

    def get_experiment(self, scope: Scope, name: str) -> Experiment | None:
        return Experiment.get(name=name, project_id=scope.project_id)

    def list_prompts(self, scope: Scope, limit: int = 50) -> list[dict[str, Any]]:
        prompts = Prompt.list(project_id=scope.project_id, limit=min(limit, 50))
        summaries = []
        for prompt in prompts:
            summary = self._prompt_summary(prompt)
            selected = getattr(prompt, "selected_version", None)
            if selected is not None:
                summary["version"] = getattr(selected, "version", None)
                summary["version_id"] = getattr(selected, "id", None)
            summaries.append(summary)
        return summaries

    def get_prompt(self, scope: Scope, name: str) -> Prompt | None:
        return next(
            (
                item
                for item in Prompt.list(project_id=scope.project_id, limit=100)
                if item.name == name
            ),
            None,
        )

    def create_prompt_version(
        self,
        scope: Scope,
        *,
        prompt_name: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        prompt = self.get_prompt(scope, prompt_name)
        if prompt is None:
            raise LookupError(f"Prompt {prompt_name!r} does not exist in the selected project.")
        messages = list(prompt.messages)
        replacement = Message(role=MessageRole.system, content=system_prompt)
        for index, message in enumerate(messages):
            if message.role == MessageRole.system:
                messages[index] = replacement
                break
        else:
            messages.insert(0, replacement)
        updated = prompt.create_version(messages=messages)
        summary = self._resource_summary(updated)
        selected = getattr(updated, "selected_version", None)
        summary["version"] = getattr(selected, "version", None)
        summary["version_id"] = getattr(selected, "id", None)
        return summary

    def run_experiment(
        self,
        scope: Scope,
        *,
        name: str,
        dataset_name: str,
        prompt_name: str,
        metrics: list[str],
    ) -> dict[str, Any]:
        dataset = self.get_dataset(scope, dataset_name)
        if dataset is None:
            raise LookupError(f"Dataset {dataset_name!r} does not exist in the selected project.")
        prompt = self.get_prompt(scope, prompt_name)
        if prompt is None:
            raise LookupError(f"Prompt {prompt_name!r} does not exist in the selected project.")
        experiment = Experiment(
            name=name,
            dataset=dataset,
            prompt=prompt,
            model=self.settings.model,
            metrics=metrics,
            project_id=scope.project_id,
        ).create()
        return self._experiment_summary(experiment)

    def compare_experiments(
        self,
        scope: Scope,
        *,
        baseline_name: str,
        candidate_name: str,
    ) -> dict[str, Any]:
        baseline = self.get_experiment(scope, baseline_name)
        candidate = self.get_experiment(scope, candidate_name)
        if baseline is None:
            raise LookupError(f"Baseline experiment {baseline_name!r} was not found.")
        if candidate is None:
            raise LookupError(f"Candidate experiment {candidate_name!r} was not found.")
        baseline_summary = self._experiment_summary(baseline)
        candidate_summary = self._experiment_summary(candidate)
        baseline_values = self._flatten_numbers(baseline_summary.get("aggregate_metrics", {}))
        candidate_values = self._flatten_numbers(candidate_summary.get("aggregate_metrics", {}))
        deltas = {
            key: candidate_values[key] - baseline_values[key]
            for key in sorted(baseline_values.keys() & candidate_values.keys())
        }
        return {
            "baseline": baseline_summary,
            "candidate": candidate_summary,
            "numeric_deltas_candidate_minus_baseline": deltas,
        }

    def dataset_row_count(self, dataset: Dataset) -> int:
        if isinstance(getattr(dataset, "num_rows", None), int):
            return int(dataset.num_rows)
        content = dataset.get_content()
        if content is None:
            return 0
        data = content.to_dict() if hasattr(content, "to_dict") else {}
        for key in ("rows", "data", "content"):
            rows = data.get(key)
            if isinstance(rows, list):
                return len(rows)
        return 0

    def dataset_rows_bounded(
        self,
        scope: Scope,
        dataset_name: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        dataset = self.get_dataset(scope, dataset_name)
        if dataset is None:
            raise LookupError(f"Dataset {dataset_name!r} was not found.")
        rows = self.dataset_row_count(dataset)
        if rows > limit:
            raise BudgetExceeded(
                f"Dataset {dataset_name!r} has {rows} rows; bounded coverage limit is {limit}."
            )
        content = dataset.get_content()
        if content is None:
            return []
        data = content.to_dict() if hasattr(content, "to_dict") else {}
        raw_rows = data.get("rows", [])
        if not isinstance(raw_rows, list):
            return []
        return sanitize(
            raw_rows[:limit],
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    @staticmethod
    def _resource_summary(resource: Any) -> dict[str, Any]:
        return {
            key: getattr(resource, key, None)
            for key in (
                "id",
                "name",
                "project_id",
                "project_name",
                "created_at",
                "updated_at",
                "num_rows",
                "column_names",
                "draft",
            )
            if getattr(resource, key, None) is not None
        }

    @staticmethod
    def _prompt_summary(prompt: Prompt) -> dict[str, Any]:
        summary = GalileoService._resource_summary(prompt)
        for key in (
            "selected_version_number",
            "selected_version_id",
            "total_versions",
            "all_available_versions",
            "max_version",
        ):
            value = getattr(prompt, key, None)
            if value is not None:
                summary[key] = value
        return summary

    @staticmethod
    def _experiment_summary(experiment: Experiment) -> dict[str, Any]:
        summary = GalileoService._resource_summary(experiment)
        for key in (
            "aggregate_metrics",
            "metric_aggregates",
            "status",
            "rank",
            "ranking_score",
            "dataset_id",
            "dataset_name",
            "prompt_id",
            "prompt_name",
            "model_alias",
            "metrics",
        ):
            value = getattr(experiment, key, None)
            if value is not None:
                summary[key] = value.to_dict() if hasattr(value, "to_dict") else value
        return sanitize(summary, max_chars=6000)

    @staticmethod
    def _flatten_numbers(value: Any, prefix: str = "") -> dict[str, float]:
        flattened: dict[str, float] = {}
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                flattened.update(GalileoService._flatten_numbers(item, child))
        elif isinstance(value, bool | int | float) and not isinstance(value, bool):
            flattened[prefix] = float(value)
        return flattened
