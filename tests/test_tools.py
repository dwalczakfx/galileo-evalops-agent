from __future__ import annotations

import unittest
from dataclasses import replace

from evalops_agent.approvals import ApprovalGate
from evalops_agent.config import Settings
from evalops_agent.models import Scope
from evalops_agent.tools import ToolRegistry


class FakeService:
    def metric_catalog(self, scope):
        return {"metric-id": "correctness"}

    def profile_metric_values(self, scope, window, limit):
        return {
            "window": window.public_dict(),
            "configured_metrics_observed": ["correctness", "factuality"],
            "metrics_with_numeric_values": ["correctness"],
            "metrics_without_numeric_values": ["factuality"],
            "metrics_not_observed_in_window": [],
            "metric_profiles": [
                {
                    "metric": "correctness",
                    "samples_present": 10,
                    "samples_with_numeric_value": 10,
                    "numeric_coverage_percent": 100.0,
                    "minimum": 0.4,
                    "maximum": 0.9,
                    "average": 0.7,
                }
            ],
            "candidates_examined": 10,
            "candidates_in_time_window": 10,
            "candidate_limit": limit,
            "search_mode": "bounded_recent_sample",
            "exhaustive": False,
        }

    def query_metrics(self, scope, window, group_by=None, interval_minutes=60):
        return {"aggregate_metrics": {"requests_count": 10, "average_correctness": 0.8}}

    def search_low_scoring_traces(self, scope, window, metric, threshold, limit):
        return {
            "traces": [{"id": f"trace-{index}", metric: 0.2} for index in range(limit)],
            "candidates_examined": limit,
            "candidates_in_time_window": limit,
            "candidate_limit": 50,
            "search_mode": "bounded_recent_sample",
            "exhaustive": False,
        }

    def search_metric_traces(
        self,
        scope,
        window,
        metric,
        comparison,
        threshold,
        limit,
    ):
        return {
            "traces": [
                {"id": f"trace-{index}", metric: threshold + 0.1}
                for index in range(limit)
            ],
            "candidates_examined": limit,
            "candidates_in_time_window": limit,
            "candidate_limit": 50,
            "search_mode": "bounded_recent_sample",
            "exhaustive": False,
            "comparison": comparison,
        }

    def get_trace_details(self, scope, trace_id, span_limit=50):
        return {"trace": {"id": trace_id}, "spans": []}

    def list_datasets(self, scope, limit=50):
        return []

    def list_experiments(self, scope):
        return []

    def list_prompts(self, scope, limit=50):
        return [{"id": "prompt-id", "name": "prompt-v1"}]

    def compare_experiments(self, scope, baseline_name, candidate_name):
        return {
            "baseline": {"name": baseline_name},
            "candidate": {"name": candidate_name},
            "numeric_deltas_candidate_minus_baseline": {"correctness": 0.1},
        }


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
    source_stream_id="stream-id",
    telemetry_stream_name="evalops-agent",
    telemetry_stream_id="telemetry-id",
)


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry(
            settings(),
            SCOPE,
            FakeService(),
            ApprovalGate(dry_run=True),
        )

    def test_trace_search_is_capped(self) -> None:
        result = self.registry.search_low_scoring_traces(
            metric="correctness",
            threshold=0.6,
            hours=24,
            limit=99,
        )
        self.assertEqual(result["applied_limit"], 20)
        self.assertEqual(result["count"], 20)

    def test_high_cost_search_uses_above_direction_and_is_capped(self) -> None:
        result = self.registry.search_metric_traces(
            metric="cost",
            comparison="above",
            threshold=0.5,
            hours=24,
            limit=99,
        )
        self.assertEqual(result["comparison"], "above")
        self.assertEqual(result["applied_limit"], 20)
        self.assertEqual(result["count"], 20)

    def test_available_metrics_are_bounded_metadata(self) -> None:
        result = self.registry.list_available_metrics(hours=24)
        self.assertEqual(result["metrics_with_numeric_values"], ["correctness"])
        self.assertEqual(result["metrics_without_numeric_values"], ["factuality"])
        self.assertEqual(result["candidate_limit"], 50)

        cached = self.registry.list_available_metrics(hours=24)
        self.assertTrue(cached["cached"])

    def test_prompt_names_are_discoverable(self) -> None:
        result = self.registry.list_prompts()
        self.assertEqual(result[0]["name"], "prompt-v1")

    def test_experiment_comparison_is_read_only(self) -> None:
        result = self.registry.compare_experiments("baseline", "candidate")
        self.assertEqual(
            result["numeric_deltas_candidate_minus_baseline"]["correctness"],
            0.1,
        )

    def test_trace_details_require_previous_search(self) -> None:
        result = self.registry.execute("get_trace_details", {"trace_id": "not-searched"})
        self.assertFalse(result["ok"])

    def test_detail_limit_is_enforced(self) -> None:
        limited = replace(settings(), max_detailed_traces=1)
        registry = ToolRegistry(limited, SCOPE, FakeService(), ApprovalGate(dry_run=True))
        registry.allowed_trace_ids = {"trace-1", "trace-2"}
        self.assertTrue(registry.execute("get_trace_details", {"trace_id": "trace-1"})["ok"])
        self.assertFalse(registry.execute("get_trace_details", {"trace_id": "trace-2"})["ok"])

    def test_dataset_write_requires_inspected_traces(self) -> None:
        self.registry.allowed_trace_ids = {"trace-1"}
        result = self.registry.execute(
            "create_regression_dataset",
            {"dataset_name": "regressions", "trace_ids": ["trace-1"]},
        )
        self.assertFalse(result["ok"])
        self.assertIn("inspected", result["error"])


if __name__ == "__main__":
    unittest.main()
