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

## Local package testing

Run `scripts/local-arch-package.sh` to package the exact current working tree without creating a release or publishing to AUR. Pass `--install` to install that artifact through pacman. Then synchronize user-owned generated files and the graphical manager:

```bash
thpm reconcile --refresh
thpm ui install
```

The default local package release is `99`, making it visibly distinct from the published package. Rebuild the published package with `yay -S thpm --rebuild` to roll back.

## Integration certification

Use the live-test scripts and certification procedure documented in [`docs/integration-support.md`](docs/integration-support.md). `scripts/zellij-live-test.sh` applies the checkout's Zellij adapter in an isolated XDG sandbox, opens a real themed session, switches its colors while running, and verifies restoration. Use `--no-launch` for a non-interactive lifecycle check or `--keep` to retain the restored sandbox.

## Releases

Release preparation is submitted from `release/<version>` and merged before tagging. Source updates follow stable GitHub releases and require matching `thpm-<version>.tar.gz` and `thpm-<version>.tar.gz.sha256` assets.

Before merging release preparation, run:

```bash
python scripts/verify-release.py metadata
```

After the merged commit is tagged, `scripts/release-assets.sh` verifies the clean tag, version, release notes, Python, QML, templates, and package metadata before producing release assets. Create the GitHub release only from that merged `main` commit.

The stable and VCS AUR submission trees live under `packaging/aur/thpm` and `packaging/aur/thpm-git`. After publishing the tagged archive, update the stable package SHA-256 and the VCS package `pkgver`, regenerate both `.SRCINFO` files with `makepkg --printsrcinfo`, and run:

```bash
python scripts/verify-release.py packaging <archive> <archive.sha256>
```

Submit archive checksums and final AUR metadata through a follow-up `release/<version>-packaging` pull request when the published archive digest was not known before tagging. Tags and AUR metadata must not be finalized from an unmerged branch. Keep `SKIP` only for the VCS package.
