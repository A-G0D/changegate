"""The gate engine: deterministic checks applied to the added lines of a change.

Every check returns ``Finding`` objects. Errors block the change; warnings are reported but do not
change the exit code. The engine is pure with respect to the repository: it never writes, stages,
or commits anything, and subprocess checks run with credential-shaped environment variables
removed.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from .diff import ChangedFile, DiffStats, diff_stats
from .patterns import (
    DANGEROUS_RULES,
    EMAIL_DOMAIN_ALLOWLIST,
    PII_RULES,
    SECRET_RULES,
    Rule,
    is_placeholder,
    redact,
)

DEFAULT_FORBIDDEN_GLOBS: tuple[str, ...] = (
    ".github/**",
    "*.lock",
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements*.txt",
    ".env",
    ".env.*",
    "Dockerfile",
    "docker-compose*.yml",
    "*.pem",
    "*.key",
)

DEFAULT_TEST_GLOBS: tuple[str, ...] = (
    "tests/**",
    "test/**",
    "**/tests/**",
    "**/test/**",
    "**/__tests__/**",
    "**/spec/**",
    "test_*.py",
    "*_test.py",
    "*_test.go",
    "conftest.py",
    "pytest.ini",
    "tox.ini",
    "jest.config.*",
    "vitest.config.*",
)

DEFAULT_ALLOWED_GLOBS: tuple[str, ...] = ("**",)

SECRET_ENV_RE = re.compile(r"(API_KEY|_TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)

CONFIG_KEYS = {
    "max_files",
    "max_added_lines",
    "max_removed_lines",
    "allow_tests",
    "allow_binary",
    "forbidden",
    "allowed",
    "ignore",
    "dangerous",
    "test_cmd",
    "lint_cmd",
    "command_timeout_s",
}


class ConfigError(ValueError):
    """Raised for an invalid configuration file or CLI override."""


def glob_any(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Match a POSIX-style path against shell globs (``**`` also matches ``/``)."""
    normalized = path.replace(os.sep, "/")
    return any(
        fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch("/" + normalized, pattern)
        for pattern in patterns
    )


@dataclass
class GateConfig:
    """Tunable policy. Defaults are deliberately strict for agent-authored changes."""

    max_files: int = 12
    max_added_lines: int = 400
    max_removed_lines: int = 400
    allow_tests: bool = False
    allow_binary: bool = False
    forbidden: tuple[str, ...] = DEFAULT_FORBIDDEN_GLOBS
    allowed: tuple[str, ...] = DEFAULT_ALLOWED_GLOBS
    ignore: tuple[str, ...] = ()
    dangerous: str = "warning"  # off | warning | error
    test_cmd: str | None = None
    lint_cmd: str | None = None
    command_timeout_s: float = 300.0

    def __post_init__(self) -> None:
        if self.dangerous not in ("off", "warning", "error"):
            raise ConfigError("dangerous must be one of: off, warning, error")
        for name in ("max_files", "max_added_lines", "max_removed_lines"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ConfigError(f"{name} must be a non-negative integer")
        if self.command_timeout_s <= 0:
            raise ConfigError("command_timeout_s must be positive")

    @classmethod
    def from_file(cls, path: str) -> GateConfig:
        """Load a JSON config file; unknown keys are rejected to catch typos."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError as exc:
            raise ConfigError(f"cannot read config {path!r}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid JSON in config {path!r}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("config file must contain a JSON object")
        unknown = set(data) - CONFIG_KEYS
        if unknown:
            raise ConfigError(f"unknown config keys: {', '.join(sorted(unknown))}")
        for list_key in ("forbidden", "allowed", "ignore"):
            if list_key in data:
                if not isinstance(data[list_key], list) or not all(
                    isinstance(x, str) for x in data[list_key]
                ):
                    raise ConfigError(f"{list_key} must be a list of strings")
                data[list_key] = tuple(data[list_key])
        return cls(**data)

    def merged(self, **overrides: Any) -> GateConfig:
        """Return a copy with non-None CLI overrides applied."""
        values = {key: getattr(self, key) for key in CONFIG_KEYS}
        values.update({k: v for k, v in overrides.items() if v is not None})
        return GateConfig(**values)

    def scannable(self, files: list[ChangedFile]) -> list[ChangedFile]:
        """Files that content checks should inspect (``ignore`` globs excluded)."""
        return [f for f in files if not self.ignore or not glob_any(f.path, self.ignore)]


@dataclass
class Finding:
    """One rule violation or note."""

    rule: str
    severity: str  # error | warning | note
    message: str
    path: str | None = None
    line: int | None = None
    snippet: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "snippet": self.snippet,
        }


@dataclass
class GateResult:
    """Outcome of running every check."""

    findings: list[Finding] = field(default_factory=list)
    files: list[ChangedFile] = field(default_factory=list)
    stats: DiffStats = field(default_factory=DiffStats)
    commands: list[dict[str, Any]] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def _content_files(files: list[ChangedFile], cfg: GateConfig) -> list[ChangedFile]:
    return [f for f in cfg.scannable(files) if not f.binary and f.status != "deleted"]


def check_scope(files: list[ChangedFile], cfg: GateConfig) -> list[Finding]:
    """Diff budget: file count, line count, forbidden and out-of-scope paths."""
    findings: list[Finding] = []
    stats = diff_stats(files)

    if not files:
        findings.append(
            Finding(
                "empty-diff",
                "warning",
                "no changes found — nothing was gated (check the base ref / patch)",
            )
        )
        return findings

    if stats.files > cfg.max_files:
        findings.append(
            Finding(
                "max-files",
                "error",
                f"{stats.files} files changed, limit is {cfg.max_files}",
            )
        )
    if stats.added > cfg.max_added_lines:
        findings.append(
            Finding(
                "max-added-lines",
                "error",
                f"{stats.added} lines added, limit is {cfg.max_added_lines}",
            )
        )
    if stats.removed > cfg.max_removed_lines:
        findings.append(
            Finding(
                "max-removed-lines",
                "error",
                f"{stats.removed} lines removed, limit is {cfg.max_removed_lines}",
            )
        )

    for f in files:
        if glob_any(f.path, cfg.forbidden):
            findings.append(
                Finding(
                    "forbidden-path",
                    "error",
                    "change touches a protected path (CI, dependency, lock or secret file)",
                    path=f.path,
                )
            )
        if not glob_any(f.path, cfg.allowed):
            findings.append(
                Finding(
                    "out-of-scope-path",
                    "error",
                    "change touches a path outside the allowed scope",
                    path=f.path,
                )
            )
        if f.status == "deleted":
            findings.append(
                Finding("file-deletion", "warning", "change deletes a file", path=f.path)
            )
    return findings


def check_binary(files: list[ChangedFile], cfg: GateConfig) -> list[Finding]:
    """Binary changes cannot be reviewed line by line and are rejected by default."""
    if cfg.allow_binary:
        return []
    return [
        Finding(
            "binary-file",
            "error",
            "binary file added or modified (reviewable diffs only)",
            path=f.path,
        )
        for f in cfg.scannable(files)
        if f.binary and f.status != "deleted"
    ]


def _rule_hits(
    files: list[ChangedFile],
    cfg: GateConfig,
    rules: tuple[Rule, ...],
    severity: str,
    label: str,
) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str, int | None]] = set()
    for f in _content_files(files, cfg):
        for added in f.added:
            text = added.text
            if not text.strip():
                continue
            for rule in rules:
                if rule.severity == "warning" and severity != "warning":
                    continue
                for match in rule.pattern.finditer(text):
                    value = match.group(0)
                    # Suppress obvious placeholders and documentation examples.
                    if is_placeholder(text):
                        continue
                    if rule.rule_id == "email-address":
                        domain = value.rsplit("@", 1)[-1].lower()
                        if any(
                            domain == d or domain.endswith("." + d) for d in EMAIL_DOMAIN_ALLOWLIST
                        ):
                            continue
                    key = (rule.rule_id, f.path, added.line_no)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(
                        Finding(
                            rule.rule_id,
                            severity,
                            f"{rule.label} ({label})",
                            path=f.path,
                            line=added.line_no,
                            snippet=redact(value),
                        )
                    )
    return findings


def check_secrets(files: list[ChangedFile], cfg: GateConfig) -> list[Finding]:
    """Credential-shaped strings in added lines."""
    return _rule_hits(files, cfg, SECRET_RULES, "error", "secret scan")


def check_pii(files: list[ChangedFile], cfg: GateConfig) -> list[Finding]:
    """Personal data that must not be published: emails and absolute home paths."""
    return _rule_hits(files, cfg, PII_RULES, "error", "privacy scan")


def check_test_tamper(files: list[ChangedFile], cfg: GateConfig) -> list[Finding]:
    """Agent changes may not edit the tests that grade them unless explicitly allowed."""
    if cfg.allow_tests:
        return []
    return [
        Finding(
            "test-tamper",
            "error",
            "test/CI-adjacent file modified; use --allow-tests for intentional test changes",
            path=f.path,
        )
        for f in files
        if glob_any(f.path, DEFAULT_TEST_GLOBS) or glob_any(f.path, (".github/**",))
    ]


def check_dangerous(files: list[ChangedFile], cfg: GateConfig) -> list[Finding]:
    """Risky calls added by the change (warnings by default)."""
    if cfg.dangerous == "off":
        return []
    findings: list[Finding] = []
    for f in _content_files(files, cfg):
        for added in f.added:
            for rule in DANGEROUS_RULES:
                if rule.pattern.search(added.text):
                    findings.append(
                        Finding(
                            rule.rule_id,
                            cfg.dangerous,
                            rule.label,
                            path=f.path,
                            line=added.line_no,
                            snippet=redact(added.text.strip(), keep=40),
                        )
                    )
    return findings


def scrubbed_env() -> dict[str, str]:
    """Environment for subprocess checks, with credential-shaped variables removed."""
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV_RE.search(k)}
    env.update({"CI": "1", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def _run_command(name: str, command: str, repo: str, timeout: float) -> dict[str, Any]:
    started = time.time()
    record: dict[str, Any] = {"name": name, "cmd": command, "exit": None, "tail": ""}
    try:
        args = shlex.split(command)
    except ValueError as exc:
        record["exit"] = -1
        record["tail"] = f"could not parse command: {exc}"
        return record
    if not args:
        record["exit"] = -1
        record["tail"] = "empty command"
        return record
    try:
        proc = subprocess.run(
            args,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=scrubbed_env(),
        )
        record["exit"] = proc.returncode
        record["tail"] = (proc.stdout + proc.stderr).strip()[-800:]
    except FileNotFoundError as exc:
        record["exit"] = 127
        record["tail"] = str(exc)
    except subprocess.TimeoutExpired:
        record["exit"] = 124
        record["tail"] = f"timed out after {timeout}s"
    record["duration_s"] = round(time.time() - started, 2)
    return record


def check_commands(repo: str, cfg: GateConfig) -> tuple[list[Finding], list[dict[str, Any]]]:
    """Optionally run the repository's own checks (tests/lint) with a scrubbed env."""
    findings: list[Finding] = []
    records: list[dict[str, Any]] = []
    for name, command in (("tests", cfg.test_cmd), ("lint", cfg.lint_cmd)):
        if not command:
            continue
        record = _run_command(name, command, repo, cfg.command_timeout_s)
        records.append(record)
        if record["exit"] != 0:
            findings.append(
                Finding(
                    f"command-{name}",
                    "error",
                    f"{name} command failed (exit {record['exit']}): {command}\n{record['tail']}",
                )
            )
    return findings, records


def evaluate(
    files: list[ChangedFile],
    cfg: GateConfig | None = None,
    repo: str | None = None,
    untracked: list[str] | None = None,
) -> GateResult:
    """Run every check and return the combined result."""
    cfg = cfg or GateConfig()
    findings: list[Finding] = []
    findings += check_scope(files, cfg)
    findings += check_binary(files, cfg)
    findings += check_secrets(files, cfg)
    findings += check_pii(files, cfg)
    findings += check_test_tamper(files, cfg)
    findings += check_dangerous(files, cfg)
    commands: list[dict[str, Any]] = []
    if repo and (cfg.test_cmd or cfg.lint_cmd):
        command_findings, commands = check_commands(repo, cfg)
        findings += command_findings
    if untracked:
        preview = ", ".join(untracked[:10])
        more = f" (+{len(untracked) - 10} more)" if len(untracked) > 10 else ""
        findings.append(
            Finding(
                "untracked-files",
                "warning",
                f"{len(untracked)} untracked file(s) are not covered by this diff: {preview}{more}",
            )
        )
    return GateResult(findings=findings, files=files, stats=diff_stats(files), commands=commands)
