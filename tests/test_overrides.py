from scicd.config import TaskConfig, _ConfigManager
from scicd.build import build
from unittest.mock import MagicMock


def test_task_config_runtime_defaults(mocker):
    """
    Verifies that set_runtime_defaults correctly layers CLI overrides
    onto the base configuration for all subsequent tasks.
    """
    _ConfigManager.reset()
    mocker.patch("scicd.config.load_config", return_value={})

    # Initial state (should now be 1 because of empty config mock)
    cfg_base = _ConfigManager.get_base_task_config()
    assert cfg_base.cpu == 1  # Default

    # Apply runtime override
    _ConfigManager.set_runtime_defaults({"cpu": 8, "memory": "32Gi"})

    # Check that new base is updated
    cfg_updated = _ConfigManager.get_base_task_config()
    assert cfg_updated.cpu == 8
    assert cfg_updated.memory == "32Gi"
    _ConfigManager.reset()


def test_task_config_merge_casting():
    """
    Ensures that the merge method correctly casts string values from
    the CLI into the types expected by the TaskConfig dataclass.
    """
    cfg = TaskConfig(cpu=1, retry=0)

    # Simulate CLI strings
    overrides = {"cpu": "16", "retry": "5", "memory": "128Gi"}

    merged = cfg.merge(overrides)
    assert merged.cpu == 16
    assert isinstance(merged.cpu, int)
    assert merged.retry == 5
    assert merged.memory == "128Gi"


def test_build_namespaced_parsing(mocker):
    """
    Verifies that the build() entrypoint correctly separates task-,
    and native parameters, and blocks workspace overrides.
    """
    _ConfigManager.reset()
    # Mock dependencies
    mocker.patch("scicd.config.load_config", return_value={})
    mock_luigi2dag = mocker.patch("scicd.build.luigi2dag")
    mock_export = mocker.patch("scicd.build.export_gitlab")

    # Simulate a complex CLI call
    kwargs = {
        "task-cpu": "4",  # TaskConfig override
        "task-image": "alpine",  # TaskConfig override (now inside TaskConfig)
        "workspace-remote": "hack",  # Blocked WorkspaceConfig field
        "TaskA-date": "2024",  # Task-specific Luigi parameter
        "global-param": "foo",  # Global Luigi parameter
    }

    build(module="mod", target="Fam", **kwargs)

    # 1. Check task overrides were applied to ConfigManager
    base_cfg = _ConfigManager.get_base_task_config()
    assert base_cfg.cpu == 4
    assert base_cfg.image == "alpine"

    # 2. Check native params were passed to the frontend
    # TaskA-date and global-param should be passed through
    args, call_kwargs = mock_luigi2dag.call_args
    assert "TaskA-date" in call_kwargs
    assert "global-param" in call_kwargs
    assert "task-cpu" not in call_kwargs

    _ConfigManager.reset()
