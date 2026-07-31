from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from evalops_agent.approvals import ApprovalDenied, ApprovalGate
from evalops_agent.config import Settings
from evalops_agent.models import Scope
from evalops_agent.tools import TOOL_SCHEMAS, ToolRegistry


def settings() -> Settings:
    return Settings.from_mapping(
        {
            "GALILEO_API_URL": "https://api.example.test",
            "GALILEO_API_KEY": "galileo-secret",
            "GALILEO_PROJECT": "source",
            "GALILEO_LOG_STREAM": "production",
            "OPENAI_API_KEY": "openai-secret",
            "EVALOPS_MODEL": "test-model",
            "AGENT_CONTROL_URL": "https://control.example.test",
            "AGENT_CONTROL_API_KEY_HEADER": "Galileo-API-Key",
        }
    )


SCOPE = Scope(
    project_name="source",
    project_id="source-id",
    source_stream_name="production",
    source_stream_id="stream-id",
    telemetry_stream_name="evalops-agent",
    telemetry_stream_id="telemetry-id",
)


class FakeAdvancedService:
    def project_snapshot(
        self,
        project_name,
        stream_limit,
        resource_limit,
        session_sample,
        include_activity,
    ):
        if project_name == "source":
            streams = [
                {
                    "name": "production",
                    "enabled_metrics": ["correctness"],
                    "sampled_trace_count": 1,
                    "latest_trace_at": "2026-07-30T12:00:00+00:00",
                    "sampled_session_count": 1,
                    "empty_sessions_in_sample": 0,
                },
                {
                    "name": "evalops-agent",
                    "enabled_metrics": [],
                    "sampled_trace_count": 1,
                    "latest_trace_at": "2026-07-30T12:00:00+00:00",
                    "sampled_session_count": 1,
                    "empty_sessions_in_sample": 0,
                },
            ]
        else:
            streams = [
                {
                    "name": "production",
                    "enabled_metrics": [],
                }
            ]
        return {
            "project": {"name": project_name},
            "log_streams": streams,
            "datasets": [{"name": "regression", "num_rows": 10}],
            "prompts": [{"name": "support", "selected_version_number": 1}],
            "experiments": [
                {
                    "name": "baseline",
                    "aggregate_metrics": {"average_correctness": 0.8},
                },
                {
                    "name": "candidate",
                    "aggregate_metrics": {"average_correctness": 0.9},
                },
            ],
            "collaborators": [],
            "sampling": {"stream_limit": stream_limit},
        }

    def query_metrics(self, scope, window, group_by=None, interval_minutes=60):
        return {"ems_captured_error": False, "aggregate_metrics": {}}

    def get_dataset(self, scope, name):
        if name == "regression":
            return SimpleNamespace(name=name, num_rows=10)
        return None

    def dataset_row_count(self, dataset):
        return dataset.num_rows

    def dataset_rows_bounded(self, scope, dataset_name, limit):
        return [
            {
                "scenario": "failed_tool_false_success",
                "output": "do not claim completion after an error",
            }
        ]

    def compare_experiments(self, scope, baseline_name, candidate_name):
        return {
            "baseline": {
                "name": baseline_name,
                "aggregate_metrics": {"average_correctness": 0.8},
            },
            "candidate": {
                "name": candidate_name,
                "aggregate_metrics": {"average_correctness": 0.9},
            },
            "numeric_deltas_candidate_minus_baseline": {
                "average_correctness": 0.1,
            },
        }

    def create_missing_log_streams(self, target_project_name, stream_names):
        return [{"name": name} for name in stream_names]

    def resolve_metric_column(self, scope, metric):
        if metric != "correctness":
            raise ValueError("unknown metric")
        return "metric-id", ["correctness"]


class FakeControlService:
    def list_controls_for_target(self, target_type, target_id, limit):
        return {"controls": []}

    def list_agents(self, limit):
        return {"agents": [{"agent_name": "support-agent"}]}

    def validate_control(self, definition):
        return {"success": True}

    def create_and_attach_control(self, name, definition, agent_name):
        return {"control": {"name": name}, "attached": True, "agent_name": agent_name}


class AdvancedToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry(
            settings(),
            SCOPE,
            FakeAdvancedService(),
            ApprovalGate(dry_run=True),
        )
        self.registry.control_service = FakeControlService()

    def test_project_doctor_is_bounded_and_cached(self) -> None:
        first = self.registry.run_project_doctor(stale_days=30)
        second = self.registry.run_project_doctor(stale_days=30)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertIsNone(first["health_score"])

    def test_all_advanced_tools_are_exposed_to_the_agent(self) -> None:
        names = {
            schema["function"]["name"]
            for schema in TOOL_SCHEMAS
        }
        self.assertTrue(
            {
                "run_project_doctor",
                "estimate_evaluation_budget",
                "analyze_dataset_coverage",
                "evaluate_release_readiness",
                "compare_project_environments",
                "bootstrap_missing_log_streams",
                "list_agent_control_agents",
                "propose_agent_control",
                "create_agent_control_from_proposal",
                "accept_signal_handoff",
            }.issubset(names)
        )

    def test_cost_advisor_uses_dataset_metadata(self) -> None:
        result = self.registry.estimate_evaluation_budget(
            dataset_name="regression",
            rows=None,
            metrics=["correctness", "instruction_adherence"],
            runs=1,
            sample_percent=50,
        )
        self.assertEqual(result["sampled_rows"], 5)
        self.assertEqual(result["estimated_evaluator_calls"], 10)

    def test_coverage_requires_inspected_traces(self) -> None:
        with self.assertRaises(PermissionError):
            self.registry.analyze_dataset_coverage(
                dataset_name="regression",
                trace_ids=["trace-1"],
                similarity_threshold=0.2,
            )
        self.registry.inspected_trace_ids.add("trace-1")
        self.registry._cache["trace_detail:trace-1"] = {
            "id": "trace-1",
            "scenario": "failed_tool_false_success",
            "output": "claimed completion after service error",
        }
        report = self.registry.analyze_dataset_coverage(
            dataset_name="regression",
            trace_ids=["trace-1"],
            similarity_threshold=0.2,
        )
        self.assertEqual(report["dataset"], "regression")

    def test_release_gate_is_deterministic(self) -> None:
        report = self.registry.evaluate_release_readiness(
            baseline_name="baseline",
            candidate_name="candidate",
            criteria=[
                {
                    "metric": "average_correctness",
                    "source": "candidate",
                    "operator": ">=",
                    "value": 0.85,
                }
            ],
        )
        self.assertEqual(report["decision"], "GO")

    def test_environment_bootstrap_requires_write_approval(self) -> None:
        report = self.registry.compare_project_environments("target")
        self.assertIn("evalops-agent", report["safe_bootstrap_candidates"]["log_streams"])
        with self.assertRaises(ApprovalDenied):
            self.registry.bootstrap_missing_log_streams(
                target_project_name="target",
                stream_names=["evalops-agent"],
            )

    def test_control_proposal_is_validated_before_write(self) -> None:
        self.registry.inspected_trace_ids.add("trace-1")
        self.registry._cache["trace_detail:trace-1"] = {
            "id": "trace-1",
            "output": "refund completed after billing service error",
        }
        proposal = self.registry.propose_agent_control(
            name="block-false-success",
            description="Do not report success after a tool error.",
            selector_path="output",
            regex_pattern=r"completed.*error",
            action="steer",
            stage="post",
            step_names=["support_agent"],
            trace_ids=["trace-1"],
        )
        self.assertTrue(proposal["validation"]["success"])
        self.assertTrue(proposal["server_validated"])
        self.registry.list_agent_control_agents()
        with self.assertRaises(ApprovalDenied):
            self.registry.create_agent_control_from_proposal(
                proposal_id=proposal["proposal_id"],
                agent_name="support-agent",
            )

    def test_control_creation_requires_agent_discovered_in_session(self) -> None:
        proposal = self.registry.propose_agent_control(
            name="block-secrets",
            description="Block secret-like output.",
            selector_path="output",
            regex_pattern=r"api[_-]?key",
            action="deny",
            stage="post",
            step_names=["support_agent"],
            trace_ids=[],
        )
        with self.assertRaises(PermissionError):
            self.registry.create_agent_control_from_proposal(
                proposal_id=proposal["proposal_id"],
                agent_name="unlisted-agent",
            )

    def test_control_rejects_unsafe_nested_regex(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.propose_agent_control(
                name="unsafe-regex",
                description="Unsafe regex.",
                selector_path="output",
                regex_pattern=r"(a+)+$",
                action="deny",
                stage="post",
                step_names=["support_agent"],
                trace_ids=[],
            )

    def test_control_cannot_publish_after_failed_server_validation(self) -> None:
        self.registry.control_service.validate_control = lambda definition: {
            "success": False
        }
        proposal = self.registry.propose_agent_control(
            name="invalid-control",
            description="Rejected by server validation.",
            selector_path="output",
            regex_pattern="unsafe",
            action="deny",
            stage="post",
            step_names=["support_agent"],
            trace_ids=[],
        )
        self.assertFalse(proposal["server_validated"])
        self.registry.list_agent_control_agents()
        with self.assertRaises(PermissionError):
            self.registry.create_agent_control_from_proposal(
                proposal_id=proposal["proposal_id"],
                agent_name="support-agent",
            )

    def test_experiment_respects_generation_call_ceiling(self) -> None:
        limited = replace(settings(), max_generation_calls=5)
        registry = ToolRegistry(
            limited,
            SCOPE,
            FakeAdvancedService(),
            ApprovalGate(dry_run=True),
        )
        with self.assertRaisesRegex(ValueError, "generation calls"):
            registry.run_experiment(
                experiment_name="candidate",
                dataset_name="regression",
                prompt_name="support",
                metrics=["correctness"],
            )

    def test_signal_handoff_does_not_claim_api_query(self) -> None:
        handoff = self.registry.accept_signal_handoff(
            signal_name="quality-drop",
            metric="correctness",
            threshold=0.6,
            hours=24,
            signal_url=None,
            notes=None,
        )
        self.assertFalse(handoff["signals_api_query_performed"])
        self.assertEqual(handoff["project"], "source")


if __name__ == "__main__":
    unittest.main()
