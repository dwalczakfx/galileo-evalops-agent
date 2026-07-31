from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from evalops_agent.config import Settings
from evalops_agent.galileo_api import GalileoService
from evalops_agent.models import Scope, TimeWindow


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


class GalileoServiceTests(unittest.TestCase):
    @patch("evalops_agent.galileo_api.get_traces")
    def test_metric_search_supports_high_values_and_descending_order(
        self,
        get_traces: MagicMock,
    ) -> None:
        now = datetime.now(timezone.utc)
        get_traces.return_value = SimpleNamespace(
            records=[
                SimpleNamespace(
                    to_dict=lambda score=score, index=index: {
                        "id": f"trace-{index}",
                        "created_at": now,
                        "metric_info": {"cost-id": {"value": score}},
                    }
                )
                for index, score in enumerate((0.4, 0.9, 0.7), start=1)
            ]
        )
        service = GalileoService(settings())
        service.resolve_metric_column = MagicMock(
            return_value=("cost-id", ["cost"])
        )

        result = service.search_metric_traces(
            SCOPE,
            TimeWindow(start=now - timedelta(hours=1), end=now + timedelta(seconds=1)),
            metric="cost",
            comparison="above",
            threshold=0.5,
            limit=10,
        )

        self.assertEqual(
            [trace["id"] for trace in result["traces"]],
            ["trace-2", "trace-3"],
        )
        self.assertEqual(result["comparison"], "above")

    @patch("evalops_agent.galileo_api.Datasets")
    def test_new_dataset_is_created_in_exact_selected_project(
        self,
        datasets_class: MagicMock,
    ) -> None:
        datasets_class.return_value.create.return_value = SimpleNamespace(
            id="dataset-id",
            name="regressions",
        )
        service = GalileoService(settings())
        service.get_dataset = MagicMock(return_value=None)
        service.get_trace_details = MagicMock(
            return_value={"input": "request", "output": "response"}
        )

        result = service.create_or_extend_dataset_from_traces(
            SCOPE,
            dataset_name="regressions",
            trace_ids=["trace-1"],
        )

        datasets_class.return_value.create.assert_called_once_with(
            name="regressions",
            content=[
                {
                    "input": "request",
                    "output": "response",
                    "trace_id": "trace-1",
                    "source_project": "project-a",
                    "source_log_stream": "production",
                }
            ],
            project_id="project-id",
        )
        self.assertEqual(result["name"], "regressions")


if __name__ == "__main__":
    unittest.main()
