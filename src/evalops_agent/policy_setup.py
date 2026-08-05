from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .agent_control_api import AgentControlService
from .approvals import ApprovalGate
from .config import Settings
from .models import OperationPreview, Scope


STARTER_POLICY_VERSION = "v1"
STARTER_TAGS = ["evalops-starter", f"evalops-starter-{STARTER_POLICY_VERSION}"]


@dataclass(frozen=True)
class StarterControl:
    name: str
    description: str
    definition: dict[str, Any]


def _control_definition(
    *,
    description: str,
    selector_path: str,
    regex_pattern: str,
    decision: str,
    stage: str,
    step_names: list[str],
) -> dict[str, Any]:
    return {
        "description": description,
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["llm"],
            "step_names": step_names,
            "stages": [stage],
        },
        "condition": {
            "selector": {"path": selector_path},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": regex_pattern},
            },
        },
        "action": {"decision": decision},
        "tags": STARTER_TAGS,
    }


STARTER_CONTROLS = (
    StarterControl(
        name="evalops-v1-deny-sensitive-requests",
        description="Deny explicit requests to reveal credentials or system prompts.",
        definition=_control_definition(
            description="Deny explicit requests to reveal credentials or system prompts.",
            selector_path="input",
            regex_pattern=(
                r"(?i)\b(?:show|reveal|expose|print|return|give|leak|display)\b"
                r"[^\n]{0,80}\b(?:api[ _-]?key|access[ _-]?token|password|"
                r"credential|secret|system[ _-]?prompt)\b"
            ),
            decision="deny",
            stage="pre",
            step_names=["evalops_user_request"],
        ),
    ),
    StarterControl(
        name="evalops-v1-deny-sensitive-responses",
        description="Deny agent responses that resemble credential disclosure.",
        definition=_control_definition(
            description="Deny agent responses that resemble credential disclosure.",
            selector_path="output",
            regex_pattern=(
                r"(?i)(?:\b(?:api[ _-]?key|access[ _-]?token|password|credential|"
                r"secret)\b[^\n]{0,24}(?:is|=|:)\s*[A-Za-z0-9_./+=-]{12,}|"
                r"\bsk-[A-Za-z0-9_-]{16,})"
            ),
            decision="deny",
            stage="post",
            step_names=["evalops_agent_response"],
        ),
    ),
    StarterControl(
        name="evalops-v1-deny-destructive-requests",
        description="Deny destructive requests targeting Galileo resources.",
        definition=_control_definition(
            description="Deny destructive requests targeting Galileo resources.",
            selector_path="input",
            regex_pattern=(
                r"(?i)\b(?:delete|drop|purge|erase|destroy)\b[^\n]{0,80}\b"
                r"(?:project|log[ _-]?stream|dataset|prompt|experiment|trace|session|"
                r"control|policy)\b"
            ),
            decision="deny",
            stage="pre",
            step_names=["evalops_user_request"],
        ),
    ),
    StarterControl(
        name="evalops-v1-observe-trace-prompt-injection",
        description="Observe prompt-injection language in inspected production traces.",
        definition=_control_definition(
            description="Observe prompt-injection language in inspected production traces.",
            selector_path="output",
            regex_pattern=(
                r"(?i)\b(?:ignore|disregard|override)\b[^\n]{0,80}\b"
                r"(?:previous|prior|system|developer)\b[^\n]{0,40}\b"
                r"(?:instruction|prompt|message)s?\b"
            ),
            decision="observe",
            stage="post",
            step_names=["inspect_production_trace"],
        ),
    ),
)


CONTROL_STEP_NAMES = (
    "evalops_user_request",
    "evalops_agent_response",
    "inspect_production_trace",
    "analyze_regression_coverage",
    "write_regression_dataset",
    "write_prompt_version",
    "run_bounded_experiment",
    "bootstrap_galileo_environment",
    "write_agent_control_policy",
)

CONTROL_STEPS = [
    {"type": "llm", "name": name}
    for name in CONTROL_STEP_NAMES
]


@dataclass(frozen=True)
class StarterPolicyPlan:
    existing_control_ids: dict[str, int]
    missing_controls: tuple[StarterControl, ...]


def starter_policy_name(agent_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", agent_name.lower()).strip("-")
    normalized = normalized or "evalops-agent"
    suffix = f"-starter-safety-{STARTER_POLICY_VERSION}"
    if len(normalized) + len(suffix) <= 80:
        return normalized + suffix
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return normalized[: 80 - len(suffix) - len(digest) - 1] + f"-{digest}" + suffix


def _contains_expected(expected: Any, actual: Any) -> bool:
    """Return whether server data contains the versioned definition we own."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains_expected(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and expected == actual
    return expected == actual


def _extract_id(value: dict[str, Any], *keys: str) -> int:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    raise RuntimeError(f"Agent Control response did not include {', '.join(keys)}.")


def _int_set(value: dict[str, Any], key: str) -> set[int]:
    items = value.get(key, [])
    if not isinstance(items, list):
        return set()
    return {
        int(item)
        for item in items
        if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
    }


class StarterPolicyInstaller:
    def __init__(
        self,
        settings: Settings,
        scope: Scope,
        approval: ApprovalGate,
        service: AgentControlService | None = None,
    ) -> None:
        if not scope.telemetry_stream_id:
            raise ValueError("The EvalOps telemetry Log Stream has not been created.")
        self.settings = settings
        self.scope = scope
        self.approval = approval
        self.service = service or AgentControlService(settings)

    def prepare(self) -> StarterPolicyPlan:
        existing: dict[str, int] = {}
        missing: list[StarterControl] = []

        for spec in STARTER_CONTROLS:
            validation = self.service.validate_control(spec.definition)
            if validation.get("success") is not True and validation.get("valid") is not True:
                raise ValueError(
                    f"Agent Control rejected starter control {spec.name!r}: {validation}"
                )

            result = self.service.list_controls_by_name(spec.name, limit=20)
            controls = result.get("controls", []) if isinstance(result, dict) else []
            exact = [
                item
                for item in controls
                if isinstance(item, dict) and item.get("name") == spec.name
            ]
            if len(exact) > 1:
                raise RuntimeError(
                    f"Agent Control returned duplicate controls named {spec.name!r}."
                )
            if not exact:
                missing.append(spec)
                continue

            control_id = _extract_id(exact[0], "id", "control_id")
            detail = self.service.get_control(control_id)
            if detail.get("name") != spec.name or not _contains_expected(
                spec.definition,
                detail.get("data"),
            ):
                raise PermissionError(
                    f"Existing control {spec.name!r} does not match the versioned "
                    "EvalOps starter definition. Refusing to overwrite or attach it."
                )
            existing[spec.name] = control_id

        policy_name = starter_policy_name(self.settings.agent_name)
        self.approval.require(
            OperationPreview(
                operation="Install Agent Control starter policy",
                project=self.scope.project_name,
                resource=policy_name,
                records=len(missing) + len(STARTER_CONTROLS),
                details={
                    "Agent": self.settings.agent_name,
                    "Telemetry Log Stream": self.scope.telemetry_stream_name,
                    "Controls": ", ".join(spec.name for spec in STARTER_CONTROLS),
                    "Controls to create": len(missing),
                    "Existing controls to reuse": len(existing),
                    "Decisions": "3 DENY, 1 OBSERVE",
                    "LLM or evaluator calls": 0,
                    "Direct target bindings": len(STARTER_CONTROLS),
                    "Rerun behavior": (
                        "reuse matching controls, policy associations, and target bindings"
                    ),
                },
            )
        )
        return StarterPolicyPlan(
            existing_control_ids=existing,
            missing_controls=tuple(missing),
        )

    def install(self, plan: StarterPolicyPlan) -> dict[str, Any]:
        control_ids = dict(plan.existing_control_ids)
        created_controls: list[str] = []
        for spec in plan.missing_controls:
            result = self.service.create_control(
                name=spec.name,
                definition=spec.definition,
            )
            control_ids[spec.name] = _extract_id(result, "control_id", "id")
            created_controls.append(spec.name)

        desired_ids = set(control_ids.values())
        associated = self.service.get_agent_policy_ids(self.settings.agent_name)
        policy_ids = sorted(_int_set(associated, "policy_ids"))
        complete_policy_id: int | None = None
        partial_candidates: list[int] = []
        for policy_id in policy_ids:
            current_ids = _int_set(
                self.service.get_policy_control_ids(policy_id),
                "control_ids",
            )
            if desired_ids.issubset(current_ids):
                complete_policy_id = policy_id
                break
            if current_ids and current_ids.issubset(desired_ids):
                partial_candidates.append(policy_id)

        created_policy = False
        if complete_policy_id is not None:
            policy_id = complete_policy_id
        elif len(partial_candidates) == 1:
            policy_id = partial_candidates[0]
        elif len(partial_candidates) > 1:
            raise PermissionError(
                "More than one attached policy partially contains the EvalOps starter "
                "controls. Review the policies in Galileo before retrying."
            )
        else:
            created = self.service.create_policy(
                starter_policy_name(self.settings.agent_name)
            )
            policy_id = _extract_id(created, "policy_id", "id")
            created_policy = True

        for control_id in sorted(desired_ids):
            self.service.add_control_to_policy(
                policy_id=policy_id,
                control_id=control_id,
            )
        self.service.add_policy_to_agent(
            agent_name=self.settings.agent_name,
            policy_id=policy_id,
        )
        target_type = "log_stream"
        target_id = str(self.scope.telemetry_stream_id)
        for control_id in sorted(desired_ids):
            self.service.bind_control_to_target(
                control_id=control_id,
                target_type=target_type,
                target_id=target_id,
            )
        self.service.refresh_runtime_controls()

        attached = self.service.list_controls_for_target(
            target_type=target_type,
            target_id=target_id,
            limit=100,
        )
        attached_controls = (
            attached.get("controls", []) if isinstance(attached, dict) else []
        )
        attached_ids = {
            _extract_id(item, "id", "control_id")
            for item in attached_controls
            if isinstance(item, dict)
        }
        attached_names = {
            str(item.get("name"))
            for item in attached_controls
            if isinstance(item, dict) and item.get("name")
        }
        expected_names = {spec.name for spec in STARTER_CONTROLS}
        if not desired_ids.issubset(attached_ids) and not expected_names.issubset(
            attached_names
        ):
            raise RuntimeError(
                "The starter controls were written, but direct attachment to the "
                f"telemetry Log Stream {self.scope.telemetry_stream_name!r} could "
                "not be verified."
            )

        effective = self.service.list_effective_controls(
            agent_name=self.settings.agent_name,
            target_type=target_type,
            target_id=target_id,
        )
        effective_controls = (
            effective.get("controls", []) if isinstance(effective, dict) else []
        )
        effective_ids = {
            _extract_id(item, "id", "control_id")
            for item in effective_controls
            if isinstance(item, dict)
        }
        effective_names = {
            str(item.get("name"))
            for item in effective_controls
            if isinstance(item, dict) and item.get("name")
        }
        if not desired_ids.issubset(effective_ids) and not expected_names.issubset(
            effective_names
        ):
            raise RuntimeError(
                "The starter policy was written, but its controls are not yet visible "
                "in the agent's effective control set. Review Agent Control in Galileo."
            )

        return {
            "agent_name": self.settings.agent_name,
            "policy_name": starter_policy_name(self.settings.agent_name),
            "policy_id": policy_id,
            "policy_created": created_policy,
            "created_controls": created_controls,
            "reused_controls": sorted(set(control_ids) - set(created_controls)),
            "target_type": target_type,
            "target_id": target_id,
            "target_name": self.scope.telemetry_stream_name,
            "target_attachment_count": len(expected_names),
            "effective_control_count": len(expected_names),
            "verified": True,
        }
