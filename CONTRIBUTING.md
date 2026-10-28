# Contributing to changegate

Thanks for considering a contribution. This tool gates changes, so its own contribution rules are
about evidence rather than ceremony.

## Development setup

```bash
git clone https://github.com/A-G0D/changegate.git
cd changegate
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

No runtime dependencies are needed, so the environment is quick to build.

## Before you open a PR

Run exactly what CI runs:

```bash
ruff check .
ruff format --check .
python3 -m pytest -q
python3 demo/run_demo.py
```

All four must pass. Paste the commands and results in the PR description. If you change a rule or a
check, add a test that fails without your change and passes with it.

## Commit messages

Conventional commits, imperative mood, subject ≤ 72 characters:

```
feat(rules): detect fine-grained GitHub tokens
fix(diff): handle renames in plain unified diffs
docs(readme): document exit codes
```

One logical change per PR; no reformatting-only PRs.

## What we will not merge

- Removing or weakening a default check to make a test pass. Defaults are the product; every
  relaxation needs a test, a documented flag, and a reason.
- Rules that flag normal code (false positives cost adoption more than misses at this stage). If you
  add a rule, include the placeholder/allowlist handling and a false-positive test.
- Secret-shaped strings or real credentials in the tree. Tests build fake credentials at runtime;
  do the same.
- Runtime dependencies without prior discussion and a changelog entry.
- Network access in the default code path. The gate must stay deterministic and offline.

## AI-assisted contributions

AI-assisted contributions are allowed and expected. Please disclose with one line in the PR, be able
to explain every changed line, and include the verification output you actually ran. See
[AGENTS.md](AGENTS.md) for the rules that autonomous agents must follow in this repository.

## Reporting bugs and requesting features

Use the issue templates. Good bug reports include the command, a minimal diff or patch, the expected
verdict, and the actual verdict. Never paste real credentials or private repository content.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
