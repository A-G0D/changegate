"""changegate CLI: ``check`` a diff against the gates, or list the rules."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .diff import DiffError, git_diff, parse_unified_diff, read_patch, untracked_files
from .engine import ConfigError, GateConfig, evaluate
from .patterns import ALL_RULES
from .report import dumps, render_markdown, render_text


def _build_config(args: argparse.Namespace) -> GateConfig:
    config = GateConfig.from_file(args.config) if args.config else GateConfig()
    return config.merged(
        max_files=args.max_files,
        max_added_lines=args.max_added_lines,
        max_removed_lines=args.max_removed_lines,
        allow_tests=True if args.allow_tests else None,
        allow_binary=True if args.allow_binary else None,
        forbidden=tuple(args.forbidden) if args.forbidden else None,
        ignore=tuple(args.ignore) if args.ignore else None,
        dangerous=args.dangerous,
        test_cmd=args.test_cmd,
        lint_cmd=args.lint_cmd,
    )


def cmd_check(args: argparse.Namespace) -> int:
    """Collect a diff, run the gates, print a report, and return an exit code."""
    cfg = _build_config(args)
    repo = os.path.abspath(args.repo or os.getcwd())
    untracked: list[str] | None = None

    if args.patch:
        files = parse_unified_diff(read_patch(args.patch))
    elif args.base or args.staged:
        files = parse_unified_diff(git_diff(repo, base=args.base, staged=args.staged))
    else:
        files = parse_unified_diff(git_diff(repo))
        untracked = untracked_files(repo)

    result = evaluate(
        files,
        cfg,
        repo=repo if (cfg.test_cmd or cfg.lint_cmd) else None,
        untracked=untracked,
    )
    print(render_text(result, quiet=args.quiet))

    if args.json_out:
        _write(args.json_out, dumps(result, cfg))
    if args.markdown_out:
        _write(args.markdown_out, render_markdown(result))
    if args.summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        _append(os.environ["GITHUB_STEP_SUMMARY"], render_markdown(result))
    return 0 if result.passed else 1


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _append(path: str, content: str) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(content)


def cmd_rules(_: argparse.Namespace) -> int:
    """Print every rule so users can see exactly what is enforced."""
    for group, rules in ALL_RULES.items():
        print(f"{group}:")
        for rule in rules:
            print(f"  {rule.rule_id:26s} {rule.severity:7s} {rule.label}")
    print("\nchecks:")
    for name in (
        "scope (max files/lines, forbidden paths, deletions)",
        "binary (binaries rejected by default)",
        "secrets (credential-shaped strings in added lines)",
        "pii (emails, absolute home paths)",
        "test-tamper (tests and CI workflows may not be edited)",
        "dangerous (shell=True, eval/exec, ... — warnings by default)",
        "commands (optional --test-cmd / --lint-cmd)",
    ):
        print(f"  - {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="changegate",
        description="Deterministic verification gate for agent-authored changes.",
    )
    parser.add_argument("--version", action="version", version=f"changegate {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check", help="gate a diff (git working tree, staged, base ref, or patch)"
    )
    check.add_argument("--repo", default=None, help="repository path (default: current directory)")
    source = check.add_mutually_exclusive_group()
    source.add_argument("--patch", default=None, help="read a unified diff from a file")
    source.add_argument("--base", default=None, help="diff this base ref against HEAD (CI mode)")
    source.add_argument("--staged", action="store_true", help="diff staged changes only")
    check.add_argument("--config", default=None, help="JSON config file (default: none)")
    check.add_argument("--max-files", type=int, default=None)
    check.add_argument("--max-added-lines", type=int, default=None)
    check.add_argument("--max-removed-lines", type=int, default=None)
    check.add_argument(
        "--allow-tests", action="store_true", help="allow intentional test file changes"
    )
    check.add_argument("--allow-binary", action="store_true", help="allow binary file changes")
    check.add_argument(
        "--forbidden",
        action="append",
        default=None,
        help="forbidden path glob (repeatable; replaces the default list)",
    )
    check.add_argument(
        "--ignore",
        action="append",
        default=None,
        help="path glob excluded from content scanning (repeatable)",
    )
    check.add_argument(
        "--dangerous",
        choices=("off", "warning", "error"),
        default=None,
        help="how to treat risky-call findings (default: warning)",
    )
    check.add_argument("--test-cmd", default=None, help="run the repo's test command")
    check.add_argument("--lint-cmd", default=None, help="run the repo's lint command")
    check.add_argument("--json-out", default=None, help="write a machine-readable report")
    check.add_argument("--markdown-out", default=None, help="write a Markdown report")
    check.add_argument(
        "--summary",
        action="store_true",
        help="append the Markdown report to $GITHUB_STEP_SUMMARY when set",
    )
    check.add_argument("--quiet", action="store_true", help="verdict and stats only")
    check.set_defaults(func=cmd_check)

    rules = sub.add_parser("rules", help="list the rules the gate enforces")
    rules.set_defaults(func=cmd_rules)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ConfigError, DiffError) as exc:
        print(f"changegate: {exc}", file=sys.stderr)
        return 2
