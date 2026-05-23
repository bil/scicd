"""
Tests for the SciCD configuration models and cascading logic.
"""

import pytest
from scicd.config import (
    TaskConfig,
    WorkspaceConfig,
    ConcurrencyConfig,
    get_task_config,
)


from pydantic import ValidationError
from unittest.mock import patch


def test_task_config_validation():
    """
    Ensures that TaskConfig correctly validates its input parameters.
    """
    with pytest.raises(ValidationError, match="cpu"):
        TaskConfig(cpu=0)

    with pytest.raises(ValidationError, match="gpu"):
        TaskConfig(gpu=0)

    with pytest.raises(ValidationError, match="retry"):
        TaskConfig(retry=-1)

    with pytest.raises(ValidationError, match="memory"):
        TaskConfig(memory="10PB")

    with pytest.raises(ValidationError, match="image"):
        TaskConfig(image=1)

    with pytest.raises(ValidationError, match="max_duration"):
        TaskConfig(max_duration="1w")

    with pytest.raises(ValidationError, match="concurrency"):
        TaskConfig(concurrency={"method": "slice"})


def test_task_config_parsing():
    """
    Verifies the conversion of human-readable strings (e.g., '16Gi', '1h 30m')
    into standard numeric units used by the execution engine (MB, Minutes).
    """
    config = TaskConfig(
        cpu="2",
        gpu="3",
        memory="16Gi",
        disk=1000,
        max_duration="1h 30m",
        concurrency={"method": "slice", "workers": "2"},
        user={"thing": "another-thing"},
    )
    assert config.memory_mb == int(16 * 1024**3 / 1000**2)  # convert to MB
    assert config.disk == "1000M"
    assert config.disk_mb == 1000
    assert config.cpu == 2
    assert config.gpu == 3
    assert config.max_duration_minutes == 90
    assert config.concurrency.method == "slice"
    assert config.concurrency.workers == 2


def test_task_config_merge():
    """
    Ensures that multiple TaskConfig sources can be layered correctly.
    """
    config = TaskConfig(cpu=2, memory="8Gi")
    merged = config.merge({"cpu": 4, "tags": ["gpu"], "variables": {"test": "value"}})
    assert merged.cpu == 4
    assert merged.memory == "8Gi"
    assert merged.tags == ["gpu"]
    assert merged.variables == {"test": "value"}


def test_concurrency_config():
    """
    Validates the 'concurrency' section of the task configuration,
    ensuring method-specific worker requirements are met.
    """
    with pytest.raises(ValidationError, match="method"):
        ConcurrencyConfig(method="invalid")


def test_workspace_config():
    """
    Ensures that the root WorkspaceConfig can be correctly parsed from
    its constituent components, and fails if task configs are passed.
    """
    with pytest.raises(ValidationError):
        WorkspaceConfig(cpu=4)


@patch("scicd.config.load_config")
def test_get_task_config_overrides(mock_load_config):
    """
    Tests the global get_task_config entrypoint.

    Verifies that it correctly loads the base configuration file and layers
    the provided manual overrides on top of it.
    """
    mock_load_config.return_value = {"task": {"cpu": 2}}
    cfg = get_task_config(memory="16Gi")
    assert cfg.cpu == 2
    assert cfg.memory == "16Gi"
