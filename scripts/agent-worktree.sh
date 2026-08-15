#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/agent-worktree.sh create <slug-or-branch>
  scripts/agent-worktree.sh list
  scripts/agent-worktree.sh remove [--force] [--yes] <branch-or-slug>

Create and manage isolated THPM task worktrees. A bare slug receives the
agent/ prefix. Worktrees default to ~/Projects/thpm-worktrees; override the
location with THPM_WORKTREE_DIR.
EOF
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

git rev-parse --show-toplevel >/dev/null 2>&1 || fail "run this command from a THPM checkout"

main_worktree() {
    local path='' branch=''
    while IFS= read -r line; do
        case "$line" in
            worktree\ *) path="${line#worktree }" ;;
            branch\ *)
                branch="${line#branch refs/heads/}"
                if [[ "$branch" == 'main' ]]; then
                    printf '%s\n' "$path"
                    return 0
                fi
                ;;
        esac
    done < <(git worktree list --porcelain)
    return 1
}

control_root="$(main_worktree)" || fail "no main worktree is registered"
worktree_base="${THPM_WORKTREE_DIR:-$(dirname "$control_root")/thpm-worktrees}"

normalize_branch() {
    local value="$1"
    if [[ "$value" == */* ]]; then
        printf '%s\n' "$value"
    else
        printf 'agent/%s\n' "$value"
    fi
}

worktree_record() {
    local query="$1" path='' branch=''
    while IFS= read -r line; do
        case "$line" in
            worktree\ *) path="${line#worktree }" ;;
            branch\ *)
                branch="${line#branch refs/heads/}"
                if [[ "$branch" == "$query" || "${branch#*/}" == "$query" || "$path" == "$query" ]]; then
                    printf '%s\t%s\n' "$path" "$branch"
                    return 0
                fi
                ;;
        esac
    done < <(git worktree list --porcelain)
    return 1
}

create_worktree() {
    [[ $# -eq 1 ]] || fail "create requires one slug or branch name"
    local branch path_slug path
    branch="$(normalize_branch "$1")"
    [[ "$branch" != 'main' ]] || fail "main is a control checkout, not a task branch"
    git check-ref-format --branch "$branch" >/dev/null 2>&1 || fail "invalid branch name: $branch"
    [[ -z "$(git -C "$control_root" status --porcelain)" ]] || fail "the main control checkout has local changes"

    printf 'Fetching origin...\n'
    git fetch --prune origin
    git show-ref --verify --quiet refs/remotes/origin/main || fail "origin/main is unavailable"
    ! git show-ref --verify --quiet "refs/heads/$branch" || fail "local branch already exists: $branch"
    ! git show-ref --verify --quiet "refs/remotes/origin/$branch" || fail "remote branch already exists: $branch"

    path_slug="${branch#*/}"
    path_slug="${path_slug//\//-}"
    path="$worktree_base/$path_slug"
    [[ ! -e "$path" ]] || fail "worktree path already exists: $path"

    mkdir -p "$worktree_base"
    git worktree add -b "$branch" "$path" origin/main

    printf '\nWorktree ready\n\n'
    printf '  Branch: %s\n' "$branch"
    printf '  Path:   %s\n\n' "$path"
    printf 'Next:\n  cd %q\n' "$path"
}

list_worktrees() {
    git worktree list
}

has_merged_pull_request() {
    local branch="$1" count
    command -v gh >/dev/null 2>&1 || return 1
    count="$(gh pr list --head "$branch" --state merged --json number --jq 'length' 2>/dev/null)" || return 1
    [[ "$count" =~ ^[1-9][0-9]*$ ]]
}

remove_worktree() {
    local force=false assume_yes=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --force) force=true ;;
            --yes) assume_yes=true ;;
            -h|--help) usage; return 0 ;;
            --*) fail "unknown remove option: $1" ;;
            *) break ;;
        esac
        shift
    done
    [[ $# -eq 1 ]] || fail "remove requires one branch, slug, or worktree path"

    local record path branch
    record="$(worktree_record "$1")" || fail "no registered worktree matches: $1"
    IFS=$'\t' read -r path branch <<< "$record"
    [[ "$branch" != 'main' ]] || fail "the main control worktree cannot be removed"

    if [[ -n "$(git -C "$path" status --porcelain)" ]]; then
        [[ "$force" == true ]] || fail "worktree has uncommitted changes: $path"
    fi

    git fetch --prune origin
    local merged_by_ancestry=false merged_by_pull_request=false
    if git merge-base --is-ancestor "$branch" origin/main; then
        merged_by_ancestry=true
    elif has_merged_pull_request "$branch"; then
        merged_by_pull_request=true
    else
        [[ "$force" == true ]] || fail "branch is not merged into origin/main and has no merged pull request: $branch"
    fi

    if [[ "$force" == true && "$assume_yes" != true ]]; then
        [[ -t 0 ]] || fail "forced unattended cleanup also requires --yes"
        printf 'Force-remove %s and discard unmerged work? [y/N] ' "$branch" >&2
        read -r answer
        [[ "$answer" == 'y' || "$answer" == 'Y' ]] || fail "cleanup cancelled"
    fi

    if [[ "$force" == true ]]; then
        git worktree remove --force "$path"
        git branch -D "$branch"
    else
        git worktree remove "$path"
        if [[ "$merged_by_ancestry" == true ]]; then
            git branch -d "$branch"
        elif [[ "$merged_by_pull_request" == true ]]; then
            # Squash and rebase merges do not retain the task tip as an ancestor.
            # A merged GitHub pull request is the safety proof for local deletion.
            git branch -D "$branch"
        fi
    fi
    printf 'Removed worktree %s (%s)\n' "$path" "$branch"
}

command="${1:-}"
[[ -n "$command" ]] || { usage; exit 2; }
shift
case "$command" in
    create) create_worktree "$@" ;;
    list) list_worktrees "$@" ;;
    remove) remove_worktree "$@" ;;
    -h|--help|help) usage ;;
    *) usage >&2; fail "unknown command: $command" ;;
esac
