"""
Remote syncing utilities for SciCD.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import requests
import cyclopts
from cyclopts import Parameter

import scicd.config

# Custom groups for cleaner --help output
SURGICAL_GROUP = "Surgical Commands (Used by Tasks)"
GLOBAL_GROUP = "Global Commands (Used by CI/CD)"

app = cyclopts.App(help="SciCD Remote Sync Utility.")


@app.command()
def push(
    *files: Annotated[
        Path,
        Parameter(
            show_default=False,
            help="One or more local file paths to archive to the remote.",
        ),
    ]
) -> bool:
    """
    Push specific local files to the remote archive.

    This is typically called automatically by a task upon successful completion.

    Example:
        python3 -m scicd.remote push results/plot.png results/data.csv
    """
    task_config = scicd.config.get_task_config()
    wspace = scicd.config.get_workspace()
    # Ensure absolute!
    files = [file.resolve() for file in files]

    if not task_config.remote:
        return True

    protocol = task_config.remote.protocol

    if protocol == "rclone":
        return _rclone_batch(task_config, list(files), "push")
    if protocol == "https":
        return _https_batch(task_config, wspace, list(files), "push")

    raise ValueError(f"Unsupported protocol for push: {protocol}")


@app.command()
def pull(
    *files: Annotated[
        Path,
        Parameter(
            show_default=False, help="One or more remote file paths to recover locally."
        ),
    ]
) -> bool:
    """
    Pull specific files from the remote archive to local storage.

    Used for 'Lazy Hydration'—recovering only the upstream dependencies
    needed for a specific task.

    Example:
        python3 -m scicd.remote pull results/raw_data.fits
    """
    task_config = scicd.config.get_task_config()
    wspace = scicd.config.get_workspace()

    if not task_config.remote:
        return True

    protocol = task_config.remote.protocol

    if protocol == "rclone":
        return _rclone_batch(task_config, list(files), "pull")
    if protocol == "https":
        return _https_batch(task_config, wspace, list(files), "pull")

    raise ValueError(f"Unsupported protocol for pull: {protocol}")


@app.command()
def pull_full() -> bool:
    """
    Perform a complete sync (Global Init) from remote to local.

    STRICT REQUIREMENT: This command only supports 'rclone' protocols.
    It is intended for stage_00 of GitLab pipelines to populate the
    persistent storage with existing baseline data.
    """
    task_config = scicd.config.get_task_config()

    if (
        not task_config.remote
        or not task_config.remote.url
        or not task_config.remote.root
    ):
        print("No remote path configured. Skipping pull-full.")
        return True

    protocol = task_config.remote.protocol

    if protocol == "rclone":
        flags = " ".join(task_config.remote.flags)
        cmd = f"rclone copy {task_config.remote.total_url} {task_config.remote.total_root} {flags}"
        subprocess.check_call(cmd, shell=True)
        return True

    raise NotImplementedError(
        f"pull-full is currently only supported for rclone. "
        f"Protocol '{protocol}' requires a manual sync or surgical pulls."
    )


def _https_batch(
    task_config: scicd.config.TaskConfig,
    wspace: scicd.config.WorkspaceConfig,
    files: list[Path],
    direction="push",
) -> bool:
    """HTTPS implementation using requests Session for connection pooling."""
    if (
        not task_config.remote
        or not files
        or not task_config.remote.url
        or not task_config.remote.root
    ):
        return True

    local_root = Path(task_config.remote.total_root)
    base_url = task_config.remote.total_url.rstrip("/")

    # Use a session to reuse the TCP connection for multiple files
    with requests.Session() as session:
        # Add auth if your workspace config provides it
        if getattr(wspace, "https_header", None):
            session.headers.update(getattr(wspace, "https_header"))

        for local_p in files:
            try:
                print(local_p, base_url, local_root)
                rel_path = local_p.relative_to(local_root)
                url = f"{base_url}/{rel_path}"

                if direction == "push":
                    if not local_p.exists():
                        continue
                    with open(local_p, "rb") as f:
                        # We use PUT here as it's the standard for 'copyto' behavior
                        response = session.put(url, data=f, timeout=60)
                        response.raise_for_status()
                else:
                    # Direction is PULL
                    response = session.get(url, stream=True, timeout=60)
                    if response.status_code == 404:
                        return False  # Fail early if a required file is missing
                    response.raise_for_status()

                    local_p.parent.mkdir(parents=True, exist_ok=True)
                    with open(local_p, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)

            except (requests.RequestException, ValueError) as e:
                print(f"HTTPS {direction} failed for {local_p}: {e}")
                return False

    return True


def _rclone_batch(
    task_config: scicd.config.TaskConfig, files: list[Path], direction="push"
) -> bool:
    if (
        not task_config.remote
        or not files
        or not task_config.remote.url
        or not task_config.remote.root
    ):
        return True

    flags = " ".join(task_config.remote.flags)
    local_root = Path(task_config.remote.total_root)
    remote_root = task_config.remote.total_url

    rel_paths = []
    for f in files:
        try:
            rel_paths.append(str(f.relative_to(local_root)))
        except ValueError:
            print(f"{f} not in specified output path {local_root}...")
            continue

    if not rel_paths:
        return True

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
        tmp.write("\n".join(rel_paths))
        tmp_path = tmp.name

    try:
        src, dest = (
            (local_root, remote_root)
            if direction == "push"
            else (remote_root, local_root)
        )
        cmd = f"rclone copy --files-from {tmp_path} {src} {dest} {flags}"
        subprocess.check_call(cmd, shell=True)
        return True
    except subprocess.CalledProcessError:
        return False
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
