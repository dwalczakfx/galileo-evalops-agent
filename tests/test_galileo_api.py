from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from evalops_agent.config import Settings
from evalops_agent.galileo_api import GalileoService
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
    source_stream_id="stream-id",
    telemetry_stream_name="evalops-agent",
    telemetry_stream_id="telemetry-id",
)


class GalileoServiceTests(unittest.TestCase):
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
