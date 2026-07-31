from __future__ import annotations

import unittest

from evalops_agent.security import redact_text, sanitize


class SecurityTests(unittest.TestCase):
    def test_redacts_known_secret(self) -> None:
        self.assertNotIn("secret-123", redact_text("value secret-123", ["secret-123"]))

    def test_redacts_assignment_and_bearer_token(self) -> None:
        text = redact_text("api_key=abc Authorization: Bearer xyz.123")
        self.assertNotIn("abc", text)
        self.assertNotIn("xyz.123", text)

    def test_redacts_masked_key_from_provider_error(self) -> None:
        text = redact_text("Incorrect API key provided: PLACEHOL**********_KEY")
        self.assertNotIn("PLACEHOL", text)
        self.assertIn("[REDACTED]", text)

    def test_redacts_sensitive_dictionary_keys(self) -> None:
        cleaned = sanitize({"token": "abc", "safe": "value"})
        self.assertEqual(cleaned["token"], "[REDACTED]")
        self.assertEqual(cleaned["safe"], "value")

    def test_preserves_non_secret_token_metrics(self) -> None:
        cleaned = sanitize(
            {
                "num_input_tokens": 42,
                "num_output_tokens": 9,
                "access_token": "secret",
            }
        )
        self.assertEqual(cleaned["num_input_tokens"], 42)
        self.assertEqual(cleaned["num_output_tokens"], 9)
        self.assertEqual(cleaned["access_token"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
