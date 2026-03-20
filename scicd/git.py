"""
Module docstring.
"""
import os
import subprocess


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


def get_git_commit():
    """
    Returns the current git commit hash.
    Checks Environment Variable first, then falls back to git command.
    """
    # Check common CI environment variables first
    ci_commit = os.environ.get("CI_COMMIT_SHA") or os.environ.get("GITHUB_SHA")
    if ci_commit:
        return ci_commit

    # Run git command locally
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, encoding="utf-8"
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # 3. Final Fallback: Return "unknown" or a timestamp if no git info exists
        return "unknown"
