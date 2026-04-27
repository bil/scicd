"""
Utilities for path management and remote sync.
"""

import shlex
import os
from typing import Optional
from pathlib import Path

from scicd.config import WorkspaceConfig, get_workspace_config


def get_relpath(path: str | Path, config_path: str):
    path = Path(path)
    wspace = get_workspace_config(config_path)
    if wspace.data_root:
        path = str(path.relative_to(os.path.expandvars(wspace.data_root)))
    else:
        path = str(path)
    return path


def rclone_commands(
    files: list[str],
    data_root: str,
    remote_root: str,
    flags: Optional[str] = None,
    direction: str = "pull",
) -> list[str]:
    if not files:
        return []
    includes = " ".join(
        [f"--filter {shlex.quote(f'+ {f}')}" for f in sorted(files)]
    )
    cmd = "rclone copy"
    if direction == "pull":
        cmd += f' "{remote_root}" "{data_root}"'
    elif direction == "push":
        cmd += f' "{data_root}" "{remote_root}"'
    cmd += f" --no-traverse --filter {shlex.quote('+ **/')} {includes} --filter {shlex.quote('- *')}"
    if flags:
        cmd += f" {flags}"
    return [cmd]


def remote_commands(
    files: list[str], wspace: WorkspaceConfig, direction: str = "pull"
) -> list[str]:
    data_root = wspace.data_root
    remote_root = wspace.remote_root
    if data_root is None or remote_root is None:
        return []
    if remote_root.startswith("rclone://"):
        remote_root = remote_root.replace("rclone://", "")
        remote_flags = wspace.remote_flags
        return rclone_commands(
            files,
            data_root,
            remote_root,
            flags=remote_flags,
            direction=direction,
        )
    else:
        raise NotImplementedError
