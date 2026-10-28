"""CLI tests: the commands users actually run must work from a clean install."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from changegate.cli import main

CLEAN_PATCH = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a + b + 0
"""


def fake_secret_patch() -> str:
    secret = "API_KEY = " + '"' + "a" * 30 + '"'
    return (
        "diff --git a/config.py b/config.py\n"
        "--- a/config.py\n"
        "+++ b/config.py\n"
        "@@ -0,0 +1,1 @@\n"
        f"+  {secret}\n"
    )


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cg-cli-")
        self.patch = os.path.join(self.tmp, "change.diff")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text: str) -> str:
        with open(self.patch, "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.patch

    def test_rules_lists_every_rule(self):
        self.assertEqual(main(["rules"]), 0)

    def test_clean_patch_passes(self):
        self.assertEqual(main(["check", "--patch", self.write(CLEAN_PATCH)]), 0)

    def test_secret_patch_fails(self):
        rc = main(["check", "--patch", self.write(fake_secret_patch())])
        self.assertEqual(rc, 1)

    def test_json_report_written(self):
        out = os.path.join(self.tmp, "report.json")
        rc = main(["check", "--patch", self.write(fake_secret_patch()), "--json-out", out])
        self.assertEqual(rc, 1)
        with open(out, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["verdict"], "fail")
        self.assertGreaterEqual(payload["errors"], 1)

    def test_markdown_report_written(self):
        out = os.path.join(self.tmp, "report.md")
        rc = main(["check", "--patch", self.write(CLEAN_PATCH), "--markdown-out", out, "--quiet"])
        self.assertEqual(rc, 0)
        with open(out, encoding="utf-8") as fh:
            self.assertIn("## changegate: PASS", fh.read())

    def test_test_file_patch_blocks_unless_allowed(self):
        patch = (
            "diff --git a/tests/test_app.py b/tests/test_app.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/tests/test_app.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+import unittest\n"
        )
        path = self.write(patch)
        self.assertEqual(main(["check", "--patch", path]), 1)
        self.assertEqual(main(["check", "--patch", path, "--allow-tests"]), 0)

    def test_limits_are_configurable(self):
        path = self.write(CLEAN_PATCH)
        self.assertEqual(main(["check", "--patch", path, "--max-added-lines", "0"]), 1)

    def test_missing_patch_returns_usage_error(self):
        self.assertEqual(main(["check", "--patch", os.path.join(self.tmp, "nope.diff")]), 2)

    def test_invalid_config_returns_usage_error(self):
        cfg = os.path.join(self.tmp, "bad.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"unknown_option": True}, fh)
        self.assertEqual(main(["check", "--patch", self.write(CLEAN_PATCH), "--config", cfg]), 2)

    def test_config_file_is_applied(self):
        cfg = os.path.join(self.tmp, "config.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"max_added_lines": 0}, fh)
        self.assertEqual(main(["check", "--patch", self.write(CLEAN_PATCH), "--config", cfg]), 1)


class TestCliOnGitRepo(unittest.TestCase):
    """PR-mode and working-tree mode against a real repository."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cg-cli-git-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        with open(os.path.join(self.repo, "app.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=demo",
                "-c",
                "user.email=demo@example.com",
                "commit",
                "-qm",
                "init",
            ],
            cwd=self.repo,
            check=True,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_base_ref_mode_blocks_secret(self):
        with open(os.path.join(self.repo, "config.py"), "w", encoding="utf-8") as fh:
            fh.write("API_KEY = " + '"' + "a" * 30 + '"' + "\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=demo",
                "-c",
                "user.email=demo@example.com",
                "commit",
                "-qm",
                "leak",
            ],
            cwd=self.repo,
            check=True,
        )
        self.assertEqual(main(["check", "--repo", self.repo, "--base", "HEAD~1"]), 1)

    def test_base_ref_mode_clean_change_passes(self):
        with open(os.path.join(self.repo, "app.py"), "a", encoding="utf-8") as fh:
            fh.write("y = 2\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=demo",
                "-c",
                "user.email=demo@example.com",
                "commit",
                "-qm",
                "clean",
            ],
            cwd=self.repo,
            check=True,
        )
        self.assertEqual(main(["check", "--repo", self.repo, "--base", "HEAD~1"]), 0)

    def test_working_tree_mode_sees_uncommitted_change(self):
        with open(os.path.join(self.repo, "app.py"), "a", encoding="utf-8") as fh:
            fh.write("z = 3\n")
        self.assertEqual(main(["check", "--repo", self.repo]), 0)

    def test_test_command_runs_against_repo(self):
        with open(os.path.join(self.repo, "app.py"), "a", encoding="utf-8") as fh:
            fh.write("z = 3\n")
        ok_cmd = "python3 -c 'import os, sys; sys.exit(0 if os.path.exists(\"app.py\") else 7)'"
        self.assertEqual(main(["check", "--repo", self.repo, "--test-cmd", ok_cmd]), 0)
        self.assertEqual(
            main(
                ["check", "--repo", self.repo, "--test-cmd", "python3 -c 'import sys; sys.exit(3)'"]
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
