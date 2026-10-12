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

### NixOS development

From inside the task worktree, use its committed `shell.nix` to enter the pinned development environment:

```bash
nix-shell
```

Run the checks above from that shell, or run the complete suite directly:

```bash
nix-shell --run 'tests/run.sh'
```

The shell provides Python, the project's Python dependencies, Bash, and Git, and sets `PYTHONPATH` to the worktree's `src` directory. It does not require enabling flakes or other experimental Nix features. Use this environment rather than an old virtual environment, global dependency installs, or changes to the host configuration. If it cannot start, report the failure instead of silently using a different environment.

Ruff, ShellCheck, and Qt's `qmllint` are not included in the current shell. Run relevant extra checks when those tools are available and record any skipped checks in the pull request. `tests/run.sh` runs QML lint only when `qmllint` is available.

This shell supports development and automated tests on NixOS; it does not turn the host into an Omarchy installation. Live theme hooks, application reloads, and graphical integration behavior still need validation on a supported Omarchy environment. Arch package builds require an Arch packaging environment with `makepkg`. Do not run the source installer merely to prepare a NixOS development checkout.

Keep documentation and pull-request examples generic. Do not publish private hostnames, usernames, absolute local paths, credentials, or unredacted environment and diagnostic dumps.

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
