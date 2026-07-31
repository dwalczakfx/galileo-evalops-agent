from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO

from evalops_agent.approvals import ApprovalDenied, ApprovalGate
from evalops_agent.models import OperationPreview


PREVIEW = OperationPreview(
    operation="test write",
    project="project-a",
    resource="dataset-a",
    records=3,
)


class ApprovalTests(unittest.TestCase):
    def test_default_denies(self) -> None:
        gate = ApprovalGate(prompt=lambda _: "")
        with redirect_stdout(StringIO()):
            with self.assertRaises(ApprovalDenied):
                gate.require(PREVIEW)

    def test_explicit_yes_approves(self) -> None:
        gate = ApprovalGate(prompt=lambda _: "yes")
        with redirect_stdout(StringIO()):
            gate.require(PREVIEW)

    def test_dry_run_never_writes_even_with_yes(self) -> None:
        gate = ApprovalGate(dry_run=True, assume_yes=True)
        with redirect_stdout(StringIO()):
            with self.assertRaises(ApprovalDenied):
                gate.require(PREVIEW)


if __name__ == "__main__":
    unittest.main()
