from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from typing import Any

from .agent_control_api import AgentControlService
from .agent import EvalOpsAgent
from .approvals import ApprovalGate
from .config import ConfigurationError, Settings
from .demo import DEMO_CASES, seed_demo
from .examples import print_starter_requests
from .galileo_api import GalileoService
from .instrumentation import InstrumentedSession, TelemetryUploadError
from .model_api import ModelConnectionError, verify_model_connection
from .models import OperationPreview, Scope
from .policy_setup import STARTER_CONTROLS, StarterPolicyInstaller
from .presentation import (
    DEMO_OPTIONS,
    DEMO_OPTIONS_BY_KEY,
    DemoOption,
    choose_demo_option,
    print_demo_card,
    print_demo_menu,
)
from .security import sanitize
from .tools import ToolRegistry
from .use_cases import (
    find_use_case,
    find_workflow_group,
    print_use_case_menu,
    select_use_case_from_menu,
)


def _confirm(prompt: str, default_yes: bool = True) -> bool:
    suffix = " [Y/n] " if default_yes else " [y/N] "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default_yes
    return answer in {"y", "yes"}


def _choose_from(items: list[Any], label: str) -> Any:
    if not items:
        raise LookupError(f"No {label} are available.")
    for index, item in enumerate(items, start=1):
        print(f"  {index}. {item.name}")
    while True:
        raw = input("Selection: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return items[int(raw) - 1]
        print(f"Enter a number between 1 and {len(items)}.")


def _select_project(
    settings: Settings,
    service: GalileoService,
    *,
    project_arg: str | None,
    select_interactively: bool,
    allow_recovery: bool,
) -> Any:
    project_name = project_arg or settings.default_project
    if select_interactively and not project_arg:
        print("Select a Galileo project (names only; no traces or metrics are queried):")
        return _choose_from(service.list_projects(), "projects")

    project = service.get_project(project_name)
    if project is not None:
        return project
    if allow_recovery:
        print(
            f"Project {project_name!r} was not found. Select a Galileo project "
            "(names only; no traces or metrics are queried):"
        )
        return _choose_from(service.list_projects(), "projects")
    raise LookupError(
        f"Project {project_name!r} was not found. Correct GALILEO_PROJECT, pass "
        "--project, or run with --select-scope."
    )


def select_scope(
    settings: Settings,
    service: GalileoService,
    *,
    project_arg: str | None,
    stream_arg: str | None,
    select_interactively: bool,
    allow_recovery: bool,
) -> Scope:
    project = _select_project(
        settings,
        service,
        project_arg=project_arg,
        select_interactively=select_interactively,
        allow_recovery=allow_recovery,
    )

    stream_name = stream_arg or settings.default_source_stream
    if select_interactively and not stream_arg:
        print(f"Select a source Log Stream in {project.name!r}:")
        source = _choose_from(service.list_log_streams(project.id), "Log Streams")
    else:
        source = service.get_log_stream(project.id, stream_name)
    if source is None:
        if allow_recovery:
            print(f"Log Stream {stream_name!r} was not found. Select one:")
            source = _choose_from(service.list_log_streams(project.id), "Log Streams")
        else:
            raise LookupError(
                f"Log Stream {stream_name!r} was not found in project "
                f"{project.name!r}. Correct GALILEO_LOG_STREAM, pass --log-stream, "
                "or run with --select-scope."
            )

    if source.name == settings.telemetry_stream:
        raise ConfigurationError(
            "The source and EvalOps telemetry Log Streams must differ. "
            "Select another --log-stream or change EVALOPS_LOG_STREAM."
        )
    telemetry = service.get_log_stream(project.id, settings.telemetry_stream)
    return Scope(
        project_name=project.name,
        project_id=project.id,
        source_stream_name=source.name,
        source_stream_id=source.id,
        telemetry_stream_name=settings.telemetry_stream,
        telemetry_stream_id=telemetry.id if telemetry else None,
    )


def ensure_telemetry_stream(
    scope: Scope,
    service: GalileoService,
    approval: ApprovalGate,
) -> Scope:
    if scope.telemetry_stream_id:
        return scope
    approval.require(
        OperationPreview(
            operation="Create EvalOps telemetry Log Stream",
            project=scope.project_name,
            resource=scope.telemetry_stream_name,
            records=0,
        )
    )
    stream = service.create_log_stream(scope.project_name, scope.telemetry_stream_name)
    return replace(scope, telemetry_stream_id=stream.id)


def print_scope(scope: Scope, settings: Settings) -> None:
    print("\nWorking context")
    print("---------------")
    print(f"Project:          {scope.project_name}")
    print(f"Source stream:    {scope.source_stream_name}")
    print(f"Telemetry stream: {scope.telemetry_stream_name}")
    print(f"Default lookback: {settings.default_lookback_hours} hours")
    print(f"Trace limit:      {settings.max_traces_per_query}")
    print(f"Detail limit:     {settings.max_detailed_traces}")
    print("Change scope:     restart with --project/--log-stream or --select-scope")


def _allow_scope_recovery(args: argparse.Namespace) -> bool:
    """Allow a picker for invalid config only in a deliberate interactive run."""
    return bool(args.select_scope or (not args.yes and sys.stdin.isatty()))


def print_app_intro(scope: Scope) -> None:
    print(
        f"""
Galileo EvalOps Agent
---------------------
Purpose: help AI teams understand production quality, turn verified failures
into reusable evaluations, and safely manage common Galileo workflows.

This session can:
  • investigate metrics and representative traces in {scope.source_stream_name!r}
  • review datasets, prompts, experiments, release gates, and evaluation cost
  • audit project health and propose Agent Control guardrails

Safety: trace and metric reads stay inside the selected project and Log Stream.
Raw searches are capped, trace content is treated as untrusted, and every remote
write requires a visible preview and explicit approval. The agent records its
own LLM, tool, and control activity in {scope.telemetry_stream_name!r}.
""".strip()
    )


def run_doctor(settings: Settings, service: GalileoService, args: argparse.Namespace) -> int:
    print("Configuration")
    for key, value in settings.public_summary().items():
        print(f"  {key}: {value}")
    scope = select_scope(
        settings,
        service,
        project_arg=args.project,
        stream_arg=args.log_stream,
        select_interactively=args.select_scope,
        allow_recovery=args.select_scope,
    )
    print("\nConnectivity")
    print(f"  project: {scope.project_name} ✓")
    print(f"  source Log Stream: {scope.source_stream_name} ✓")
    ready = True
    try:
        model_check = verify_model_connection(settings)
    except ModelConnectionError as exc:
        safe_error = sanitize(str(exc), settings.secret_values(), 500)
        print(f"  model authentication/access: failed ({safe_error})")
        ready = False
    else:
        print(
            f"  model authentication/access: {model_check['model']} ✓ "
            "(0 generation calls)"
        )
    if scope.telemetry_stream_id:
        print(f"  telemetry Log Stream: {scope.telemetry_stream_name} ✓")
    else:
        print(f"  telemetry Log Stream: {scope.telemetry_stream_name} — run setup")
        ready = False
    control_service = AgentControlService(settings)
    try:
        control_service.get_agent(settings.agent_name)
    except Exception as exc:
        safe_error = sanitize(str(exc), settings.secret_values(), 500)
        print(f"  Agent Control registration/authentication: failed ({safe_error})")
        ready = False
    else:
        print("  Agent Control authentication: ✓")
        print("  EvalOps Agent registration: ✓")
        if scope.telemetry_stream_id:
            starter_names = {spec.name for spec in STARTER_CONTROLS}
            try:
                attached = control_service.list_controls_for_target(
                    target_type="log_stream",
                    target_id=scope.telemetry_stream_id,
                    limit=20,
                )
            except Exception as exc:
                safe_error = sanitize(str(exc), settings.secret_values(), 500)
                print(f"  Agent Control Log Stream attachments: failed ({safe_error})")
                ready = False
            else:
                attached_controls = (
                    attached.get("controls", [])
                    if isinstance(attached, dict)
                    else []
                )
                attached_names = {
                    str(item.get("name"))
                    for item in attached_controls
                    if isinstance(item, dict) and item.get("name")
                }
                attached_count = len(starter_names & attached_names)
                if starter_names.issubset(attached_names):
                    print(
                        "  Agent Control Log Stream attachments: "
                        f"{attached_count}/{len(starter_names)} on "
                        f"{scope.telemetry_stream_name} ✓"
                    )
                else:
                    print(
                        "  Agent Control Log Stream attachments: "
                        f"{attached_count}/{len(starter_names)} on "
                        f"{scope.telemetry_stream_name} — run setup "
                        "--with-agent-control"
                    )
                    ready = False
            try:
                effective = control_service.list_effective_controls(
                    agent_name=settings.agent_name,
                    target_type="log_stream",
                    target_id=scope.telemetry_stream_id,
                )
            except Exception as exc:
                safe_error = sanitize(str(exc), settings.secret_values(), 500)
                print(f"  Effective Agent Controls: failed ({safe_error})")
                ready = False
            else:
                controls = (
                    effective.get("controls", [])
                    if isinstance(effective, dict)
                    else []
                )
                names = {
                    str(item.get("name"))
                    for item in controls
                    if isinstance(item, dict) and item.get("name")
                }
                starter_count = len(starter_names & names)
                if starter_names.issubset(names):
                    print(
                        f"  Agent Control starter policy: {starter_count}/"
                        f"{len(starter_names)} effective ✓"
                    )
                elif names:
                    print(
                        f"  Effective Agent Controls: {len(names)} custom; starter "
                        f"coverage {starter_count}/{len(starter_names)}"
                    )
                else:
                    print(
                        "  Effective Agent Controls: none — run setup "
                        "--with-agent-control"
                    )
                    ready = False
                try:
                    runtime_result = control_service.probe_runtime_evaluation(
                        agent_name=settings.agent_name,
                        target_type="log_stream",
                        target_id=scope.telemetry_stream_id,
                    )
                except Exception as exc:
                    safe_error = sanitize(str(exc), settings.secret_values(), 500)
                    print(
                        "  Agent Control runtime evaluation: failed "
                        f"({safe_error})"
                    )
                    ready = False
                else:
                    if runtime_result.get("is_safe") is True:
                        print("  Agent Control runtime evaluation: ✓")
                    else:
                        print(
                            "  Agent Control runtime evaluation: connectivity probe "
                            "was unexpectedly blocked"
                        )
                        ready = False
    if settings.env_file.exists():
        print(f"  environment file: {settings.env_file} ✓")
    else:
        print(
            f"  environment file: {settings.env_file} not found "
            "(configuration came from process environment)"
        )
    print("  organization trace scan: not performed")
    print(f"\nDeployment readiness: {'READY' if ready else 'ACTION REQUIRED'}")
    return 0 if ready else 1


def run_setup(
    settings: Settings,
    service: GalileoService,
    args: argparse.Namespace,
) -> int:
    approval = ApprovalGate(dry_run=args.dry_run, assume_yes=args.yes)
    scope = select_scope(
        settings,
        service,
        project_arg=args.project,
        stream_arg=args.log_stream,
        select_interactively=args.select_scope,
        allow_recovery=_allow_scope_recovery(args),
    )
    scope = ensure_telemetry_stream(scope, service, approval)
    print_scope(scope, settings)
    if not args.with_agent_control:
        print(
            "\nTelemetry setup complete. To register the agent and install the "
            "recommended Agent Control starter policy, run:\n"
            "  python3 -m evalops_agent setup --with-agent-control"
        )
        return 0

    installer = StarterPolicyInstaller(settings, scope, approval)
    plan = installer.prepare()
    with InstrumentedSession(
        settings,
        scope,
        "Galileo EvalOps Agent installation",
    ):
        result = installer.install(plan)

    print("\nAgent Control installation complete")
    print("-----------------------------------")
    print(f"Agent:              {result['agent_name']}")
    print(f"Policy:             {result['policy_name']} (ID {result['policy_id']})")
    print(f"Policy created:     {'yes' if result['policy_created'] else 'no, reused'}")
    print(f"Controls created:   {len(result['created_controls'])}")
    print(f"Controls reused:    {len(result['reused_controls'])}")
    print(
        f"Target attachments: {result['target_attachment_count']} verified on "
        f"{result['target_name']}"
    )
    print(f"Effective controls: {result['effective_control_count']} verified")
    print("LLM/evaluator calls: 0")
    return 0


def _run_agent_request(
    agent: EvalOpsAgent,
    telemetry: InstrumentedSession,
    scope: Scope,
    request: str,
) -> None:
    telemetry.ensure_started()
    print(agent.run_with_steering(request))
    try:
        uploaded = telemetry.flush_turn()
    except TelemetryUploadError as exc:
        print(f"Telemetry error: {exc}", file=sys.stderr)
    else:
        print(
            f"[Galileo telemetry: uploaded {uploaded} trace(s) to "
            f"{scope.telemetry_stream_name}]"
        )


def _run_presentation_steps(
    option: DemoOption,
    agent: EvalOpsAgent,
    telemetry: InstrumentedSession,
    scope: Scope,
    *,
    run_without_pauses: bool,
) -> None:
    print(f"\nPresentation mode: {option.title}")
    print("The agent will run a predefined workflow one step at a time.")
    for index, step in enumerate(option.steps, start=1):
        print(f"\nStep {index}/{len(option.steps)} — {step.title}")
        print(f"Capability: {step.capability}")
        print(f"Presenter note: {step.presenter_note}")
        print(f"\nPrompt:\n{step.prompt}")
        if not run_without_pauses:
            action = input("\nPress Enter to run, 's' to skip, or 'q' to stop: ").strip().lower()
            if action in {"q", "quit", "exit"}:
                break
            if action in {"s", "skip"}:
                continue
        print("\nAgent response")
        print("--------------")
        _run_agent_request(agent, telemetry, scope, step.prompt)
    print(
        "\nPresentation complete. Open the newest session in the "
        f"{scope.telemetry_stream_name!r} Log Stream to show the agent, LLM, "
        "and tool spans, then show the corresponding Agent Control decisions."
    )


def _is_menu_selection(user_input: str, *, menu_open: bool) -> bool:
    if not menu_open:
        return False
    return bool(
        user_input.isdigit()
        or find_use_case(user_input) is not None
        or find_workflow_group(user_input) is not None
    )


def run_chat(
    settings: Settings,
    service: GalileoService,
    args: argparse.Namespace,
    *,
    presentation: DemoOption | None = None,
) -> int:
    approval = ApprovalGate(dry_run=args.dry_run, assume_yes=args.yes)
    scope = select_scope(
        settings,
        service,
        project_arg=args.project,
        stream_arg=args.log_stream,
        select_interactively=args.select_scope,
        allow_recovery=_allow_scope_recovery(args),
    )
    scope = ensure_telemetry_stream(scope, service, approval)
    print_scope(scope, settings)
    tools = ToolRegistry(settings, scope, service, approval)
    session_name = (
        f"EvalOps Demo: {presentation.title}"
        if presentation is not None
        else "Galileo EvalOps CLI"
    )
    with InstrumentedSession(settings, scope, session_name) as telemetry:
        agent = EvalOpsAgent(settings, scope, tools)
        if presentation is not None:
            _run_presentation_steps(
                presentation,
                agent,
                telemetry,
                scope,
                run_without_pauses=args.yes,
            )
            return 0

        print_app_intro(scope)
        print_use_case_menu()
        print(
            "\nChoose a topic, type your own request, or enter "
            "'menu', 'examples', or 'quit'."
        )
        menu_open = True
        while True:
            try:
                user_input = input("\nevalops> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_input:
                continue
            if user_input.lower() in {"quit", "exit", "q"}:
                break
            if user_input.lower() in {"usecases", "workflows", "menu"}:
                print_use_case_menu()
                menu_open = True
                continue
            if user_input.lower() == "examples":
                print_starter_requests()
                continue
            use_case = None
            if menu_open:
                if user_input == "0":
                    print("Type your own EvalOps question at the prompt.")
                    menu_open = False
                    continue
                if _is_menu_selection(user_input, menu_open=menu_open):
                    use_case = select_use_case_from_menu(user_input)
                    if use_case is None:
                        print_use_case_menu()
                        continue
                else:
                    menu_open = False
            elif not user_input.isdigit():
                use_case = find_use_case(user_input)
                group = find_workflow_group(user_input)
                if use_case is None and group is not None:
                    use_case = select_use_case_from_menu(user_input)
                    if use_case is None:
                        print_use_case_menu()
                        menu_open = True
                        continue
            if use_case is not None:
                print(f"\nStarting workflow: {use_case.title}")
                user_input = use_case.opening_request
                menu_open = False
            elif menu_open:
                continue
            else:
                # Once a workflow or free-form conversation starts, numbers are
                # answers to the agent (thresholds, hours, limits), not menu choices.
                menu_open = False
            _run_agent_request(agent, telemetry, scope, user_input)
    return 0


def _copy_args(args: argparse.Namespace, **overrides: Any) -> argparse.Namespace:
    values = vars(args).copy()
    values.update(overrides)
    return argparse.Namespace(**values)


def run_demo_presentation(
    settings: Settings,
    service: GalileoService,
    args: argparse.Namespace,
) -> int:
    if args.list:
        print_demo_menu()
        return 0

    if args.scenario:
        option = DEMO_OPTIONS_BY_KEY[args.scenario]
    else:
        option = choose_demo_option()
        if option is None:
            return 0

    print_demo_card(option)
    if args.print_only:
        return 0
    if not args.yes and not _confirm("\nLaunch this guided presentation?"):
        return 0

    launch_args = _copy_args(args)
    if option.requires_demo_data:
        project = _select_project(
            settings,
            service,
            project_arg=args.project,
            select_interactively=args.select_scope,
            allow_recovery=_allow_scope_recovery(args),
        )
        demo_stream = service.get_log_stream(project.id, settings.demo_stream)
        if demo_stream is None:
            print(
                f"\nThe deterministic Log Stream {settings.demo_stream!r} does not exist."
            )
            if not args.yes and not _confirm(
                f"Seed {len(DEMO_CASES)} zero-evaluator-cost demo traces now?"
            ):
                print(
                    "\nSeed it later with:\n"
                    f"  evalops --project {project.name} demo-seed"
                )
                return 0
            seed_args = _copy_args(args, project=project.name)
            run_demo_seed(settings, service, seed_args)
        launch_args = _copy_args(
            args,
            project=project.name,
            log_stream=settings.demo_stream,
        )

    return run_chat(
        settings,
        service,
        launch_args,
        presentation=option,
    )


def run_offline_demo_preview(args: argparse.Namespace) -> int:
    """List or print presentation material without loading credentials."""
    if args.list:
        print_demo_menu()
        return 0
    option = (
        DEMO_OPTIONS_BY_KEY[args.scenario]
        if args.scenario
        else choose_demo_option()
    )
    if option is not None:
        print_demo_card(option)
    return 0


def run_demo_seed(settings: Settings, service: GalileoService, args: argparse.Namespace) -> int:
    approval = ApprovalGate(dry_run=args.dry_run, assume_yes=args.yes)
    project = _select_project(
        settings,
        service,
        project_arg=args.project,
        select_interactively=args.select_scope,
        allow_recovery=_allow_scope_recovery(args),
    )
    stream = service.get_log_stream(project.id, settings.demo_stream)
    approval.require(
        OperationPreview(
            operation="Create deterministic EvalOps demo traffic",
            project=project.name,
            resource=settings.demo_stream,
            records=len(DEMO_CASES),
            estimated_generation_calls=0,
            estimated_evaluator_calls=0,
            details={
                "Create Log Stream": "yes" if stream is None else "no",
                "Metric": "demo_quality (local deterministic scorer)",
            },
        )
    )
    if stream is None:
        stream = service.create_log_stream(project.name, settings.demo_stream)
    result = seed_demo(project.name, stream.name)
    print("\nDemo traffic created")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print(
        "\nStart the guided agent with:\n"
        f"  python3 -m evalops_agent "
        f"--project {project.name} --log-stream {stream.name} chat"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cost-bounded Galileo EvalOps Agent")
    parser.add_argument("--env-file", help="Override the environment file.")
    parser.add_argument("--project", help="Exact project name. No organization trace scan is used.")
    parser.add_argument("--log-stream", help="Exact source Log Stream name.")
    parser.add_argument(
        "--select-scope",
        action="store_true",
        help=(
            "Interactively select a project and source Log Stream instead of "
            "using configured defaults."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview but never execute writes.")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Approve write previews and run guided demos without pauses.",
    )
    subparsers = parser.add_subparsers(dest="command")
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run read-only configuration and connectivity checks.",
    )
    setup_parser = subparsers.add_parser(
        "setup",
        help="Create telemetry and optionally install the Agent Control starter policy.",
    )
    setup_parser.add_argument(
        "--with-agent-control",
        action="store_true",
        help=(
            "Register the agent and install the versioned Agent Control starter "
            "policy after a write preview."
        ),
    )
    chat_parser = subparsers.add_parser(
        "chat",
        help="Start the conversational EvalOps operator.",
    )
    demo_parser = subparsers.add_parser(
        "demo",
        help="Choose and run a presenter-ready guided demo.",
    )
    demo_parser.add_argument(
        "--list",
        action="store_true",
        help="List presentation scenarios without launching one.",
    )
    demo_parser.add_argument(
        "--scenario",
        choices=[option.key for option in DEMO_OPTIONS],
        help="Launch an exact presentation scenario without the menu.",
    )
    demo_parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the selected presentation card and prompts without running them.",
    )
    demo_seed_parser = subparsers.add_parser(
        "demo-seed",
        help="Create 12 deterministic demo traces after a write preview.",
    )
    for command_parser in (
        doctor_parser,
        setup_parser,
        chat_parser,
        demo_parser,
        demo_seed_parser,
    ):
        command_parser.add_argument(
            "--select-scope",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Interactively select scope instead of using configured defaults.",
        )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "chat"
    settings: Settings | None = None
    try:
        if command == "demo" and (args.list or args.print_only):
            raise SystemExit(run_offline_demo_preview(args))
        settings = Settings.load(args.env_file)
        service = GalileoService(settings)
        if command == "doctor":
            code = run_doctor(settings, service, args)
        elif command == "setup":
            code = run_setup(settings, service, args)
        elif command == "demo":
            code = run_demo_presentation(settings, service, args)
        elif command == "demo-seed":
            code = run_demo_seed(settings, service, args)
        else:
            code = run_chat(settings, service, args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        code = 130
    except (
        ConfigurationError,
        LookupError,
        ModelConnectionError,
        PermissionError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        code = 2
    except Exception as exc:
        secrets = settings.secret_values() if settings is not None else ()
        safe_error = sanitize(str(exc), secrets, 1000)
        print(
            f"Runtime error: {safe_error}\n"
            "Run `python3 -m evalops_agent doctor` to verify deployment connectivity.",
            file=sys.stderr,
        )
        code = 1
    raise SystemExit(code)
