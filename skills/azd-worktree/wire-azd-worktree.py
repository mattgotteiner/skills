#!/usr/bin/env python3
"""Link a Git worktree's .azure directory to the main checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def git_output(cwd: Path, *arguments: str) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def is_linked_worktree(git_dir: Path, common_dir: Path) -> bool:
    if git_dir == common_dir:
        return False
    normalized_parts = tuple(part.lower() for part in git_dir.parts)
    return "worktrees" in normalized_parts


def wire_azure_directory(cwd: Path) -> int:
    worktree_root_output = git_output(cwd, "rev-parse", "--show-toplevel")
    git_dir_output = git_output(cwd, "rev-parse", "--path-format=absolute", "--git-dir")
    common_dir_output = git_output(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not worktree_root_output or not git_dir_output or not common_dir_output:
        print(f"No Git repository found at {cwd}; no .azure wiring needed.")
        return 0

    worktree_root = Path(worktree_root_output).resolve()
    git_dir = Path(git_dir_output).resolve()
    common_dir = Path(common_dir_output).resolve()
    if not is_linked_worktree(git_dir, common_dir):
        print(f"{worktree_root} is the main checkout; no .azure wiring needed.")
        return 0

    if common_dir.name != ".git":
        print(
            f"Cannot derive the main checkout from Git common directory {common_dir}. "
            "Expected the common directory to end in .git.",
            file=sys.stderr,
        )
        return 2

    shared_azure_dir = common_dir.parent / ".azure"
    worktree_azure_dir = worktree_root / ".azure"
    shared_azure_dir.mkdir(parents=True, exist_ok=True)

    if worktree_azure_dir.is_symlink():
        if worktree_azure_dir.resolve() == shared_azure_dir.resolve():
            print(f"{worktree_azure_dir} already links to {shared_azure_dir}.")
            return 0
        print(
            f"{worktree_azure_dir} links to {worktree_azure_dir.resolve()}, "
            f"not the main checkout's {shared_azure_dir}. Refusing to overwrite it.",
            file=sys.stderr,
        )
        return 2

    if worktree_azure_dir.exists():
        kind = "directory" if worktree_azure_dir.is_dir() else "file"
        print(
            f"{worktree_azure_dir} already exists as a local {kind}. "
            f"Migrate any required environments to {shared_azure_dir}, then remove the local path "
            "after verifying its contents. Refusing to overwrite it.",
            file=sys.stderr,
        )
        return 2

    try:
        worktree_azure_dir.symlink_to(shared_azure_dir, target_is_directory=True)
    except OSError as error:
        detail = ""
        if os.name == "nt":
            detail = " Enable Windows Developer Mode or run with permission to create directory symlinks."
        print(f"Failed to create {worktree_azure_dir} -> {shared_azure_dir}: {error}.{detail}", file=sys.stderr)
        return 1

    print(f"Linked {worktree_azure_dir} -> {shared_azure_dir}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Share azd environment state with the main Git checkout.")
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Git checkout or subdirectory that azd will use. Defaults to the current directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return wire_azure_directory(args.cwd.resolve())


if __name__ == "__main__":
    sys.exit(main())
