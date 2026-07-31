from __future__ import annotations

from .prompts import STARTER_REQUESTS
from .use_cases import print_use_case_menu


def print_starter_requests() -> None:
    print("\nTry one of these:")
    for index, request in enumerate(STARTER_REQUESTS, start=1):
        print(f"  {index}. {request}")


def print_guided_start() -> None:
    print_use_case_menu()
    print(
        "\nChoose a workflow number, type your own request, or enter "
        "'usecases' to show this menu again."
    )


def print_demo_walkthrough() -> None:
    print(
        """
Guided EvalOps demo
-------------------
1. Confirm the configured project and source Log Stream.
2. Optionally run `demo-seed` to write 12 deterministic, zero-LLM-call traces.
3. Select `evalops-demo-source` as the source Log Stream.
4. Run: "Summarize quality metrics for the last 24 hours."
5. Run: "Find traces with demo_quality below 0.6."
6. Ask the agent to inspect no more than three returned traces.
7. Ask it to prepare a regression dataset from those trace IDs.
8. Review and approve the dataset write preview.
9. List prompts/datasets in Galileo, then run a bounded experiment.
10. Review the estimate before approving any model or evaluator calls.

Trace and metric queries stay within one selected project and one selected Log
Stream. The optional environment comparison reads only capped metadata from one
exact target project.
"""
    )
