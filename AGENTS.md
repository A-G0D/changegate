# AGENTS.md — rules for AI agents working in this repository

This file is the contract for autonomous or semi-autonomous coding agents (Claude Code, Codex,
Cursor, OpenHands, custom harnesses, ...) contributing to changegate. Humans get the same rules via
[CONTRIBUTING.md](CONTRIBUTING.md). If your harness supports a project instruction file, point it at
this file.

## TL;DR

1. Read `README.md` and this file before editing.
2. Run `ruff check . && ruff format --check . && python3 -m pytest -q && python3 demo/run_demo.py`.
3. **Never weaken a default check or a test to make your change pass.** A rule may become configurable
   but the strict default must stay strict.
4. No real credentials, personal data, or third-party repository content in code, tests, logs, or
   commit messages. Build fake credentials at runtime (as the existing tests do).
5. Disclose AI assistance in the PR description; be able to explain every changed line yourself.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## The one command that defines "done"

```bash
ruff check . && ruff format --check . && python3 -m pytest -q && python3 demo/run_demo.py
```

## What you may edit

- `changegate/` — parser, rules, checks, report, CLI.
- `tests/` — add coverage for a behavior change. Do not delete, skip, or loosen an existing test to
  make a change pass; if a test encodes the wrong behavior, change the behavior deliberately and say
  so in the PR.
- `README.md` / `CHANGELOG.md` — keep claims honest and measured. Update the changelog for every
  user-visible behavior change.

## What you must not do

- Do not modify `.github/workflows/*` to make CI pass. CI is the oracle; if it is genuinely wrong,
  explain why with evidence in the PR.
- Do not weaken default policy: no raising `max_files`/`max_added_lines`, no removing forbidden globs,
  no turning a default error into a warning, no disabling `test-tamper` by default.
- Do not add runtime dependencies. The zero-dependency property is a feature; discuss first.
- Do not add network access or telemetry to the default code path.
- Do not paste real credentials into tests, logs, issues, or PR descriptions. Use runtime-built fake
  values (see `tests/test_patterns.py`).
- Do not add patterns that flag ordinary code without a placeholder/allowlist path and a test proving
  the false positive is handled.
- Do not impersonate the maintainer or other contributors.

## Code style

- Python 3.10+, `from __future__ import annotations`, type hints on public functions.
- Ruff with the repository config; format with `ruff format`.
- Findings must carry a redacted snippet or none — never the full matched value.
- New rule? Add it to `patterns.py` with a stable `rule_id`, document it in `README.md`, and add
  match tests and (if applicable) false-positive tests.
- New check? Add a function in `engine.py`, call it from `evaluate`, wire it into the report, and add
  tests both ways (pass and fail).

## Repository layout

```
changegate/       package: patterns, diff, engine, report, cli
tests/            unit + integration tests (pytest / unittest compatible)
demo/             deterministic demo, temporary repositories only
.github/          CI, CodeQL, Dependabot, issue templates
```

## Reporting

Security-sensitive changes (regex denial of service, path handling, environment scrubbing, redaction)
must be called out in the PR. Report actual vulnerabilities privately per [SECURITY.md](SECURITY.md).
