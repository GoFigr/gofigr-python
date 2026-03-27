# GoFigr Python Client - Claude Code Guide

## Code Changes

- When deleting or renaming a module/function, always search for all imports and usages across the codebase (grep/Glob) and update them in the same change.

## Debugging

- Before proposing a fix, confirm the root cause with the user if there's ambiguity. Don't assume the first hypothesis — verify which layer (client vs. server) owns the issue.

## Git & Commits

- Always run pre-commit hooks. If linters fail, fix the issues before presenting the commit as ready. Do not use `--no-verify`.
