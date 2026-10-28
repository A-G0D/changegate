"""Diff collection and parsing tests (no network, temporary git repositories only)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from changegate.diff import (
    DiffError,
    diff_stats,
    git_diff,
    parse_unified_diff,
    read_patch,
    untracked_files,
)


def make_repo(tmp: str) -> str:
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    with open(os.path.join(repo, "app.py"), "w", encoding="utf-8") as fh:
        fh.write("def add(a, b):\n    return a + b\n")
    with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# demo\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
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
        cwd=repo,
        check=True,
    )
    return repo


class TestParse(unittest.TestCase):
    def test_modified_file_with_hunk(self):
        text = (
            "diff --git a/app.py b/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1,2 +1,3 @@\n"
            " def add(a, b):\n"
            "-    return a + b\n"
            "+    total = a + b\n"
            "+    return total\n"
            " # end\n"
        )
        files = parse_unified_diff(text)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].path, "app.py")
        self.assertEqual(files[0].status, "modified")
        self.assertEqual(files[0].removed, 1)
        self.assertEqual(
            [a.text for a in files[0].added], ["    total = a + b", "    return total"]
        )
        self.assertEqual(files[0].added[0].line_no, 2)

    def test_new_and_deleted_files(self):
        text = (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+print('hi')\n"
            "+\n"
            "diff --git a/old.py b/old.py\n"
            "deleted file mode 100644\n"
            "--- a/old.py\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-print('bye')\n"
        )
        files = parse_unified_diff(text)
        self.assertEqual([f.path for f in files], ["new.py", "old.py"])
        self.assertEqual(files[0].status, "added")
        self.assertEqual(files[1].status, "deleted")

    def test_binary_and_rename(self):
        text = (
            "diff --git a/logo.png b/logo.png\n"
            "new file mode 100644\n"
            "Binary files /dev/null and b/logo.png differ\n"
            "diff --git a/old_name.py b/new_name.py\n"
            "similarity index 100%\n"
            "rename from old_name.py\n"
            "rename to new_name.py\n"
        )
        files = parse_unified_diff(text)
        self.assertTrue(files[0].binary)
        self.assertFalse(files[0].added)
        self.assertEqual(files[1].status, "renamed")
        self.assertEqual(files[1].old_path, "old_name.py")

    def test_plain_unified_diff_without_git_header(self):
        text = "--- a/app.py\n+++ b/app.py\n@@ -1 +1,2 @@\n def add(a, b):\n+    return a + b\n"
        files = parse_unified_diff(text)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].path, "app.py")
        self.assertEqual([a.text for a in files[0].added], ["    return a + b"])

    def test_stats(self):
        files = parse_unified_diff(
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n-x\n+y\n+z\n"
        )
        stats = diff_stats(files)
        self.assertEqual((stats.files, stats.added, stats.removed), (1, 2, 1))


class TestGitCollection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cg-diff-")
        self.repo = make_repo(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_working_tree_diff(self):
        with open(os.path.join(self.repo, "app.py"), "a", encoding="utf-8") as fh:
            fh.write("EXTRA = 1\n")
        files = parse_unified_diff(git_diff(self.repo))
        self.assertEqual([f.path for f in files], ["app.py"])
        self.assertIn("EXTRA = 1", files[0].added[0].text)

    def test_staged_diff(self):
        with open(os.path.join(self.repo, "app.py"), "a", encoding="utf-8") as fh:
            fh.write("STAGED = 2\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.repo, check=True)
        files = parse_unified_diff(git_diff(self.repo, staged=True))
        self.assertEqual([f.path for f in files], ["app.py"])
        self.assertIn("STAGED = 2", files[0].added[0].text)

    def test_base_ref_diff(self):
        first = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True
        ).stdout.strip()
        with open(os.path.join(self.repo, "app.py"), "a", encoding="utf-8") as fh:
            fh.write("COMMITTED = 3\n")
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
                "change",
            ],
            cwd=self.repo,
            check=True,
        )
        files = parse_unified_diff(git_diff(self.repo, base=first))
        self.assertEqual([f.path for f in files], ["app.py"])
        self.assertIn("COMMITTED = 3", files[0].added[0].text)

    def test_untracked_files_listed(self):
        with open(os.path.join(self.repo, "scratch.txt"), "w", encoding="utf-8") as fh:
            fh.write("draft\n")
        self.assertEqual(untracked_files(self.repo), ["scratch.txt"])

    def test_bad_repo_raises_diff_error(self):
        with self.assertRaises(DiffError):
            git_diff(os.path.join(self.tmp, "does-not-exist"))

    def test_missing_patch_file_raises_diff_error(self):
        with self.assertRaises(DiffError):
            read_patch(os.path.join(self.tmp, "missing.diff"))


if __name__ == "__main__":
    unittest.main()
