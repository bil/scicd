"""
Tests for the executor discovery and registration mechanism.
"""

import pytest
from scicd.executor import (
    register_executor,
    get_executor,
    reset_executors,
    _ExecutorRegistry,
)
from scicd.config import TaskConfig


def test_executor_discovery_env_var(tmp_path, monkeypatch):
    """Verify SCICD_EXECUTORS_PATH env var is used if it exists."""
    reset_executors()

    custom_dir = tmp_path / "custom_execs"
    custom_dir.mkdir()
    exec_file = custom_dir / "my_execs.py"
    exec_file.write_text(
        """
from scicd.executor import register_executor
@register_executor(tags=["custom_tag"])
def my_func(cfg):
    return {"CUSTOM_VAR": "found"}
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("SCICD_EXECUTORS_PATH", str(exec_file))

    # This should trigger discovery
    executor = get_executor(["custom_tag"])
    assert executor.name == "my_func"

    config = TaskConfig()
    assert executor.func(config) == {"CUSTOM_VAR": "found"}

    reset_executors()


def test_tag_matching():
    """Verify that executors only match if ALL tags are present and exact."""
    reset_executors()
    # Mock loaded state to prevent disk discovery during unit tests
    _ExecutorRegistry._loaded = True

    @register_executor(tags=["gpu", "high_mem"])
    def gpu_exec(cfg):
        return {"EXEC": "gpu"}

    executor = get_executor(["gpu", "high_mem"])
    assert executor.name == "gpu_exec"
    executor = get_executor(["gpu"])
    assert executor.name == "gpu_exec"

    # Superset match (should fail now)
    with pytest.raises(
        ValueError, match="No executor found matching or supersetting"
    ):
        get_executor(["gpu", "high_mem", "extra"])

    # Different order (should pass because frozenset is unordered)
    exec = get_executor(["high_mem", "gpu"])
    assert exec.name == "gpu_exec"

    reset_executors()


def test_executor_func_call_with_config():
    """Verify that executor functions receive a valid TaskConfig."""
    reset_executors()
    _ExecutorRegistry._loaded = True

    @register_executor(tags=["test"])
    def test_exec(cfg):
        return {"CPU": str(cfg.cpu)}

    executor = get_executor(["test"])
    config = TaskConfig(cpu=4)

    result = executor.func(config)
    assert result == {"CPU": "4"}

    reset_executors()
