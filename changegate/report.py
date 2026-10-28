"""Report rendering: human-readable text, Markdown for CI summaries, stable JSON for tooling."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .engine import GateConfig, GateResult

SEVERITY_ICON = {"error": "FAIL", "warning": "WARN", "note": "note"}


def _location(finding) -> str:
    if finding.path and finding.line:
        return f"{finding.path}:{finding.line}"
    return finding.path or "—"


def render_text(result: GateResult, *, quiet: bool = False) -> str:
    """Terminal output: verdict first, then the findings."""
    lines = []
    verdict = "PASS" if result.passed else "FAIL"
    stats = result.stats
    lines.append(
        f"changegate: {verdict} — {len(result.errors)} error(s), "
        f"{len(result.warnings)} warning(s); {stats.files} file(s), "
        f"+{stats.added}/-{stats.removed}"
    )
    if result.commands:
        for cmd in result.commands:
            lines.append(f"  [{cmd['name']}] exit {cmd['exit']} ({cmd.get('duration_s', 0)}s)")
    if not quiet:
        for finding in result.findings:
            snippet = f"  [{finding.snippet}]" if finding.snippet else ""
            lines.append(
                f"  {SEVERITY_ICON.get(finding.severity, finding.severity).upper():4s} "
                f"{_location(finding)} {finding.rule}: {finding.message}{snippet}"
            )
    if result.passed and result.warnings:
        lines.append("verdict: pass (warnings do not block; use the JSON report for detail)")
    return "\n".join(lines)


def render_markdown(result: GateResult) -> str:
    """Markdown suitable for a pull-request comment or a CI step summary."""
    verdict = "PASS" if result.passed else "FAIL"
    lines = [
        f"## changegate: {verdict}",
        "",
        f"- errors: **{len(result.errors)}**, warnings: **{len(result.warnings)}**",
        f"- files: **{result.stats.files}**, added: **{result.stats.added}**, "
        f"removed: **{result.stats.removed}**, binary: **{result.stats.binary}**",
    ]
    if result.commands:
        lines += ["", "| command | exit | duration |", "|---|---|---|"]
        for cmd in result.commands:
            lines.append(f"| `{cmd['name']}` | {cmd['exit']} | {cmd.get('duration_s', 0)}s |")
    if result.findings:
        lines += [
            "",
            "| severity | rule | location | detail |",
            "|---|---|---|---|",
        ]
        for finding in result.findings:
            detail = finding.message.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {finding.severity} | `{finding.rule}` | `{_location(finding)}` | {detail} |"
            )
    else:
        lines += ["", "No findings."]
    return "\n".join(lines) + "\n"


def to_dict(result: GateResult, cfg: GateConfig | None = None) -> dict:
    """Stable JSON structure for machines (schema-versioned)."""
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "pass" if result.passed else "fail",
        "errors": len(result.errors),
        "warnings": len(result.warnings),
        "stats": {
            "files": result.stats.files,
            "added_lines": result.stats.added,
            "removed_lines": result.stats.removed,
            "binary_files": result.stats.binary,
        },
        "files": [{"path": f.path, "status": f.status} for f in result.files],
        "findings": [f.as_dict() for f in result.findings],
        "commands": result.commands,
        "config": {
            "max_files": cfg.max_files if cfg else None,
            "max_added_lines": cfg.max_added_lines if cfg else None,
            "allow_tests": cfg.allow_tests if cfg else None,
            "allow_binary": cfg.allow_binary if cfg else None,
        },
    }


def dumps(result: GateResult, cfg: GateConfig | None = None) -> str:
    return json.dumps(to_dict(result, cfg), indent=2, sort_keys=False) + "\n"
