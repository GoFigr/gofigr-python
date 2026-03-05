# Secrets Checker Setup

This repository uses `detect-secrets` to scan for accidentally committed secrets (API keys, passwords, tokens, etc.).

## Quick Setup

Run the setup script:

```bash
bash scripts/setup-pre-commit.sh
```

Or manually:

```bash
pip install pre-commit detect-secrets
pre-commit install
```

## How It Works

The secrets checker runs automatically on every `git commit` via a pre-commit hook. It scans your staged files for common secret patterns like:

- API keys (AWS, Azure, Google Cloud, etc.)
- Private keys (SSH, RSA, etc.)
- Passwords and tokens
- Database credentials
- OAuth secrets
- And many more...

If a potential secret is detected, the commit will be blocked with an error message.

## Running Manually

To scan all files in the repository:

```bash
pre-commit run detect-secrets --all-files
```

To run all pre-commit hooks:

```bash
pre-commit run --all-files
```

## Handling False Positives

If the checker finds something that's not actually a secret (a false positive), you can add it to the baseline file:

```bash
# After the hook detects it, update the baseline:
pre-commit run detect-secrets --all-files
# Review the findings, then update baseline:
pre-commit run detect-secrets --all-files --update-baseline
```

This updates `.secrets.baseline` which should be committed to the repository.

## Skipping the Check (Not Recommended)

If you absolutely must skip the check (not recommended):

```bash
git commit --no-verify
```

**Warning**: Only skip if you're absolutely certain there are no secrets in your changes.

## CI Integration

The secrets check also runs in GitHub Actions CI as a safety net. If secrets are detected in CI, the build will fail.

## What Gets Scanned

The checker scans all files except:
- `.secrets.baseline` (the baseline file itself)
- `.gitignore`
- `package-lock.json` and `yarn.lock` (known false positives)
- Files matched by `.gitignore` patterns

## Updating Pre-commit Hooks

To update to the latest versions:

```bash
pre-commit autoupdate
```
