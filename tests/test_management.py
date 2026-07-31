from __future__ import annotations

import unittest

from evalops_agent.management import (
    analyze_coverage,
    build_environment_diff,
    build_project_doctor_report,
    estimate_evaluation_budget,
    evaluate_release_gate,
)


class ManagementAnalysisTests(unittest.TestCase):
    def test_project_doctor_reports_deterministic_findings(self) -> None:
        snapshot = {
            "project": {"name": "project-a"},
            "telemetry_stream_known": True,
            "log_streams": [
                {
                    "name": "production",
                    "enabled_metrics": [],
                    "sampled_trace_count": 0,
                    "trace_sample_limit": 1,
                    "sampled_session_count": 2,
                    "empty_sessions_in_sample": 2,
                },
                {
                    "name": "evalops-agent",
                    "enabled_metrics": [],
                    "sampled_trace_count": 1,
                    "latest_trace_at": "2026-07-30T12:00:00+00:00",
                    "sampled_session_count": 1,
                    "empty_sessions_in_sample": 0,
                },
            ],
            "datasets": [{"name": "empty", "num_rows": 0}],
            "prompts": [{"name": "support", "selected_version_number": 1}],
            "experiments": [],
            "collaborators": [{"email": "owner@example.test", "role": "owner"}],
            "selected_stream_metric_summary": {"ems_captured_error": True},
            "sampling": {"stream_limit": 10},
        }
        report = build_project_doctor_report(
            snapshot,
            telemetry_stream_name="evalops-agent",
            stale_days=30,
        )
        finding_ids = {item["id"] for item in report["findings"]}
        self.assertIn("no-traces-production", finding_ids)
        self.assertIn("empty-sessions-production", finding_ids)
        self.assertIn("metrics-missing-production", finding_ids)
        self.assertIn("empty-datasets", finding_ids)
        self.assertIn("prompts-without-experiments", finding_ids)
        self.assertIn("metric-evaluation-errors", finding_ids)
        self.assertIsNone(report["health_score"])

    def test_environment_diff_is_non_destructive(self) -> None:
        source = {
            "project": {"name": "dev"},
            "log_streams": [
                {"name": "app", "enabled_metrics": ["correctness"]},
                {"name": "evalops-agent", "enabled_metrics": []},
            ],
            "datasets": [{"name": "regression"}],
            "prompts": [{"name": "support", "selected_version_number": 2}],
            "experiments": [],
            "collaborators": [{"email": "user@example.test", "role": "editor"}],
        }
        target = {
            "project": {"name": "prod"},
            "log_streams": [{"name": "app", "enabled_metrics": ["cost"]}],
            "datasets": [],
            "prompts": [{"name": "support", "selected_version_number": 1}],
            "experiments": [],
            "collaborators": [{"email": "user@example.test", "role": "viewer"}],
        }
        report = build_environment_diff(source, target)
        self.assertEqual(
            report["safe_bootstrap_candidates"]["log_streams"],
            ["evalops-agent"],
        )
        self.assertEqual(report["prompt_version_drift"][0]["source_version"], 2)
        self.assertTrue(report["collaborator_role_drift"])
        self.assertIn("Trace data is never copied.", report["excluded_automatic_actions"])

    def test_budget_estimate_is_transparent(self) -> None:
        result = estimate_evaluation_budget(
            rows=100,
            metric_count=3,
            runs=2,
            sample_percent=10,
            max_generation_calls=50,
            max_evaluator_calls=100,
        )
        self.assertEqual(result["sampled_rows"], 10)
        self.assertEqual(result["estimated_generation_calls"], 20)
        self.assertEqual(result["estimated_evaluator_calls"], 60)
        self.assertTrue(result["within_budget"])
        self.assertIsNone(result["monetary_cost"])

    def test_release_gate_requires_every_criterion(self) -> None:
        comparison = {
            "baseline": {
                "name": "baseline",
                "aggregate_metrics": {
                    "average_correctness": 0.8,
                    "average_cost": 0.02,
                },
            },
            "candidate": {
                "name": "candidate",
                "aggregate_metrics": {
                    "average_correctness": 0.9,
                    "average_cost": 0.03,
                },
            },
            "numeric_deltas_candidate_minus_baseline": {
                "average_correctness": 0.1,
                "average_cost": 0.01,
            },
        }
        result = evaluate_release_gate(
            comparison,
            [
                {
                    "metric": "average_correctness",
                    "source": "candidate",
                    "operator": ">=",
                    "value": 0.85,
                },
                {
                    "metric": "average_cost",
                    "source": "candidate",
                    "operator": "<=",
                    "value": 0.025,
                },
            ],
        )
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["criteria_passed"], 1)

    def test_coverage_analysis_marks_unrepresented_failure(self) -> None:
        report = analyze_coverage(
            [
                {
                    "id": "trace-tool",
                    "scenario": "failed_tool_false_success",
                    "output": "Refund completed despite billing service error",
                },
                {
                    "id": "trace-retrieval",
                    "scenario": "irrelevant_retrieval",
                    "output": "Unrelated password policy",
                },
            ],
            [
                {
                    "scenario": "failed_tool_false_success",
                    "input": "billing service error",
                    "output": "Do not report refund completed",
                }
            ],
            similarity_threshold=0.2,
        )
        self.assertEqual(report["trace_count"], 2)
        self.assertIn("trace-retrieval", report["gap_trace_ids"])


if __name__ == "__main__":
    unittest.main()
