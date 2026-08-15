# Agent Workflow

These rules apply to every automated coding agent working in this repository.

## Main is a control checkout

- Never edit, commit, or push from the `main` branch.
- Treat the primary checkout at `~/Projects/thpm` as a read-only control workspace used to fetch, inspect, create worktrees, and clean them up.
- If a task starts on `main`, stop before modifying files. Create a task branch and worktree with `scripts/agent-worktree.sh create <slug>`, then continue in the path it prints.
- Do not bypass repository hooks with `--no-verify`.

## One task, one branch, one worktree

- Create every task from the current `origin/main`.
- Use one writer or agent per worktree. Never share a writable worktree between concurrent agents.
- Use concise branch names under an appropriate prefix:
  - `agent/<slug>` for agent-authored maintenance
  - `fix/<slug>` for fixes
  - `feat/<slug>` for features
  - `docs/<slug>` for documentation
  - `release/<version>` for release preparation
- Keep worktrees under `~/Projects/thpm-worktrees/` unless the caller explicitly chooses another location.
- Do not reuse a branch for unrelated work.

## Verification and pull requests

- Follow the development commands in `README.md` and run the checks relevant to the changed files.
- Run the complete `tests/run.sh` suite before declaring a code change ready.
- Commit changes on the task branch, push that branch, and open or update a pull request targeting `main`.
- Open a draft pull request when work needs continued remote visibility; mark it ready only after verification succeeds.
- Include the commands run, their outcomes, and any residual risks in the pull request.
- Agents may not merge or close pull requests. A human owner makes the final merge decision.
- Do not push directly to `main`, force-push protected branches, or delete remote branches manually.

## Cleanup

- Remove a worktree only after its pull request is merged or the task is explicitly abandoned.
- Before removal, check for uncommitted and unpushed work.
- Use `scripts/agent-worktree.sh remove <branch-or-slug>` for normal cleanup.

## Releases

- Release changes follow the same pull-request workflow.
- Merge release preparation before creating a tag. Tags must point to commits already present on `main`.
- Publish release assets from the merged release commit.
- Submit archive checksums and final AUR metadata through a follow-up packaging pull request when the published archive digest is not known before tagging.
