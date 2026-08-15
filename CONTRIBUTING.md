# Contributing to THPM

THPM uses short-lived branches, isolated Git worktrees, and pull requests for every change. The `main` branch is not a development workspace.

## Create a worktree

From the primary checkout:

```bash
cd ~/Projects/thpm
scripts/agent-worktree.sh create fix-cava-detection
```

The helper fetches `origin`, creates `agent/fix-cava-detection` from the current `origin/main`, and prints the new worktree path. Enter that directory before editing files.

Use an explicit branch prefix when appropriate:

```bash
scripts/agent-worktree.sh create fix/cava-detection
scripts/agent-worktree.sh create feat/plugin-import
scripts/agent-worktree.sh create docs/install-guide
```

List active worktrees with:

```bash
scripts/agent-worktree.sh list
```

## Develop and verify

Keep each branch focused on one change. Follow existing project conventions and run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src
bash -n install.sh uninstall.sh assets/hooks/90-thpm scripts/*.sh
ruff check --select E9,F src tests
```

When available, also run ShellCheck and QML lint for changed shell or QML files. `tests/run.sh` is the authoritative complete test entry point.

## Submit a pull request

Push the task branch, then open a pull request targeting `main`:

```bash
git push -u origin HEAD
gh pr create --draft --fill --base main
```

Record verification commands and risks in the pull request template. Resolve review conversations and wait for required CI before marking the pull request ready. Only the repository owner merges pull requests.

## Clean up

After the pull request is merged, return to the primary checkout and run:

```bash
scripts/agent-worktree.sh remove fix-cava-detection
```

The helper refuses to remove worktrees with uncommitted changes or branches that have not been merged into `origin/main` unless an explicit forced cleanup is requested.

## Releases

Release preparation is submitted from `release/<version>` and merged before tagging. Create the GitHub release from the merged `main` commit. If the stable AUR archive checksum depends on the published release asset, submit it afterward through a second `release/<version>-packaging` pull request. Tags and AUR metadata must not be finalized from an unmerged branch.
