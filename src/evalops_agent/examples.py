from __future__ import annotations

from .prompts import STARTER_REQUEST_GROUPS
from .use_cases import print_use_case_menu


def print_starter_requests() -> None:
    print("\nExample requests by topic")
    print("-------------------------")
    for title, requests in STARTER_REQUEST_GROUPS:
        print(f"\n{title}")
        for request in requests:
            print(f"  • {request}")


def print_guided_start() -> None:
    print_use_case_menu()
    print(
        "\nChoose one shortcut, combine options such as '1,2', open a topic, "
        "or type any request. Enter 'capabilities' for the full catalog."
    )


def print_demo_walkthrough() -> None:
    print(
        """
Guided EvalOps demo
-------------------
1. Review the configured project and source Log Stream shown in Working context.
   To choose different resources, start the command with `--select-scope`.
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
