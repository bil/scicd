"""
Unified path resolution engine.
"""

import os
import pathlib
import subprocess

from scicd import config


def module_dir():
    """Returns directory for module YAML files."""
    return config.get_config()["internal"]["module_dir"]


def ci_dir():
    """Returns directory for CI artifacts."""
    return config.get_config()["internal"]["ci_dir"]


def get_branch():
    """Identifies current git branch."""
    if "CI_COMMIT_REF_NAME" in os.environ:
        return os.environ["CI_COMMIT_REF_NAME"]
    try:
        return subprocess.check_output(
            ["git", "branch", "--show-current"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return None


def get_namespace():
    """Resolves project namespace if enabled."""
    cfg = config.get_config()["path"]
    if str(cfg["use_branch"]).lower() != "true":
        return ""

    branch = get_branch()
    if not branch:
        raise RuntimeError(
            "Git branch required for namespace. Set use_branch: false in scicd.yaml."
        )
    return branch


def root():
    """Resolves base local results directory."""
    cfg = config.get_config()["path"]
    return pathlib.Path(cfg["output"]) / get_namespace()


def remote_root():
    """Resolves base remote storage root."""
    cfg = config.get_config()["path"]
    return pathlib.Path(cfg["remote"]) / get_namespace()


def local_path(path):
    """Maps relative path to local project root."""
    return root() / path


def remote_path(path):
    """Maps local path to remote storage location."""
    path_str, root_str = str(path), str(root())
    suffix = (
        path_str.split(root_str, 1)[-1].lstrip("/")
        if root_str in path_str
        else path_str
    )
    return str(remote_root() / suffix)
