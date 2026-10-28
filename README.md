# changegate

[![CI](https://github.com/A-G0D/changegate/actions/workflows/ci.yml/badge.svg)](https://github.com/A-G0D/changegate/actions/workflows/ci.yml)
[![CodeQL](https://github.com/A-G0D/changegate/actions/workflows/codeql.yml/badge.svg)](https://github.com/A-G0D/changegate/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**Deterministic verification gate for agent-authored changes.** One command checks a diff before it
becomes a commit or a pull request: no leaked credentials, no personal data, no test tampering, no
out-of-scope edits, and optionally the repository's own tests and linter.

```
 git diff / patch ──► parse added lines ──► gates ──► PASS / FAIL + JSON report
                                            │
        scope · binary · secrets · PII · test-tamper · dangerous calls · commands
```

Agentic contributors made generating changes cheap. The review bottleneck is now scope and safety:
did the agent touch CI or the tests that grade it, paste a credential, include a home path, or
balloon a 2-line fix into a 40-file rewrite? `changegate` answers that deterministically, in under a
second, with zero runtime dependencies.

Status: **alpha (0.1.0)**.

## Install

```bash
pip install git+https://github.com/A-G0D/changegate.git   # or: pip install -e ".[dev]"
changegate --help
```

Python 3.10+. No runtime dependencies use only the standard library.

## Quickstart

```bash
# 1. gate a patch file (no git repository needed)
changegate check --patch change.diff

# 1b. ...or stream the diff on stdin
git -C /path/to/repo diff | changegate check --patch -

# 2. gate uncommitted changes in the current repository
changegate check

# 3. gate staged changes (pre-commit style)
changegate check --staged

# 4. pull-request CI mode: everything since the merge base with the base branch
changegate check --base origin/main

# 5. optionally run the repository's own checks too
changegate check --base origin/main --test-cmd "pytest -q" --lint-cmd "ruff check ."

# 6. see every rule the gate enforces
changegate rules

# 7. deterministic demo, no network, temporary repos only
python3 demo/run_demo.py
```

Exit codes: **0** pass, **1** gate failure, **2** usage/configuration/diff error.

Example output:

```
changegate: FAIL — 2 error(s), 0 warning(s); 1 file(s), +1/-0
  FAIL config.py:1 openai-key: OpenAI-style API key (secret scan)  [sk-a…******]
  FAIL config.py:1 generic-credential: hardcoded credential assignment (secret scan)  [API_…******]
```

Matched values are redacted in every output (terminal, Markdown and JSON). The gate never prints a
full credential.

## What it checks

| check | severity | detail |
|---|---|---|
| `scope` | error | max files changed, max lines added/removed, `forbidden` globs (`.github/**`, lockfiles, dependency manifests, `.env`, Dockerfiles, key files), optional `allowed` allow-list |
| `binary-file` | error | binary changes cannot be reviewed line by line |
| `secrets` | error | AWS/GitHub/OpenAI/Anthropic/Stripe/Slack/Google keys, JWTs, private-key blocks, generic hardcoded credential assignments in **added** lines |
| `pii` | error | personal email addresses (documentation domains such as `example.com` are allowed) and absolute home paths (`/Users/…`, `/home/…`, `C:\Users\…`) |
| `test-tamper` | error | changes to test files or CI workflows — the files an agent would need in order to grade its own work; `--allow-tests` for intentional changes |
| `dangerous` | warning | `shell=True`, `os.system`, `eval`/`exec`, `pickle`, `curl \| sh`, `chmod 777`, `rm -rf /` — configurable to `off` or `error` |
| `commands` | error | optional `--test-cmd` / `--lint-cmd`, run with credential-shaped environment variables removed and a timeout |

Obvious placeholders (`API_KEY = "your_key_here"`, `os.environ[...]`, `<TOKEN>`) are suppressed so
the gate does not cry wolf on normal code. The rule list is small on purpose: every rule must be
cheap, deterministic, and defensible.

## Configuration

CLI flags cover the common cases; a JSON config file (`--config`, or wire it into CI) sets defaults:

```json
{
  "max_files": 12,
  "max_added_lines": 400,
  "max_removed_lines": 400,
  "allow_tests": false,
  "allow_binary": false,
  "forbidden": [".github/**", "*.lock", "requirements*.txt", ".env*"],
  "allowed": ["**"],
  "ignore": ["docs/generated/**"],
  "dangerous": "warning",
  "test_cmd": "pytest -q",
  "lint_cmd": "ruff check .",
  "command_timeout_s": 300
}
```

See [`changegate.example.json`](changegate.example.json). Unknown keys are rejected so a typo
cannot silently weaken the gate.

## Use it in CI

```yaml
name: agent-change-gate
on: pull_request
permissions:
  contents: read
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # the gate needs history to diff against the base branch
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install git+https://github.com/A-G0D/changegate.git
      - run: changegate check --base origin/${{ github.base_ref }} --json-out changegate.json
      - if: always()
        run: cat changegate.json
```

The job fails when the gate fails, and `changegate.json` is a stable, schema-versioned report
(`"schema_version": 1`) for bots and dashboards. Add `--summary` to append a Markdown table to
`$GITHUB_STEP_SUMMARY`.

## Design rules

1. **Only added lines can introduce risk.** Findings point at added lines; deletions are counted
   toward the diff budget but are not content-scanned.
2. **Deterministic and offline by default.** No network access, no model calls, no repository code
   execution unless you explicitly pass `--test-cmd`/`--lint-cmd`.
3. **Never print a secret.** Findings carry a redacted excerpt (`sk-a…******`) only.
4. **Strict defaults, explicit opt-outs.** Test edits, binaries and protected paths block by
   default; each opt-out is a visible flag in the command or CI diff.
5. **No writes to the repository.** The gate reads a diff and reports; it never stages, commits, or
   modifies files.

## What this is not

- Not a replacement for [gitleaks](https://github.com/gitleaks/gitleaks) or GitHub secret scanning:
  those scan full history and support custom rules. `changegate` is a fast, dependency-free diff gate
  that also covers scope, test tampering and PII. Run both if you can.
- Not a sandbox. `--test-cmd` executes the repository's own command as your user with a scrubbed
  environment; only run it on repositories whose code you trust (see [SECURITY.md](SECURITY.md)).
- Not a judge of correctness. It enforces *rules*, not semantics; tests and the repository's real CI
  are the correctness oracle.

## Limitations

- Secret detection is regex-based on added lines; an encrypted or split credential is not detected.
- Rename detection relies on git's rename output; a patch file without rename metadata may show up
  as an added/deleted pair.
- `--patch` mode parses the diff only: it does not verify that the patch applies to the repository.
- Untracked files are not part of `git diff`; the gate reports them as a warning so they are not
  silently skipped.
- Python API surface (`from changegate.engine import evaluate`) is for tests and integrations; pin
  to a version if you depend on it.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). AI-assisted contributions are welcome with disclosure;
[AGENTS.md](AGENTS.md) defines the rules for autonomous agents in this repository. Security issues:
[SECURITY.md](SECURITY.md). Community expectations: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE) © 2026 A-G0D.
