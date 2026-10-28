"""Deterministic rule sets: credentials, personal data, dangerous calls.

Patterns are intentionally conservative. This is a *gate*, not a malware scanner: it should
never block a normal contribution, and every finding names the rule that fired.

Nothing in this module prints a matched value. Findings carry a redacted snippet only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """One named regex rule."""

    rule_id: str
    label: str
    pattern: re.Pattern[str]
    severity: str = "error"  # "error" | "warning"


def _r(rule_id: str, label: str, regex: str, severity: str = "error") -> Rule:
    return Rule(rule_id, label, re.compile(regex), severity)


# --------------------------------------------------------------------------- #
# Credentials. Test fixtures in this repo build fake keys at runtime so the
# repository itself never contains a literal credential pattern.
# --------------------------------------------------------------------------- #
SECRET_RULES: tuple[Rule, ...] = (
    _r("aws-access-key-id", "AWS access key ID", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    _r("github-token", "GitHub personal access token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    _r(
        "github-fine-grained-token",
        "GitHub fine-grained token",
        r"\bgithub_pat_[A-Za-z0-9_]{60,}\b",
    ),
    _r("openai-key", "OpenAI-style API key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    _r("anthropic-key", "Anthropic API key", r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    _r("stripe-live-key", "Stripe live key", r"\b[rs]k_live_[A-Za-z0-9]{16,}\b"),
    _r("slack-token", "Slack token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    _r("google-api-key", "Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    _r("private-key-block", "Private key block", r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    _r(
        "jwt",
        "JSON Web Token",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    ),
    _r(
        "generic-credential",
        "hardcoded credential assignment",
        r"""(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*["'][A-Za-z0-9_\-./+=]{16,}["']""",
    ),
)

# Conservative placeholder suppression: obvious examples and environment lookups are not leaks.
PLACEHOLDER_HINTS: tuple[str, ...] = (
    "example",
    "sample",
    "dummy",
    "fake",
    "placeholder",
    "redacted",
    "your_",
    "your-",
    "<",
    "${",
    "{{",
    "xxxx",
    "changeme",
    "change-me",
    "replace-me",
    "...",
    "os.environ",
    "getenv",
    "process.env",
)


def is_placeholder(text: str) -> bool:
    """True when a candidate match is obviously a placeholder rather than a credential."""
    lowered = text.lower()
    return any(hint in lowered for hint in PLACEHOLDER_HINTS)


# --------------------------------------------------------------------------- #
# Personal data that must never be committed to a public repository.
# --------------------------------------------------------------------------- #
PII_RULES: tuple[Rule, ...] = (
    _r(
        "email-address",
        "personal email address",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b",
    ),
    _r("posix-home-path", "absolute POSIX home path", r"/(?:Users|home)/[A-Za-z0-9._-]+"),
    _r(
        "windows-home-path",
        "absolute Windows home path",
        r"[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z0-9._-]+",
    ),
)

# Addresses that are documentation examples, not personal data.
EMAIL_DOMAIN_ALLOWLIST: tuple[str, ...] = (
    "example.com",
    "example.org",
    "example.net",
    "example.dev",
    "localhost",
    "noreply.github.com",
    "users.noreply.github.com",
)


# --------------------------------------------------------------------------- #
# Dangerous calls. Warnings, not errors: sometimes there is a legitimate reason.
# --------------------------------------------------------------------------- #
DANGEROUS_RULES: tuple[Rule, ...] = (
    _r(
        "shell-true",
        "subprocess with shell=True",
        r"\bsubprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True",
        "warning",
    ),
    _r("os-system", "os.system call", r"\bos\.system\s*\(", "warning"),
    _r("eval-exec", "eval/exec call", r"\b(?:eval|exec)\s*\(", "warning"),
    _r("pickle-load", "pickle deserialization", r"\bpickle\.loads?\s*\(", "warning"),
    _r("curl-pipe-sh", "curl piped to a shell", r"\bcurl\b[^|\n]*\|\s*(?:ba)?sh", "warning"),
    _r("chmod-777", "chmod 777", r"\bchmod\s+777\b", "warning"),
    _r(
        "rm-rf-root",
        "rm -rf on an absolute path",
        r"\brm\s+(?:-[A-Za-z]*r[A-Za-z]*f[A-Za-z]*|-[A-Za-z]*f[A-Za-z]*r[A-Za-z]*)\s+/(?!tmp\b)",
        "warning",
    ),
)


def redact(value: str, keep: int = 4) -> str:
    """Return a safe excerpt of a matched secret: first few chars only."""
    value = value.strip()
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "…" + "*" * min(6, len(value) - keep)


ALL_RULES: dict[str, tuple[Rule, ...]] = {
    "secrets": SECRET_RULES,
    "pii": PII_RULES,
    "dangerous": DANGEROUS_RULES,
}
