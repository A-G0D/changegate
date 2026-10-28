"""Pattern tests. Fake credentials are built at runtime so this file never contains one."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from changegate.patterns import ALL_RULES, PII_RULES, SECRET_RULES, is_placeholder, redact


def rule(rule_id: str, rules=SECRET_RULES):
    return next(r for r in rules if r.rule_id == rule_id)


class TestSecretRules(unittest.TestCase):
    def assert_matches(self, rule_id: str, value: str):
        match = rule(rule_id).pattern.search(value)
        self.assertIsNotNone(match, f"{rule_id} did not match synthetic sample")
        self.assertEqual(match.group(0), value)

    def test_aws_access_key(self):
        self.assert_matches("aws-access-key-id", "AKIA" + "".join("ABCDEFGH"[:8] for _ in range(2)))

    def test_github_token(self):
        self.assert_matches("github-token", "ghp" + "_" + "a" * 36)

    def test_fine_grained_github_token(self):
        self.assert_matches("github-fine-grained-token", "github_pat_" + "B" * 60)

    def test_openai_style_key(self):
        self.assert_matches("openai-key", "sk-" + "a" * 24)

    def test_anthropic_key(self):
        self.assert_matches("anthropic-key", "sk-ant-" + "a" * 24)

    def test_stripe_live_key(self):
        self.assert_matches("stripe-live-key", "sk_live_" + "a" * 20)

    def test_slack_token(self):
        self.assert_matches("slack-token", "xoxb-" + "1" * 12)

    def test_google_api_key(self):
        self.assert_matches("google-api-key", "AIza" + "a" * 35)

    def test_private_key_block(self):
        self.assert_matches("private-key-block", "-----BEGIN RSA PRIVATE KEY-----")

    def test_jwt(self):
        token = "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12
        self.assert_matches("jwt", token)

    def test_generic_credential_assignment(self):
        value = 'API_KEY = "' + "a" * 24 + '"'
        self.assertIsNotNone(rule("generic-credential").pattern.search(value))

    def test_placeholder_heuristics(self):
        self.assertTrue(is_placeholder('API_KEY = "your_api_key_here_1234"'))
        self.assertTrue(is_placeholder('token = os.environ["TOKEN"]'))
        self.assertFalse(is_placeholder('API_KEY = "' + "a" * 30 + '"'))

    def test_redact_never_returns_full_value(self):
        value = "ghp_" + "a" * 36
        masked = redact(value)
        self.assertNotIn(value, masked)
        self.assertTrue(masked.endswith("*") or "…" in masked)


class TestPiiRules(unittest.TestCase):
    def test_email(self):
        email = "alice" + "@" + "realcorp" + "." + "com"
        self.assertIsNotNone(rule("email-address", PII_RULES).pattern.search(email))

    def test_home_path(self):
        path = "/Users/" + "alice" + "/project"
        self.assertIsNotNone(rule("posix-home-path", PII_RULES).pattern.search(path))

    def test_windows_home_path(self):
        path = "C:" + "\\" + "Users" + "\\" + "alice" + "\\" + "x"
        self.assertIsNotNone(rule("windows-home-path", PII_RULES).pattern.search(path))

    def test_all_rule_groups_present(self):
        self.assertEqual(set(ALL_RULES), {"secrets", "pii", "dangerous"})


if __name__ == "__main__":
    unittest.main()
