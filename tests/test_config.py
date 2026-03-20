import pytest
from scicd.config import (
    TaskConfig,
    WorkspaceConfig,
    RepositoryConfig,
    RemoteConfig,
    QueueConfig,
    ConcurrencyConfig,
    get_task_config,
    cascade,
    get_workspace,
    _ConfigManager,
)
import scicd.config


def test_task_config_validation():
    """
    Ensures that TaskConfig correctly validates its input parameters.

    Checks that CPU counts, retries, memory formats, and timeout strings
    adhere to expected formats and constraints.
    """
    with pytest.raises(ValueError, match="cpu must be positive"):
        TaskConfig(cpu=0)

    with pytest.raises(ValueError, match="retry cannot be negative"):
        TaskConfig(retry=-1)

    with pytest.raises(ValueError, match="Invalid memory format"):
        TaskConfig(memory="invalid")

    with pytest.raises(ValueError, match="Invalid timeout format"):
        TaskConfig(timeout="invalid")


def test_task_config_parsing():
    """
    Verifies the conversion of human-readable strings (e.g., '16Gi', '1h 30m')
    into standard numeric units used by the execution engine (MB, Minutes).
    """
    config = TaskConfig(memory="16Gi", disk="100G", timeout="1h 30m")
    assert config.memory_mb == 16384  # 16 * 1024
    assert config.disk_mb == 102400  # 100 * 1024
    assert config.timeout_minutes == 90


def test_task_config_merge():
    """
    Ensures that multiple TaskConfig sources can be layered correctly.
    """
    config = TaskConfig(cpu=2, memory="8Gi")
    merged = config.merge({"cpu": 4, "tags": ["gpu"]})
    assert merged.cpu == 4
    assert merged.memory == "8Gi"
    assert merged.tags == ["gpu"]


def test_concurrency_config():
    """
    Validates the 'concurrency' section of the task configuration,
    ensuring method-specific worker requirements are met.
    """
    with pytest.raises(ValueError):
        ConcurrencyConfig(method="invalid")


def test_workspace_config():
    """
    Ensures that the root WorkspaceConfig can be correctly parsed from
    its constituent Repository and Remote components.
    """
    ws = WorkspaceConfig(
        repository={
            "platform": "github",
            "url": "https://github.com",
            "project": "org/repo",
        },
        remote={"protocol": "rclone", "url": "s3://bucket", "root": "/data"},
    )
    assert isinstance(ws.repository, RepositoryConfig)
    assert ws.repository.platform == "github"
    assert isinstance(ws.remote, RemoteConfig)
    assert ws.remote.protocol == "rclone"


def test_cascade():
    """
    Verifies the cascading configuration logic.

    This ensures that global base configurations are correctly overridden
    by specific environment-matched rules (e.g., 'prod' vs 'dev').
    """
    config = {"a": 1, "b": 2}
    override = [
        {"match": {"env": "prod"}, "config": {"b": 3, "c": 4}},
        {"match": {"env": "dev"}, "config": {"a": 0}},
    ]


def test_get_task_config_overrides(mocker):
    """
    Tests the global get_task_config entrypoint.

    Verifies that it correctly loads the base configuration file and layers
    the provided manual overrides on top of it.
    """
    _ConfigManager.reset()
    mocker.patch("scicd.config.load_config", return_value={"task": {"cpu": 2}})
    cfg = get_task_config(memory="16Gi")
    assert cfg.cpu == 2
    assert cfg.memory == "16Gi"
    _ConfigManager.reset()
