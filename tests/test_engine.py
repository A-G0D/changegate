"""Gate engine tests: every check, the config loader, and report rendering."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from changegate.diff import AddedLine, ChangedFile
from changegate.engine import (
    ConfigError,
    GateConfig,
    check_commands,
    evaluate,
    glob_any,
)
from changegate.report import dumps, render_markdown, render_text


def changed(path: str, lines: list[str], status: str = "modified", binary: bool = False):
    return ChangedFile(
        path=path,
        status=status,
        binary=binary,
        added=[AddedLine(text=line, line_no=i + 1) for i, line in enumerate(lines)],
    )


def rules_of(result) -> list[str]:
    return [f.rule for f in result.findings]


def fake_secret() -> str:
    """A credential-shaped value, built at runtime so the source contains no literal secret."""
    return 'API_KEY = "' + "a" * 30 + '"'


class TestScope(unittest.TestCase):
    def test_clean_change_passes(self):
        result = evaluate([changed("app.py", ["x = 1"])])
        self.assertTrue(result.passed)
        self.assertEqual(result.findings, [])

    def test_empty_diff_warns_but_passes(self):
        result = evaluate([])
        self.assertTrue(result.passed)
        self.assertIn("empty-diff", rules_of(result))

    def test_forbidden_path_blocks(self):
        result = evaluate([changed(".github/workflows/ci.yml", ["on: push"])])
        self.assertFalse(result.passed)
        self.assertIn("forbidden-path", rules_of(result))

    def test_lockfile_blocks(self):
        result = evaluate([changed("uv.lock", ["+new-package==1.0"])])
        self.assertFalse(result.passed)
        self.assertIn("forbidden-path", rules_of(result))

    def test_max_files(self):
        files = [changed(f"src/module_{i}.py", ["x = 1"]) for i in range(4)]
        result = evaluate(files, GateConfig(max_files=3))
        self.assertFalse(result.passed)
        self.assertIn("max-files", rules_of(result))

    def test_max_added_lines(self):
        result = evaluate([changed("app.py", ["x = 1"] * 10)], GateConfig(max_added_lines=5))
        self.assertFalse(result.passed)
        self.assertIn("max-added-lines", rules_of(result))

    def test_allowed_scope_blocks_outside_paths(self):
        cfg = GateConfig(allowed=("src/**",))
        result = evaluate([changed("app.py", ["x = 1"])], cfg)
        self.assertFalse(result.passed)
        self.assertIn("out-of-scope-path", rules_of(result))

    def test_deletion_warns(self):
        result = evaluate([changed("old.py", [], status="deleted")])
        self.assertTrue(result.passed)
        self.assertIn("file-deletion", rules_of(result))


class TestBinaryAndTamper(unittest.TestCase):
    def test_binary_blocks_by_default(self):
        result = evaluate([changed("logo.png", [], binary=True)])
        self.assertFalse(result.passed)
        self.assertIn("binary-file", rules_of(result))

    def test_binary_allowed_with_flag(self):
        result = evaluate([changed("logo.png", [], binary=True)], GateConfig(allow_binary=True))
        self.assertTrue(result.passed)

    def test_test_edit_blocks_by_default(self):
        result = evaluate([changed("tests/test_app.py", ["x = 1"])])
        self.assertFalse(result.passed)
        self.assertIn("test-tamper", rules_of(result))

    def test_test_edit_allowed_with_flag(self):
        result = evaluate([changed("tests/test_app.py", ["x = 1"])], GateConfig(allow_tests=True))
        self.assertTrue(result.passed)


class TestSecretsAndPii(unittest.TestCase):
    def test_secret_blocks(self):
        result = evaluate([changed("config.py", [fake_secret()])])
        self.assertFalse(result.passed)
        self.assertIn("generic-credential", rules_of(result))

    def test_secret_is_redacted_in_report(self):
        result = evaluate([changed("config.py", [fake_secret()])])
        out = render_text(result)
        self.assertNotIn("a" * 30, out)

    def test_placeholder_is_not_flagged(self):
        result = evaluate([changed("config.py", ['API_KEY = "your_api_key_here"'])])
        self.assertTrue(result.passed)

    def test_secret_in_deleted_file_content_is_not_scanned(self):
        result = evaluate([changed("config.py", [fake_secret()], status="deleted")])
        self.assertTrue(result.passed)

    def test_pii_email_blocks(self):
        email_line = "contact: alice" + "@" + "realcorp" + "." + "com"
        result = evaluate([changed("docs/team.md", [email_line])])
        self.assertFalse(result.passed)
        self.assertIn("email-address", rules_of(result))

    def test_example_email_is_allowed(self):
        example_line = "contact: team" + "@" + "example" + "." + "com"
        result = evaluate([changed("docs/team.md", [example_line])])
        self.assertTrue(result.passed)

    def test_home_path_blocks(self):
        home_line = "RUNNER = '/Users/" + "alice" + "/project'"
        result = evaluate([changed("ci.py", [home_line])])
        self.assertFalse(result.passed)
        self.assertIn("posix-home-path", rules_of(result))

    def test_ignore_globs_skip_content_scan(self):
        cfg = GateConfig(ignore=("docs/**",))
        result = evaluate([changed("docs/notes.md", [fake_secret()])], cfg)
        self.assertTrue(result.passed)


class TestDangerous(unittest.TestCase):
    def test_dangerous_call_is_warning_by_default(self):
        result = evaluate([changed("app.py", ["os.system('ls')"])])
        self.assertTrue(result.passed)
        self.assertIn("os-system", rules_of(result))

    def test_dangerous_can_block(self):
        result = evaluate([changed("app.py", ["os.system('ls')"])], GateConfig(dangerous="error"))
        self.assertFalse(result.passed)

    def test_dangerous_off(self):
        result = evaluate([changed("app.py", ["os.system('ls')"])], GateConfig(dangerous="off"))
        self.assertTrue(result.passed)
        self.assertNotIn("os-system", rules_of(result))


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cg-cmd-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_passing_command(self):
        findings, records = check_commands(
            self.tmp, GateConfig(test_cmd="python3 -c 'import sys; sys.exit(0)'")
        )
        self.assertEqual(findings, [])
        self.assertEqual(records[0]["exit"], 0)

    def test_failing_command(self):
        findings, records = check_commands(
            self.tmp, GateConfig(test_cmd="python3 -c 'import sys; sys.exit(3)'")
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "command-tests")
        self.assertEqual(records[0]["exit"], 3)

    def test_missing_command_is_reported(self):
        findings, _ = check_commands(self.tmp, GateConfig(test_cmd="definitely-not-a-real-binary"))
        self.assertEqual(findings[0].rule, "command-tests")

    def test_secrets_are_scrubbed_from_command_env(self):
        os.environ["CHANGEGATE_TEST_API_KEY"] = "should-not-leak"
        try:
            findings, _ = check_commands(
                self.tmp,
                GateConfig(
                    test_cmd="python3 -c 'import os,sys; sys.exit(0 if \"CHANGEGATE_TEST_API_KEY\" not in os.environ else 9)'"
                ),
            )
        finally:
            os.environ.pop("CHANGEGATE_TEST_API_KEY", None)
        self.assertEqual(findings, [])


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cg-cfg-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, data) -> str:
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def test_roundtrip(self):
        path = self.write_config({"max_files": 3, "forbidden": ["secrets/**"]})
        cfg = GateConfig.from_file(path)
        self.assertEqual(cfg.max_files, 3)
        self.assertEqual(cfg.forbidden, ("secrets/**",))

    def test_unknown_key_rejected(self):
        path = self.write_config({"max_file": 3})
        with self.assertRaises(ConfigError):
            GateConfig.from_file(path)

    def test_bad_type_rejected(self):
        path = self.write_config({"forbidden": "not-a-list"})
        with self.assertRaises(ConfigError):
            GateConfig.from_file(path)

    def test_invalid_dangerous_rejected(self):
        with self.assertRaises(ConfigError):
            GateConfig(dangerous="maybe")

    def test_merged_overrides_only_non_none(self):
        cfg = GateConfig(max_files=5)
        merged = cfg.merged(max_files=9, max_added_lines=None)
        self.assertEqual(merged.max_files, 9)
        self.assertEqual(merged.max_added_lines, cfg.max_added_lines)

    def test_glob_any(self):
        self.assertTrue(glob_any("tests/test_a.py", ("tests/**",)))
        self.assertTrue(glob_any(".github/workflows/ci.yml", (".github/**",)))
        self.assertFalse(glob_any("src/app.py", ("tests/**",)))

    def test_example_config_is_valid(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = GateConfig.from_file(os.path.join(root, "changegate.example.json"))
        self.assertEqual(cfg.max_files, 12)
        self.assertIn(".github/**", cfg.forbidden)
        self.assertEqual(cfg.test_cmd, "pytest -q")


class TestReports(unittest.TestCase):
    def test_json_report_is_stable_and_without_raw_secret(self):
        result = evaluate([changed("config.py", [fake_secret()])])
        payload = json.loads(dumps(result))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["verdict"], "fail")
        self.assertEqual(payload["errors"], 1)
        self.assertNotIn("a" * 30, dumps(result))

    def test_markdown_report_has_verdict(self):
        result = evaluate([changed("app.py", ["x = 1"])])
        self.assertIn("## changegate: PASS", render_markdown(result))

    def test_text_output_quiet_hides_findings(self):
        result = evaluate([changed("old.py", [], status="deleted")])
        quiet = render_text(result, quiet=True)
        self.assertIn("changegate: PASS", quiet)
        self.assertNotIn("file-deletion", quiet)


if __name__ == "__main__":
    unittest.main()
