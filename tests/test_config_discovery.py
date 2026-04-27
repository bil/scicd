"""
Tests for the configuration file discovery logic.
"""

import pytest
from scicd.config import find_config_path, get_workspace_config


def test_find_config_path_env_var(tmp_path, monkeypatch):
    """Priority 1: Verify SCICD_CONFIG_PATH env var is used if it exists."""
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    config_file = custom_dir / "my_config.yaml"
    config_file.write_text("task: {cpu: 4}", encoding="utf-8")

    monkeypatch.setenv("SCICD_CONFIG_PATH", str(config_file))

    path = find_config_path()
    assert path.resolve() == config_file.resolve()


def test_find_config_path_root_yaml(tmp_path, monkeypatch):
    """Priority 2: Verify root scicd.yaml is used if no env var is set."""
    # Ensure no env var
    monkeypatch.delenv("SCICD_CONFIG_PATH", raising=False)

    # Change to temp directory
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / "scicd.yaml"
    config_file.write_text("task: {cpu: 2}", encoding="utf-8")

    path = find_config_path()
    assert path.name == "scicd.yaml"


def test_find_config_path_nested(tmp_path, monkeypatch):
    """Priority 3: Verify .scicd/config.yaml is used if root doesn't exist."""
    monkeypatch.delenv("SCICD_CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    dot_scicd = tmp_path / ".scicd"
    dot_scicd.mkdir()
    config_file = dot_scicd / "config.yaml"
    config_file.write_text("task: {cpu: 1}", encoding="utf-8")

    path = find_config_path()
    assert path.parts[-2:] == (".scicd", "config.yaml")


def test_find_config_path_not_found(tmp_path, monkeypatch):
    """Verify FileNotFoundError is raised if no config files are found."""
    monkeypatch.delenv("SCICD_CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    assert find_config_path() is None


def test_config_discovery(tmp_path, monkeypatch):
    """Verify that _ConfigManager actually uses the discovery logic."""
    monkeypatch.delenv("SCICD_CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / "scicd.yaml"
    config_file.write_text("workspace: {url: x, project: y}", encoding="utf-8")

    ws = get_workspace_config()
    assert ws.url == "x"
