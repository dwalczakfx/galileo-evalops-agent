from __future__ import annotations

import unittest

from evalops_agent.demo import DEMO_CASES, _demo_quality


class FakeTrace:
    def __init__(self, expected_outcome: str) -> None:
        self.metadata = {"expected_outcome": expected_outcome}


class DemoTests(unittest.TestCase):
    def test_demo_is_small_and_balanced(self) -> None:
        self.assertEqual(len(DEMO_CASES), 12)
        outcomes = {case.expected_outcome for case in DEMO_CASES}
        self.assertEqual(outcomes, {"success", "failure"})

    def test_demo_metric_is_deterministic(self) -> None:
        self.assertEqual(_demo_quality(FakeTrace("success"))[0], 1.0)
        self.assertEqual(_demo_quality(FakeTrace("failure"))[0], 0.2)


if __name__ == "__main__":
    unittest.main()
