from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GuidedUseCase:
    key: str
    title: str
    description: str
    opening_request: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowGroup:
    key: str
    title: str
    description: str
    use_case_keys: tuple[str, ...]
    aliases: tuple[str, ...] = ()


RECOMMENDED_USE_CASE = GuidedUseCase(
    key="recommended-check",
    title="Recommend what I should check first",
    description="Inspect bounded metadata and propose useful checks without requiring an example.",
    aliases=("recommend", "help me start", "what should i check"),
    opening_request=(
        "Start the recommendation-led onboarding workflow. I do not need to provide "
        "an example first. List the available metrics now, group only those metrics "
        "into quality, safety, and efficiency/operations, and propose exactly three "
        "useful checks. Use above-threshold checks for risk metrics such as prompt "
        "injection or SQL injection. Mark one as Recommended and explain why it is "
        "the best first check for this Log Stream. Use 24 hours and at most 10 "
        "traces as proposed defaults. Do not inspect trace details yet. Ask me to "
        "reply with 1, 2, 3, "
        "or 'run recommended'; interpret 'yes' as accepting the recommended option. "
        "Keep this initial recommendation menu under 180 words and defer detailed "
        "investigation guidance until I select an option."
    ),
)


GUIDED_USE_CASES = (
    RECOMMENDED_USE_CASE,
    GuidedUseCase(
        key="quality-drop",
        title="Investigate a quality drop",
        description="Measure a change and inspect representative failures.",
        opening_request=(
            "Start the guided 'Investigate a quality drop' workflow. Profile actual "
            "numeric metric coverage for the last 24 hours before recommending "
            "anything. Separate configured metrics with values from metrics with no "
            "values. Recommend only a populated quality metric and cite its sample "
            "coverage or observed range. Always report candidates examined and "
            "candidates inside the window. If no quality metric is populated, "
            "explain that and propose the most useful diagnostic next step. Do not "
            "make me invent an example. Ask one question at a time and interpret "
            "'yes' as "
            "accepting your last recommendation. Execute accepted bounded reads "
            "without asking for another confirmation."
        ),
    ),
    GuidedUseCase(
        key="failure-triage",
        title="Find and explain low-quality traces",
        description="Choose failure criteria and inspect a small evidence-backed sample.",
        opening_request=(
            "Start the guided 'Find and explain low-quality traces' workflow. "
            "Profile actual metric values and recommend only a populated quality "
            "metric. Propose a clearly labeled heuristic threshold only for "
            "a normalized quality metric, plus defaults of 24 hours and 10 traces. "
            "Ask me to accept or change one decision at a time. Use below-threshold "
            "search for quality, but above-threshold search for cost or latency."
        ),
    ),
    GuidedUseCase(
        key="signal-candidates",
        title="Explore important Signal candidates",
        description="Recommend quality, safety, or efficiency conditions worth monitoring.",
        aliases=("find a signal", "find a new signal", "suggest a signal"),
        opening_request=(
            "Start the proactive 'Signal candidates' workflow. The user does not "
            "already have a Signal. List available metrics now and recommend up to "
            "three concrete monitoring candidates, each with the correct direction: "
            "below for normalized quality and above for risk metrics, cost, token "
            "use, or latency. "
            "Explain why each matters, mark one Recommended, and propose 24 hours as "
            "the first investigation window. Do not claim to create or query Galileo "
            "Signals. Ask the user to choose a candidate or accept the recommendation."
        ),
    ),
    GuidedUseCase(
        key="signal-handoff",
        title="Investigate a known Galileo Signal",
        description="Turn an existing Signal name or link into a scoped investigation.",
        aliases=("investigate a galileo signal", "signal handoff"),
        opening_request=(
            "Start the guided 'Known Galileo Signal handoff' workflow. Ask first for "
            "only the Signal name or link. Then extract or ask for one missing fact "
            "at a time. Offer 24 hours and 10 traces as defaults, validate the metric "
            "against this Log Stream, and never imply that a Signals API was queried."
        ),
    ),
    GuidedUseCase(
        key="regression-dataset",
        title="Build a regression dataset",
        description="Turn verified production failures into reusable dataset rows.",
        opening_request=(
            "Start the guided 'Build a regression dataset' workflow. Recommend a "
            "quality metric from those available, offer bounded failure criteria, "
            "search and inspect candidates, then propose a dataset. Ask one decision "
            "at a time. Never write until a complete preview is explicitly approved."
        ),
    ),
    GuidedUseCase(
        key="coverage-gaps",
        title="Find production-to-dataset coverage gaps",
        description="Compare verified failures with a small regression dataset.",
        opening_request=(
            "Start the guided 'Production-to-dataset coverage gaps' workflow. "
            "Recommend bounded failure criteria from available metrics, inspect a "
            "small representative sample, list candidate datasets, and ask which one "
            "to compare. Treat lexical similarity only as an indicator, not proof."
        ),
    ),
    GuidedUseCase(
        key="experiment-review",
        title="Review or compare experiments",
        description="Compare a selected baseline and candidate using existing results.",
        opening_request=(
            "Start the guided 'Review or compare experiments' workflow. List recent "
            "experiments and recommend a likely comparison only when names or dates "
            "support it. Ask me to confirm baseline and candidate, then calculate "
            "candidate-minus-baseline numeric deltas from existing results."
        ),
    ),
    GuidedUseCase(
        key="safe-experiment",
        title="Prepare a bounded experiment",
        description="Select a prompt and dataset, estimate calls, then request approval.",
        opening_request=(
            "Start the guided 'Prepare a bounded experiment' workflow. Discover "
            "prompts and datasets, recommend a sensible starting pair when evidence "
            "supports one, and ask for confirmation one decision at a time. Preview "
            "rows, generation calls, and evaluator calls before any write."
        ),
    ),
    GuidedUseCase(
        key="release-gate",
        title="Evaluate release readiness",
        description="Apply explicit quality and cost criteria to experiment results.",
        opening_request=(
            "Start the guided 'Release readiness gate' workflow. List recent "
            "experiments and available numeric metrics. Recommend a likely baseline "
            "and candidate when supported, but require confirmation and explicit "
            "release thresholds. Produce GO only when every criterion passes."
        ),
    ),
    GuidedUseCase(
        key="project-briefing",
        title="Get an EvalOps project briefing",
        description="Review bounded datasets, prompts, experiments, and activity.",
        opening_request=(
            "Give me a concise EvalOps briefing for the selected project using bounded "
            "metadata. Identify evidence-backed gaps and finish with one Recommended "
            "next action plus two alternatives. Do not ask me what to inspect first."
        ),
    ),
    GuidedUseCase(
        key="project-doctor",
        title="Run Galileo Project Doctor",
        description="Audit bounded project health, hygiene, cost, and governance.",
        opening_request=(
            "Run the bounded Galileo Project Doctor now with a 30-day stale-resource "
            "threshold. Summarize findings by severity, then recommend the highest "
            "value next investigation. Do not invent a health score."
        ),
    ),
    GuidedUseCase(
        key="control-builder",
        title="Build and simulate an Agent Control",
        description="Validate a guardrail proposal before approval-gated publishing.",
        opening_request=(
            "Start the guided 'Agent Control builder' workflow. If I have no example, "
            "offer three common choices: credential disclosure, destructive Galileo "
            "requests, or prompt injection. Ask one decision at a time, simulate only "
            "on inspected traces, and never publish without approval."
        ),
    ),
    GuidedUseCase(
        key="cost-advisor",
        title="Optimize evaluation cost and budget",
        description="Estimate generation and evaluator calls before evaluation work.",
        opening_request=(
            "Start the guided 'Evaluation cost advisor' workflow. Discover bounded "
            "dataset metadata and available metrics, recommend a conservative sample "
            "when I have no plan, and ask one decision at a time. Show formulas and "
            "calls, but never invent currency prices."
        ),
    ),
    GuidedUseCase(
        key="environment-drift",
        title="Compare or bootstrap Galileo environments",
        description="Compare one exact target project without copying trace data.",
        opening_request=(
            "Start the guided 'Environment drift' workflow. Ask for one exact target "
            "project, compare bounded metadata, explain the most important drift, and "
            "recommend a safe next action. Create only selected missing Log Streams "
            "after approval; never copy or delete data."
        ),
    ),
)


GUIDED_USE_CASES_BY_KEY = {use_case.key: use_case for use_case in GUIDED_USE_CASES}


WORKFLOW_GROUPS = (
    WorkflowGroup(
        key="production-quality",
        title="Investigate production quality",
        description="Quality changes, trace failures, and Signal candidates.",
        aliases=("production", "quality", "investigate"),
        use_case_keys=(
            "quality-drop",
            "failure-triage",
            "signal-candidates",
            "signal-handoff",
        ),
    ),
    WorkflowGroup(
        key="evaluations-release",
        title="Improve evaluations and releases",
        description="Regression data, coverage, experiments, and release gates.",
        aliases=("evaluations", "experiments", "release"),
        use_case_keys=(
            "regression-dataset",
            "coverage-gaps",
            "experiment-review",
            "safe-experiment",
            "release-gate",
        ),
    ),
    WorkflowGroup(
        key="govern-manage",
        title="Govern and manage Galileo",
        description="Project health, Agent Control, budgets, and environments.",
        aliases=("govern", "manage", "operations"),
        use_case_keys=(
            "project-briefing",
            "project-doctor",
            "control-builder",
            "cost-advisor",
            "environment-drift",
        ),
    ),
)


def _normalize(value: str) -> str:
    return " ".join(
        value.strip().lower().replace("_", " ").replace("-", " ").split()
    )


USE_CASES_BY_ALIAS = {
    _normalize(alias): use_case
    for use_case in GUIDED_USE_CASES
    for alias in (use_case.key, use_case.title, *use_case.aliases)
}
GROUPS_BY_ALIAS = {
    _normalize(alias): group
    for group in WORKFLOW_GROUPS
    for alias in (group.key, group.title, *group.aliases)
}


def find_use_case(value: str) -> GuidedUseCase | None:
    return USE_CASES_BY_ALIAS.get(_normalize(value))


def find_workflow_group(value: str) -> WorkflowGroup | None:
    return GROUPS_BY_ALIAS.get(_normalize(value))


def print_use_case_menu() -> None:
    print("\nHow can I help?")
    print("---------------")
    print("  1. Recommend what I should check first (recommended)")
    print("     Discover relevant metrics and propose useful starting checks.")
    print("\nTopics")
    for index, group in enumerate(WORKFLOW_GROUPS, start=2):
        print(f"  {index}. {group.title}")
        print(f"     {group.description}")
    print("  0. Ask my own question")


def print_group_menu(group: WorkflowGroup) -> None:
    print(f"\n{group.title}")
    print("-" * len(group.title))
    for index, key in enumerate(group.use_case_keys, start=1):
        use_case = GUIDED_USE_CASES_BY_KEY[key]
        print(f"  {index}. {use_case.title}")
        print(f"     {use_case.description}")
    print("  b. Back to topics")


def choose_group_use_case(
    group: WorkflowGroup,
    input_fn: Callable[[str], str] = input,
) -> GuidedUseCase | None:
    print_group_menu(group)
    while True:
        selection = input_fn("\nChoose an option: ").strip()
        if _normalize(selection) in {"b", "back", "menu", "topics"}:
            return None
        if selection.isdigit() and 1 <= int(selection) <= len(group.use_case_keys):
            return GUIDED_USE_CASES_BY_KEY[group.use_case_keys[int(selection) - 1]]
        direct = find_use_case(selection)
        if direct is not None and direct.key in group.use_case_keys:
            return direct
        print(f"Enter 1–{len(group.use_case_keys)} or 'b' to go back.")


def select_use_case_from_menu(
    selection: str,
    input_fn: Callable[[str], str] = input,
) -> GuidedUseCase | None:
    normalized = _normalize(selection)
    if normalized in {"1", "recommended", "recommend"}:
        return RECOMMENDED_USE_CASE
    if selection.isdigit() and 2 <= int(selection) <= len(WORKFLOW_GROUPS) + 1:
        return choose_group_use_case(WORKFLOW_GROUPS[int(selection) - 2], input_fn)
    direct = find_use_case(selection)
    if direct is not None:
        return direct
    group = find_workflow_group(selection)
    if group is not None:
        return choose_group_use_case(group, input_fn)
    print(f"Choose 0–{len(WORKFLOW_GROUPS) + 1}, a topic, or type your own request.")
    return None


def choose_use_case(
    input_fn: Callable[[str], str] = input,
) -> GuidedUseCase | None:
    print_use_case_menu()
    while True:
        selection = input_fn("\nChoose a topic: ").strip()
        if selection == "0":
            return None
        selected = select_use_case_from_menu(selection, input_fn)
        if selected is not None:
            return selected
