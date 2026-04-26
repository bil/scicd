"""Remote data synchronization utilities for SciCD."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Optional

import requests


def _resolve(file: str, local_root: str) -> tuple[Path, Path]:
    abs_path = Path(file).resolve()
    rel_path = abs_path.relative_to(local_root)
    return abs_path, rel_path


def https_batch(
    files: list[str],
    url: str,
    direction: Literal["push", "pull"] = "push",
    local_root: Optional[str] = None,  # assume cwd if None
    header: Optional[dict] = None,
) -> bool:
    """Execute HTTPS sync for multiple files using requests.Session."""

    if not local_root:
        local_root = os.getcwd()
    url = url.rstrip("/")

    with requests.Session() as session:
        if header:
            session.headers.update(header)

        for file in files:
            try:
                abs_path, rel_path = _resolve(file, local_root)
            except ValueError:
                print(
                    f"{file} not in specified output path {local_root}, skipping..."
                )
                continue

            try:
                file_url = f"{url}/{rel_path.as_posix()}"  # use forward slashes
                if direction == "push":
                    if not abs_path.exists():
                        print(
                            f"{file} doesn't exist! Can't push... skipping..."
                        )
                        continue
                    with open(abs_path, "rb") as f:
                        response = session.put(file_url, data=f, timeout=3600)
                        response.raise_for_status()
                else:
                    response = session.get(file_url, stream=True, timeout=3600)
                    if response.status_code == 404:
                        return False
                    response.raise_for_status()

                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with tempfile.NamedTemporaryFile(
                            dir=abs_path.parent,
                            prefix=abs_path.name + ".",
                            suffix=".tmp",
                            delete=False,
                        ) as tmp:
                            tmp_name = tmp.name
                            for chunk in response.iter_content(chunk_size=8192):
                                tmp.write(chunk)
                        os.replace(tmp_name, abs_path)
                    except Exception:
                        if "tmp_name" in locals() and os.path.exists(tmp_name):
                            os.remove(tmp_name)
                        raise

            except (requests.RequestException, ValueError) as e:
                print(f"HTTPS {direction} failed for {abs_path}: {e}")
                return False

    return True


def rclone_batch(
    files: list[str],
    url: str,
    direction: Literal["push", "pull"] = "push",
    local_root: Optional[str] = None,  # assume cwd if None
    flags: Optional[list] = None,
) -> bool:
    """Execute rclone sync using --files-from for batching."""

    if not local_root:
        local_root = os.getcwd()

    if not flags:
        flags = []

    rel_paths: list[str] = []
    for file in files:
        try:
            _, rel_path = _resolve(file, local_root)
            rel_paths.append(str(rel_path))
        except ValueError:
            print(
                f"{file} not in specified output path {local_root}, skipping..."
            )
            continue

    if not rel_paths:
        return True

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
        tmp.write("\n".join(rel_paths))
        tmp_path = tmp.name

    try:
        src, dest = (
            (local_root, url) if direction == "push" else (url, local_root)
        )
        cmd = ["rclone", "copy", "--files-from", tmp_path, src, dest, *flags]
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError:
        return False
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
