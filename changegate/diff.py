"""Unified-diff collection and parsing.

The gate must work in three modes:

* ``git diff`` against a base ref (CI pull-request mode),
* staged changes (pre-commit mode),
* an arbitrary patch file (reviewer mode, no git repository required).

Only added lines carry risk; deletions are counted for the diff-size budget.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field

GIT_DIFF_FLAGS = ("--no-color", "--unified=0", "--find-renames", "--no-ext-diff")


class DiffError(RuntimeError):
    """Raised when a diff cannot be produced or read."""


@dataclass
class AddedLine:
    """A line added by the change."""

    text: str
    line_no: int | None = None  # line number in the new file, when known


@dataclass
class ChangedFile:
    """One file touched by the change."""

    path: str
    status: str = "modified"  # added | modified | deleted | renamed
    old_path: str | None = None
    binary: bool = False
    added: list[AddedLine] = field(default_factory=list)
    removed: int = 0

    @property
    def added_count(self) -> int:
        return len(self.added)


@dataclass
class DiffStats:
    files: int = 0
    added: int = 0
    removed: int = 0
    binary: int = 0


_DIFF_GIT = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@")
_DEV_NULL = "/dev/null"


def _clean_path(path: str) -> str | None:
    """Strip git's ``a/`` / ``b/`` prefixes; map /dev/null to None (new/deleted file)."""
    path = path.strip()
    if not path or path == _DEV_NULL:
        return None
    if path.startswith(("a/", "b/")):
        return path[2:]
    if path.startswith('"') and path.endswith('"'):
        return path[1:-1]
    return path


def parse_unified_diff(text: str) -> list[ChangedFile]:
    """Parse a git-style or plain unified diff into ``ChangedFile`` objects."""
    files: list[ChangedFile] = []
    current: ChangedFile | None = None
    pending_old: str | None = None
    new_line = 0
    in_hunk = False

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            match = _DIFF_GIT.match(raw)
            if match:
                current = ChangedFile(path=_clean_path(match.group("b")) or match.group("b"))
                files.append(current)
            in_hunk = False
            continue

        if raw.startswith("--- "):
            pending_old = _clean_path(raw[4:])
            continue

        if raw.startswith("+++ "):
            new_path = _clean_path(raw[4:])
            if current is None:
                current = ChangedFile(path=new_path or pending_old or "?")
                if pending_old is None and new_path is not None:
                    current.status = "added"
                elif new_path is None and pending_old is not None:
                    current.status = "deleted"
                files.append(current)
            elif pending_old and new_path and pending_old != new_path:
                current.old_path = pending_old
                current.status = "renamed"
            continue

        if current is None:
            continue

        if raw.startswith("new file mode "):
            current.status = "added"
            continue
        if raw.startswith("deleted file mode "):
            current.status = "deleted"
            continue
        if raw.startswith("rename from "):
            current.old_path = raw[len("rename from ") :]
            current.status = "renamed"
            continue
        if raw.startswith("rename to "):
            current.status = "renamed"
            continue
        if raw.startswith(("Binary files ", "GIT binary patch")):
            current.binary = True
            continue

        hunk = _HUNK.match(raw)
        if hunk:
            new_line = int(hunk.group("start"))
            in_hunk = True
            continue

        if not in_hunk or not raw:
            continue
        marker, body = raw[0], raw[1:]
        if marker == "+":
            current.added.append(AddedLine(text=body, line_no=new_line))
            new_line += 1
        elif marker == "-":
            current.removed += 1
        elif marker == " ":
            new_line += 1
        # "\ No newline at end of file" is metadata; ignore.

    return files


def diff_stats(files: list[ChangedFile]) -> DiffStats:
    """Aggregate per-file stats for the report."""
    return DiffStats(
        files=len(files),
        added=sum(f.added_count for f in files),
        removed=sum(f.removed for f in files),
        binary=sum(1 for f in files if f.binary),
    )


def _run_git(repo: str, *args: str, timeout: float = 120.0) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise DiffError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise DiffError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[:500]
        raise DiffError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def git_diff(repo: str, base: str | None = None, staged: bool = False) -> str:
    """Produce a unified diff for a repository.

    Args:
        repo: Path to the repository.
        base: Base ref. When set, diffs ``base...HEAD`` (three-dot: from the merge base),
            which is the correct mode for pull-request CI.
        staged: Diff only staged changes (``--cached``).
    """
    args = ["diff", *GIT_DIFF_FLAGS]
    if base:
        args.append(f"{base}...HEAD")
    elif staged:
        args.append("--cached")
    return _run_git(repo, *args)


def untracked_files(repo: str) -> list[str]:
    """List untracked, non-ignored files so callers can warn that they are not gated."""
    out = _run_git(repo, "ls-files", "--others", "--exclude-standard")
    return [line for line in out.splitlines() if line.strip()]


def read_patch(path: str) -> str:
    """Read a patch file (or ``-`` for stdin), with a clear error instead of a traceback."""
    if path == "-":
        try:
            return sys.stdin.read()
        except OSError as exc:  # pragma: no cover - platform dependent
            raise DiffError(f"cannot read patch from stdin: {exc}") from exc
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        raise DiffError(f"cannot read patch file {path!r}: {exc}") from exc
