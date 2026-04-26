"""
Git repository utilities for SciCD.

This module provides helpers for retrieving the current branch name and commit hash,
supporting both local development and various CI/CD environments.
"""

import os
import subprocess


def get_branch() -> str:
    """
    Identify the current git branch.

    Checks the 'CI_COMMIT_REF_NAME' environment variable before falling back
    to the local 'git branch' command.

    Returns:
        The branch name string, or 'unknown' if not in a git repository.
    """
    if "CI_COMMIT_REF_NAME" in os.environ:
        return os.environ["CI_COMMIT_REF_NAME"]
    try:
        return subprocess.check_output(
            ["git", "branch", "--show-current"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def get_git_commit() -> str:
    """
    Retrieve the current git commit hash.

    Checks CI environment variables (GitLab SHA or GitHub SHA) first,
    then falls back to 'git rev-parse HEAD'.

    Returns:
        The 40-character commit hash string, or "unknown" if no git info exists.
    """
    # Check common CI environment variables first
    ci_commit = os.environ.get("CI_COMMIT_SHA") or os.environ.get("GITHUB_SHA")
    if ci_commit:
        return ci_commit

    # Run git command locally
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
