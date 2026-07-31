from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, TypeVar

import agent_control

from .config import Settings
from .security import sanitize


T = TypeVar("T")


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an Agent Control async API safely from sync code, including nested SDK loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="evalops-control-api") as pool:
        return pool.submit(asyncio.run, coro).result()


class AgentControlService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _kwargs(self) -> dict[str, str]:
        if not self.settings.agent_control_url:
            raise RuntimeError("AGENT_CONTROL_URL is not configured.")
        return {
            "server_url": self.settings.agent_control_url,
            "api_key": self.settings.galileo_api_key,
            "api_key_header": self.settings.agent_control_api_key_header,
        }

    def list_agents(self, limit: int = 20) -> dict[str, Any]:
        result = _run_async(
            agent_control.list_agents(
                limit=min(limit, 20),
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def get_agent(self, agent_name: str) -> dict[str, Any]:
        result = _run_async(
            agent_control.get_agent(
                agent_name=agent_name,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def list_controls_for_target(
        self,
        *,
        target_type: str,
        target_id: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        result = _run_async(
            agent_control.list_controls(
                limit=min(limit, 20),
                include_attachments=True,
                attachment_target_type=target_type,
                attachment_target_id=target_id,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def list_controls_by_name(self, name: str, limit: int = 20) -> dict[str, Any]:
        result = _run_async(
            agent_control.list_controls(
                name=name,
                limit=min(limit, 20),
                include_attachments=True,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def get_control(self, control_id: int) -> dict[str, Any]:
        result = _run_async(
            agent_control.get_control(control_id=control_id, **self._kwargs())
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def validate_control(self, definition: dict[str, Any]) -> dict[str, Any]:
        result = _run_async(
            agent_control.validate_control_data(
                definition,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def create_control(self, *, name: str, definition: dict[str, Any]) -> dict[str, Any]:
        result = _run_async(
            agent_control.create_control(
                name=name,
                data=definition,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def get_agent_policy_ids(self, agent_name: str) -> dict[str, Any]:
        result = _run_async(
            agent_control.get_agent_policies(
                agent_name=agent_name,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def get_policy_control_ids(self, policy_id: int) -> dict[str, Any]:
        result = _run_async(
            agent_control.list_policy_controls(
                policy_id=policy_id,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def create_policy(self, name: str) -> dict[str, Any]:
        async def create() -> dict[str, Any]:
            async with agent_control.AgentControlClient(
                base_url=self.settings.agent_control_url,
                api_key=self.settings.galileo_api_key,
                api_key_header=self.settings.agent_control_api_key_header,
                runtime_auth_mode=self.settings.agent_control_runtime_auth_mode,
            ) as client:
                return await agent_control.policies.create_policy(client, name)

        result = _run_async(create())
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def add_control_to_policy(self, *, policy_id: int, control_id: int) -> dict[str, Any]:
        result = _run_async(
            agent_control.add_control_to_policy(
                policy_id=policy_id,
                control_id=control_id,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def add_policy_to_agent(self, *, agent_name: str, policy_id: int) -> dict[str, Any]:
        result = _run_async(
            agent_control.add_agent_policy(
                agent_name=agent_name,
                policy_id=policy_id,
                **self._kwargs(),
            )
        )
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def list_effective_controls(
        self,
        *,
        agent_name: str,
        target_type: str,
        target_id: str,
    ) -> dict[str, Any]:
        async def list_effective() -> dict[str, Any]:
            async with agent_control.AgentControlClient(
                base_url=self.settings.agent_control_url,
                api_key=self.settings.galileo_api_key,
                api_key_header=self.settings.agent_control_api_key_header,
                runtime_auth_mode=self.settings.agent_control_runtime_auth_mode,
            ) as client:
                return await agent_control.agents.list_agent_controls(
                    client,
                    agent_name,
                    rendered_state="rendered",
                    enabled_state="enabled",
                    target_type=target_type,
                    target_id=target_id,
                )

        result = _run_async(list_effective())
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def probe_runtime_evaluation(
        self,
        *,
        agent_name: str,
        target_type: str,
        target_id: str,
    ) -> dict[str, Any]:
        """Verify the target-bound runtime evaluation path used by decorators."""

        async def probe() -> dict[str, Any]:
            async with agent_control.AgentControlClient(
                base_url=self.settings.agent_control_url,
                api_key=self.settings.galileo_api_key,
                api_key_header=self.settings.agent_control_api_key_header,
                runtime_auth_mode=self.settings.agent_control_runtime_auth_mode,
            ) as client:
                response = await client.post_runtime_evaluation(
                    json={
                        "agent_name": agent_name,
                        "step": {
                            "type": "llm",
                            "name": "evalops_user_request",
                            "input": "EvalOps runtime connectivity check",
                            "output": "",
                        },
                        "stage": "pre",
                        "target_type": target_type,
                        "target_id": target_id,
                    },
                    target_type=target_type,
                    target_id=target_id,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("is_safe"), bool
                ):
                    raise RuntimeError(
                        "Agent Control runtime evaluation returned an invalid response."
                    )
                return payload

        result = _run_async(probe())
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def refresh_runtime_controls(self) -> list[dict[str, Any]]:
        result = agent_control.refresh_controls() or []
        return sanitize(
            result,
            self.settings.secret_values(),
            self.settings.max_output_chars,
        )

    def create_and_attach_control(
        self,
        *,
        name: str,
        definition: dict[str, Any],
        agent_name: str,
    ) -> dict[str, Any]:
        created = _run_async(
            agent_control.create_control(
                name=name,
                data=definition,
                **self._kwargs(),
            )
        )
        control_id = int(created["control_id"])
        try:
            attachment = _run_async(
                agent_control.add_agent_control(
                    agent_name=agent_name,
                    control_id=control_id,
                    **self._kwargs(),
                )
            )
        except Exception as exc:
            return {
                "control": sanitize(
                    created,
                    self.settings.secret_values(),
                    self.settings.max_output_chars,
                ),
                "attached": False,
                "agent_name": agent_name,
                "attachment_error": sanitize(
                    str(exc),
                    self.settings.secret_values(),
                    1000,
                ),
                "warning": (
                    "The control was created, but attaching it to the agent failed. "
                    "Review the created control in Agent Control."
                ),
            }
        return {
            "control": sanitize(
                created,
                self.settings.secret_values(),
                self.settings.max_output_chars,
            ),
            "attached": True,
            "agent_name": agent_name,
            "attachment": sanitize(
                attachment,
                self.settings.secret_values(),
                self.settings.max_output_chars,
            ),
        }
