from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GuidedUseCase:
    key: str
    title: str
    description: str
    opening_request: str


GUIDED_USE_CASES = (
    GuidedUseCase(
        key="quality-drop",
        title="Investigate a quality drop",
        description="Discover available metrics, measure the change, and inspect representative failures.",
        opening_request=(
            "Start the guided 'Investigate a quality drop' workflow. First list the "
            "friendly metric names available on the selected Log Stream and summarize "
            "the default time window. Do not guess which quality metric matters. If "
            "there are multiple plausible metrics, ask me to select one before "
            "retrieving traces. Guide me one decision at a time."
        ),
    ),
    GuidedUseCase(
        key="failure-triage",
        title="Find and explain low-quality traces",
        description="Choose a metric and threshold, then inspect a small evidence-backed sample.",
        opening_request=(
            "Start the guided 'Find and explain low-quality traces' workflow. Discover "
            "the metrics available on the selected Log Stream, then ask me which metric "
            "and threshold define a failure. Do not retrieve detailed traces until I "
            "choose. Keep the search and inspection within the configured limits."
        ),
    ),
    GuidedUseCase(
        key="regression-dataset",
        title="Build a regression dataset",
        description="Find verified failures and safely convert selected traces into dataset rows.",
        opening_request=(
            "Start the guided 'Build a regression dataset' workflow. Help me define "
            "the failure criteria using available metrics, search a bounded sample, "
            "and verify candidate traces before proposing a dataset. Ask me for a "
            "dataset name if needed. Do not write anything until the application "
            "shows a complete preview and I explicitly approve it."
        ),
    ),
    GuidedUseCase(
        key="experiment-review",
        title="Review or compare experiments",
        description="Discover experiments and compare a user-selected baseline and candidate.",
        opening_request=(
            "Start the guided 'Review or compare experiments' workflow. List the "
            "available recent experiments first. Do not guess the baseline or "
            "candidate. Ask me to choose them, then compare numeric "
            "candidate-minus-baseline deltas using existing results only."
        ),
    ),
    GuidedUseCase(
        key="project-briefing",
        title="Get an EvalOps project briefing",
        description="Summarize bounded metadata for datasets, prompts, and experiments.",
        opening_request=(
            "Give me a concise EvalOps briefing for the selected project. List bounded "
            "metadata for datasets, prompts, and recent experiments. Recommend the "
            "next useful EvalOps action from only the evidence you found. Do not query "
            "organization-wide traces."
        ),
    ),
    GuidedUseCase(
        key="safe-experiment",
        title="Prepare a bounded experiment",
        description="Choose an existing prompt and dataset, estimate cost, and require approval.",
        opening_request=(
            "Start the guided 'Prepare a bounded experiment' workflow. Discover "
            "available prompts and datasets, ask me to select them, and preview the "
            "maximum rows plus estimated generation and evaluator calls. Do not run "
            "the experiment until I explicitly approve the write preview."
        ),
    ),
    GuidedUseCase(
        key="project-doctor",
        title="Run Galileo Project Doctor",
        description="Audit bounded project health, hygiene, cost signals, and governance coverage.",
        opening_request=(
            "Start the advanced 'Galileo Project Doctor' workflow. Run the bounded "
            "rules-based project audit with a 30-day stale-resource threshold. "
            "Summarize high, medium, and low findings without inventing a health "
            "score. Ask me which finding I want to investigate or remediate."
        ),
    ),
    GuidedUseCase(
        key="coverage-gaps",
        title="Find production-to-dataset coverage gaps",
        description="Compare verified production failures with a small regression dataset.",
        opening_request=(
            "Start the advanced 'Production-to-dataset coverage gaps' workflow. "
            "First discover available metrics and help me select bounded failure "
            "criteria. Then search and inspect representative failures, list small "
            "candidate datasets, and ask me which dataset to compare. Do not claim "
            "semantic coverage from lexical similarity alone."
        ),
    ),
    GuidedUseCase(
        key="release-gate",
        title="Evaluate release readiness",
        description="Compare experiments against explicit user-selected release criteria.",
        opening_request=(
            "Start the advanced 'Release readiness gate' workflow. List recent "
            "experiments and their numeric metrics. Ask me to select an exact "
            "baseline, candidate, and release thresholds. Never invent thresholds. "
            "Produce GO only if every explicit criterion passes; otherwise HOLD."
        ),
    ),
    GuidedUseCase(
        key="cost-advisor",
        title="Optimize evaluation cost and budget",
        description="Estimate generation/evaluator calls before experiments or metric work.",
        opening_request=(
            "Start the advanced 'Evaluation cost advisor' workflow. Discover datasets "
            "and available metrics, then ask me to choose a dataset or row count, "
            "metrics, number of runs, and sample percentage. Calculate generation "
            "and evaluator calls transparently. Do not invent a currency cost."
        ),
    ),
    GuidedUseCase(
        key="control-builder",
        title="Build and simulate an Agent Control",
        description="Create a validated regex control proposal and test it on inspected traces.",
        opening_request=(
            "Start the advanced 'Agent Control builder' workflow. Ask what unsafe "
            "input or output pattern should be detected and whether the action should "
            "observe, steer, or deny. Use only inspected traces for local simulation. "
            "List Agent Control agents before asking where to attach it, and never "
            "publish without a write preview and explicit approval."
        ),
    ),
    GuidedUseCase(
        key="environment-drift",
        title="Compare or bootstrap Galileo environments",
        description="Diff the selected project against one exact target project without copying traces.",
        opening_request=(
            "Start the advanced 'Environment drift' workflow. Ask me for one exact "
            "target Galileo project, compare bounded resource metadata, prompt "
            "versions, stream metrics, and collaborator roles, and explain the drift. "
            "Offer to create only explicitly selected missing Log Streams after "
            "approval. Never copy traces, datasets, collaborators, or delete resources."
        ),
    ),
    GuidedUseCase(
        key="signal-handoff",
        title="Investigate a Galileo Signal",
        description="Turn user-provided Signal context into a scoped incident investigation.",
        opening_request=(
            "Start the advanced 'Galileo Signal handoff' workflow. Ask me for the "
            "Signal name or link, metric, threshold, and time window. Record that "
            "context without claiming to query a Signals API, validate the metric "
            "against the selected Log Stream, then run the normal bounded incident "
            "investigation."
        ),
    ),
)


GUIDED_USE_CASES_BY_KEY = {use_case.key: use_case for use_case in GUIDED_USE_CASES}


def print_use_case_menu() -> None:
    print("\nWhat would you like to do?")
    print("--------------------------")
    for index, use_case in enumerate(GUIDED_USE_CASES, start=1):
        print(f"  {index}. {use_case.title}")
        print(f"     {use_case.description}")
    print("  0. Ask my own question")


def choose_use_case(
    input_fn: Callable[[str], str] = input,
) -> GuidedUseCase | None:
    print_use_case_menu()
    while True:
        selection = input_fn("\nChoose a workflow: ").strip()
        if selection == "0":
            return None
        if selection.isdigit() and 1 <= int(selection) <= len(GUIDED_USE_CASES):
            return GUIDED_USE_CASES[int(selection) - 1]
        if selection in GUIDED_USE_CASES_BY_KEY:
            return GUIDED_USE_CASES_BY_KEY[selection]
        print(f"Enter 0–{len(GUIDED_USE_CASES)} or a workflow key.")
