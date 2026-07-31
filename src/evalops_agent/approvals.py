from __future__ import annotations

from collections.abc import Callable

from .models import OperationPreview


class ApprovalDenied(PermissionError):
    """Raised when a write operation is not approved."""


class ApprovalGate:
    def __init__(
        self,
        *,
        dry_run: bool = False,
        assume_yes: bool = False,
        prompt: Callable[[str], str] = input,
    ) -> None:
        self.dry_run = dry_run
        self.assume_yes = assume_yes
        self.prompt = prompt

    def require(self, preview: OperationPreview) -> None:
        print("\nWrite preview")
        print("-------------")
        for line in preview.lines():
            print(line)
        if self.dry_run:
            raise ApprovalDenied("Dry-run mode: write operation was not executed.")
        if self.assume_yes:
            return
        answer = self.prompt("Approve this write? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            raise ApprovalDenied("Write operation was not approved.")
