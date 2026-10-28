#!/usr/bin/env python3
"""Deterministic demo: no network, no keys, temporary repositories only.

Shows the three things the gate exists to stop:

1. a clean change passes;
2. a change that leaks a credential fails;
3. a change that edits the tests that grade it fails.

Run from anywhere: ``python3 demo/run_demo.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from changegate.cli import main  # noqa: E402

GIT = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def commit(repo: str, message: str) -> None:
    run("git", "add", "-A", cwd=repo)
    proc = run(*GIT, "commit", "-qm", message, cwd=repo)
    if proc.returncode != 0:
        raise SystemExit(f"demo setup failed: {proc.stderr}")


def write(repo: str, path: str, content: str) -> None:
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(content)


def main_demo() -> int:
    tmp = tempfile.mkdtemp(prefix="changegate-demo-")
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    run("git", "init", "-q", "-b", "main", cwd=repo)
    write(repo, "app.py", "def add(a, b):\n    return a + b\n")
    commit(repo, "init")

    failures = 0

    def check_staged() -> int:
        run("git", "add", "-A", cwd=repo)
        return main(["check", "--repo", repo, "--staged"])

    print("=" * 72)
    print("1) clean change -> expect PASS (exit 0)")
    print("=" * 72)
    write(repo, "app.py", "def add(a, b):\n    total = a + b\n    return total\n")
    rc = check_staged()
    failures += rc != 0
    commit(repo, "refactor")

    print()
    print("=" * 72)
    print("2) leaked credential -> expect FAIL (exit 1)")
    print("=" * 72)
    # Built at runtime so the demo script itself never contains a literal credential.
    fake_key = "sk-" + "a" * 30
    write(repo, "config.py", f'API_KEY = "{fake_key}"\n')
    rc = check_staged()
    failures += rc != 1
    run("git", "reset", "--hard", "HEAD", cwd=repo)
    run("git", "clean", "-fd", cwd=repo)

    print()
    print("=" * 72)
    print("3) test edit -> expect FAIL (exit 1)")
    print("=" * 72)
    write(repo, "tests/test_app.py", "def test_placeholder():\n    assert True\n")
    rc = check_staged()
    failures += rc != 1

    print()
    print("=" * 72)
    if failures:
        print(f"DEMO FAILED: {failures} expectation(s) not met")
        return 1
    print("DEMO OK: clean change passed, credential and test tampering were blocked")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main_demo())
    finally:
        # Best-effort cleanup of the scratch repository.
        tmpdir = tempfile.gettempdir()
        for name in os.listdir(tmpdir):
            if name.startswith("changegate-demo-"):
                shutil.rmtree(os.path.join(tmpdir, name), ignore_errors=True)
