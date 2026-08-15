#!/usr/bin/env bash
set -euo pipefail

root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    printf 'Error: run this command from a THPM checkout\n' >&2
    exit 1
}

cd "$root"
[[ -x .githooks/pre-commit && -x .githooks/pre-push ]] || {
    printf 'Error: committed Git hooks are missing or not executable\n' >&2
    exit 1
}

git config core.hooksPath .githooks

printf 'Development guards enabled\n\n'
printf '  Hooks:  %s/.githooks\n' "$root"
printf '  Policy: commits and pushes to main are rejected\n\n'
printf 'Create a task worktree with:\n  scripts/agent-worktree.sh create <task-slug>\n'
