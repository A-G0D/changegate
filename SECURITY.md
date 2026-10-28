# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |
| < 0.1 | not released |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private vulnerability
reporting on this repository:

1. Go to <https://github.com/A-G0D/changegate/security/advisories/new>.
2. Describe the issue, the affected version/commit, and a minimal reproduction.

If private reporting is unavailable to you, open a normal issue that says only
"security report — please contact me for details" without exploit details.

## Threat model

`changegate` is a *reader*: by default it parses a diff and inspects added lines. It does not stage,
commit, or modify files, and it makes no network calls. The two places where it interacts with the
environment are:

1. **`--test-cmd` / `--lint-cmd`** execute a command you provide, as your user, inside the repository
   under test, with `*_API_KEY`, `*_TOKEN`, `*SECRET*`, `*PASSWORD*` environment variables removed and
   a timeout. Only run commands on repositories whose code you trust. This is opt-in; a plain
   `changegate check` never executes repository code.
2. **Reading files and running `git diff`** in the target repository. Paths are passed to `git`
   directly (no shell), never interpolated into a shell string.

## What is in scope

- A credential that the documentation claims to detect but that passes the gate *when it is a
  realistic credential pattern* (regex gaps, catastrophic backtracking, rule bypass with near-identical
  syntax). Please include a minimal, clearly synthetic reproduction.
- A way to make the gate print a full credential or personal data instead of a redacted excerpt.
- Command or path injection through configuration values, CLI arguments, or a crafted patch file.
- A crash or infinite loop triggered by a malformed diff (denial of service for CI).
- A repo-controlled file that makes the gate silently skip content it should scan.

## Out of scope

- The gate not detecting a credential pattern that is intentionally not in its rule set. The rules are
  documented and intentionally small; open a feature request instead.
- A hostile repository whose tests you deliberately ran with `--test-cmd`.
- Findings that are technically true but not exploitable (for example, a warning about `eval` in a
  hand-written parser) — treat those as rule-quality issues.
- Vulnerabilities in tools this project is often used alongside (gitleaks, CodeQL, GitHub Actions).

## Release hygiene

The repository itself is protected by the same CI it ships: lint, tests, a deterministic demo, a
gitleaks secret scan, and CodeQL. Dependabot security updates and private vulnerability reporting are
enabled for the repository.
