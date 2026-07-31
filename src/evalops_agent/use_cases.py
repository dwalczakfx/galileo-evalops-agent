from __future__ import annotations

import re
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


QUALITY_OVERVIEW_USE_CASE = GuidedUseCase(
    key="quality-overview",
    title="Show my Galileo quality overview",
    description="Summarize activity, quality, safety, cost, latency, and token metrics.",
    aliases=(
        "overview",
        "quality summary",
        "summarize quality metrics",
        "show quality metrics",
    ),
    opening_request=(
        "Give me a clear Galileo quality overview for the last 24 hours. Query the "
        "aggregate metric trend and the bounded metric-value profile before drawing "
        "conclusions. Present Activity first, then Quality and Safety, then Cost, "
        "Latency, and Tokens. Show total requests and failures when the aggregate API "
        "returns them. Treat server aggregate values as overall results. If a metric "
        "is available only from the bounded trace profile, put it in a separate "
        "'Bounded sample' section with its numeric sample count and never label it an "
        "overall aggregate. Include all useful friendly metric names returned by "
        "Galileo, not only a hard-coded shortlist. In the Overall metrics section, "
        "show every returned average_* aggregate exactly once, including zero-valued "
        "safety or retrieval metrics. Explain the strongest two findings and finish "
        "with up to three concrete next actions. Do not retrieve trace details. Keep "
        "the complete report under 300 words by using compact bullets. If the window "
        "contains no traces, report candidates examined and candidates inside the "
        "window, then offer a wider window."
    ),
)


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


QUICK_USE_CASES = (
    QUALITY_OVERVIEW_USE_CASE,
    RECOMMENDED_USE_CASE,
)


GUIDED_USE_CASES = (
    QUALITY_OVERVIEW_USE_CASE,
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


MAX_COMBINED_WORKFLOWS = 3


def parse_menu_indices(value: str, *, maximum: int) -> tuple[int, ...] | None:
    """Parse one or more numeric shortcuts without capturing conversational values."""
    stripped = value.strip()
    if not re.fullmatch(r"\d+(?:\s*[, +]\s*\d+)*", stripped):
        return None
    indices = tuple(dict.fromkeys(int(item) for item in re.findall(r"\d+", stripped)))
    if len(indices) > MAX_COMBINED_WORKFLOWS:
        raise ValueError(
            f"Choose at most {MAX_COMBINED_WORKFLOWS} workflows at a time."
        )
    if any(index < 1 or index > maximum for index in indices):
        raise ValueError(f"Choose numbers from 1 to {maximum}.")
    return indices


def combine_use_cases(use_cases: tuple[GuidedUseCase, ...]) -> GuidedUseCase:
    if not use_cases:
        raise ValueError("Select at least one workflow.")
    if len(use_cases) == 1:
        return use_cases[0]
    if len(use_cases) > MAX_COMBINED_WORKFLOWS:
        raise ValueError(
            f"Choose at most {MAX_COMBINED_WORKFLOWS} workflows at a time."
        )
    goals = "; ".join(
        f"{index}. {use_case.title} — {use_case.description}"
        for index, use_case in enumerate(use_cases, start=1)
    )
    return GuidedUseCase(
        key="combined-" + "-".join(use_case.key for use_case in use_cases),
        title="Combined: " + " + ".join(use_case.title for use_case in use_cases),
        description="A bounded plan combining selected Galileo outcomes.",
        opening_request=(
            "Start a combined guided workflow for these selected outcomes: "
            f"{goals}. Reuse shared bounded discovery instead of repeating queries. "
            "Begin with the useful read-only overview or evidence that the outcomes "
            "share, then clearly separate the result for each selected outcome. Do "
            "not expand into unselected capabilities. If a later step requires a "
            "write or a consequential choice, pause once with a concise combined "
            "plan and ask for that decision."
        ),
    )


def group_use_cases(
    group: WorkflowGroup,
    selection: str,
) -> tuple[GuidedUseCase, ...] | None:
    indices = parse_menu_indices(selection, maximum=len(group.use_case_keys))
    if indices is None:
        direct = find_use_case(selection)
        if direct is not None and direct.key in group.use_case_keys:
            return (direct,)
        return None
    return tuple(
        GUIDED_USE_CASES_BY_KEY[group.use_case_keys[index - 1]]
        for index in indices
    )


def print_use_case_menu() -> None:
    print("\nGalileo shortcuts — not limits")
    print("-------------------------------")
    for index, use_case in enumerate(QUICK_USE_CASES, start=1):
        suffix = " (recommended)" if use_case is QUALITY_OVERVIEW_USE_CASE else ""
        print(f"  {index}. {use_case.title}{suffix}")
        print(f"     {use_case.description}")
    print("\nExplore by topic")
    for index, group in enumerate(WORKFLOW_GROUPS, start=len(QUICK_USE_CASES) + 1):
        print(f"  {index}. {group.title}")
        print(f"     {group.description}")
    print("  0. Ask my own question")
    print(
        "\nChoose one shortcut, combine quick actions (for example 1,2), "
        "open a topic, or type any request."
    )


def print_group_menu(group: WorkflowGroup) -> None:
    print(f"\n{group.title}")
    print("-" * len(group.title))
    for index, key in enumerate(group.use_case_keys, start=1):
        use_case = GUIDED_USE_CASES_BY_KEY[key]
        print(f"  {index}. {use_case.title}")
        print(f"     {use_case.description}")
    print("  0. Ask my own question")
    print("  b. Back to all shortcuts")
    print(
        f"\nChoose one or up to {MAX_COMBINED_WORKFLOWS} workflows "
        "(for example 1,3), or type any request."
    )


def print_capability_catalog() -> None:
    print("\nFull capability catalog")
    print("-----------------------")
    print("These workflows are shortcuts. Free-form Galileo and EvalOps requests are welcome.")
    print("\nQuick actions")
    for use_case in QUICK_USE_CASES:
        print(f"  • {use_case.title} — {use_case.description}")
    for group in WORKFLOW_GROUPS:
        print(f"\n{group.title}")
        for key in group.use_case_keys:
            use_case = GUIDED_USE_CASES_BY_KEY[key]
            print(f"  • {use_case.title} — {use_case.description}")


def choose_group_use_case(
    group: WorkflowGroup,
    input_fn: Callable[[str], str] = input,
) -> GuidedUseCase | None:
    print_group_menu(group)
    while True:
        selection = input_fn("\nChoose an option: ").strip()
        if _normalize(selection) in {"b", "back", "menu", "topics"}:
            return None
        if selection == "0":
            return None
        try:
            selected = group_use_cases(group, selection)
        except ValueError as exc:
            print(exc)
            continue
        if selected is not None:
            return combine_use_cases(selected)
        print(
            f"Enter 1–{len(group.use_case_keys)}, combine up to "
            f"{MAX_COMBINED_WORKFLOWS}, or enter 'b'."
        )


def select_use_case_from_menu(
    selection: str,
    input_fn: Callable[[str], str] = input,
) -> GuidedUseCase | None:
    normalized = _normalize(selection)
    quick_aliases = {
        "overview": QUALITY_OVERVIEW_USE_CASE,
        "summary": QUALITY_OVERVIEW_USE_CASE,
        "recommended": RECOMMENDED_USE_CASE,
        "recommend": RECOMMENDED_USE_CASE,
    }
    if normalized in quick_aliases:
        return quick_aliases[normalized]
    maximum = len(QUICK_USE_CASES) + len(WORKFLOW_GROUPS)
    try:
        indices = parse_menu_indices(selection, maximum=maximum)
    except ValueError as exc:
        print(exc)
        return None
    if indices is not None:
        quick = tuple(
            QUICK_USE_CASES[index - 1]
            for index in indices
            if index <= len(QUICK_USE_CASES)
        )
        group_indices = tuple(
            index - len(QUICK_USE_CASES) - 1
            for index in indices
            if index > len(QUICK_USE_CASES)
        )
        if group_indices:
            if len(indices) > 1:
                print("Open one topic first, then combine workflows inside it.")
                return None
            return choose_group_use_case(WORKFLOW_GROUPS[group_indices[0]], input_fn)
        return combine_use_cases(quick)
    direct = find_use_case(selection)
    if direct is not None:
        return direct
    group = find_workflow_group(selection)
    if group is not None:
        return choose_group_use_case(group, input_fn)
    print(f"Choose 0–{maximum}, a topic, or type your own request.")
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
