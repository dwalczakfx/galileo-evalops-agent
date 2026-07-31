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
