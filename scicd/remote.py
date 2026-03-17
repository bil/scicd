import os
import subprocess
import tempfile
from pathlib import Path
from typing import List

import requests
import scicd.config


def push(files: List[Path]) -> bool:
    """Generic push for a list of local files."""
    wspace = scicd.config.get_workspace()
    protocol = getattr(wspace, "remote_protocol", "rclone")

    if protocol == "rclone":
        return _rclone_push_pull(wspace, files, direction="push")
    elif protocol == "https":
        return _https_push_pull(wspace, files, direction="push")
    return False


def pull(files: List[Path]) -> bool:
    """Generic pull for a list of local files."""
    wspace = scicd.config.get_workspace()
    protocol = getattr(wspace, "remote_protocol", "rclone")

    if protocol == "rclone":
        return _rclone_push_pull(wspace, files, direction="pull")
    elif protocol == "https":
        return _https_push_pull(wspace, files, direction="pull")
    return False


def _https_push_pull(
    wspace: scicd.config.WorkspaceConfig, files: List[Path], direction="push"
) -> bool:
    """HTTPS implementation using requests Session for connection pooling."""
    if not files or not wspace.path_remote:
        return True

    local_root = Path(wspace.path_output)
    base_url = wspace.path_remote.rstrip("/")

    # Use a session to reuse the TCP connection for multiple files
    with requests.Session() as session:
        # Add auth if your workspace config provides it
        if wspace.https_header:
            session.headers.update(wspace.https_header)

        for local_p in files:
            try:
                rel_path = local_p.relative_to(local_root)
                url = f"{base_url}/{rel_path}"

                if direction == "push":
                    if not local_p.exists():
                        continue
                    with open(local_p, "rb") as f:
                        # We use PUT here as it's the standard for 'copyto' behavior
                        response = session.put(url, data=f)
                        response.raise_for_status()
                else:
                    # Direction is PULL
                    response = session.get(url, stream=True)
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


def _rclone_push_pull(
    wspace: scicd.config.WorkspaceConfig, files: List[Path], direction="push"
) -> bool:
    # ... (Your existing rclone logic stays exactly the same) ...
    if not files or not wspace.path_remote:
        return True

    flags = " ".join(wspace.rclone_flags)
    local_root = Path(wspace.path_output)
    remote_root = Path(wspace.path_remote)

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
