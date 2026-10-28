# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- SARIF output so GitHub code scanning renders findings as annotations.
- Optional full-history secret scan (`--history`) as a complement to the diff scan.
- Entropy-based detection for credentials that match no known prefix.
- Compound rule: a change that edits tests *and* product code in one diff (classic self-grading
  pattern) gets an explicit, named finding.
- Python API documentation and `--config` schema publication.

## [0.1.0] - 2026-10-28

First public release: the gate is usable in CI and as a pre-commit check.

### Added
- `changegate check` with four diff sources: patch file (`--patch`), staged changes (`--staged`),
  merge-base pull-request mode (`--base`), and the working tree (default); `--patch -` reads
  the diff from stdin.
- Scope gate: max files, max added/removed lines, forbidden path globs (CI config, lockfiles,
  dependency manifests, `.env`, Dockerfiles, key material) and an optional allowed-path list.
- Binary-change gate (rejected by default, `--allow-binary` to opt out).
- Secret gate: AWS, GitHub (classic + fine-grained), OpenAI-style, Anthropic, Stripe, Slack and Google
  keys, JWTs, PEM private-key blocks and generic hardcoded credential assignments; placeholder
  suppression; redacted snippets in every output.
- PII gate: personal email addresses (documentation domains allowlisted) and absolute POSIX/Windows
  home paths.
- Test-tamper gate: edits to test files and CI workflows are blocked unless `--allow-tests`.
- Dangerous-call warnings (`shell=True`, `os.system`, `eval`/`exec`, `pickle`, `curl | sh`,
  `chmod 777`, `rm -rf /`) with `off`/`warning`/`error` modes.
- Optional repository commands: `--test-cmd` and `--lint-cmd`, executed with a scrubbed environment
  and timeout; failures become gate errors.
- Reports: human-readable text, Markdown (`--markdown-out`, `--summary` for `$GITHUB_STEP_SUMMARY`)
  and schema-versioned JSON (`--json-out`).
- `changegate rules` to print the enforced rule set.
- JSON configuration file with unknown-key rejection; example in `changegate.example.json`.
- Deterministic no-network demo (`demo/run_demo.py`) and 78 unit/integration tests.
- Zero runtime dependencies; Python 3.10–3.13.

[Unreleased]: https://github.com/A-G0D/changegate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/A-G0D/changegate/releases/tag/v0.1.0
