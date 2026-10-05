---
name: azd-worktree
description: Use before running Azure Developer CLI (azd) from a linked Git worktree to store .azure environment state in the main checkout.
---

# Shared azd environments for Git worktrees

Run the adjacent `wire-azd-worktree.py` script before using `azd` from a linked
Git worktree. This keeps azd environment state in the main checkout while azd
continues to provision and deploy source code from the current worktree.

## Workflow

1. Resolve the directory that will be used as the azd project working directory.
2. Locate `wire-azd-worktree.py` beside the loaded `SKILL.md`.
3. Run the script with Python 3.10+:

   ```shell
   python3 /path/to/azd-worktree/wire-azd-worktree.py --cwd /path/to/worktree
   ```

   On Windows, use `python` and Windows-style paths.
4. If the script succeeds, run Azure commands through the `az-azd` skill.
5. If another linked or detached worktree is created later, run this skill for
   that worktree before invoking azd there.

Do not run azd from a linked worktree before completing this wiring step.

## Behavior

The script reads:

- `git rev-parse --git-common-dir`
- `git rev-parse --git-dir`
- `git rev-parse --show-toplevel`

When `--git-dir` identifies a linked worktree, the script:

- Derives the main checkout from the common Git directory.
- Creates `<main-checkout>/.azure` if needed.
- Creates `<worktree-root>/.azure` as a directory symlink to the shared path.
- Accepts an existing symlink when it already targets the shared path.
- Refuses to overwrite an existing file, local directory, or symlink to another
  location.

The script makes no changes when the target is the main checkout or is not a Git
repository.

## Existing worktree-local state

If the worktree already contains a real `.azure` directory, stop and inspect it.
Migrate only the required named environment directories to the main checkout.
Do not automatically merge, move, or delete `.azure`; matching environment names
may refer to different subscriptions or tenants.

Remove a verified, empty worktree-local directory only with the user's approval,
then rerun the script.

## Scope

This skill manages only `.azure` directory linkage. It does not authenticate,
select tenants or subscriptions, create azd environments, provision resources,
or deploy applications. Use the `az-azd` skill for those operations.
