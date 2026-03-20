import pytest
from scicd.executor import (
    register_executor,
    get_executor,
    reset_executors,
    _ExecutorRegistry,
)
from scicd.config import TaskConfig


def test_strict_tag_matching():
    """Verify that executors only match if ALL tags are present and exact."""
    reset_executors()
    # Mock loaded state to prevent disk discovery during unit tests
    _ExecutorRegistry._loaded = True

    @register_executor(tags=["gpu", "high_mem"])
    def gpu_exec(cfg):
        return {"EXEC": "gpu"}

    # 1. Exact match
    exec = get_executor(["gpu", "high_mem"])
    assert exec.name == "gpu_exec"

    # 2. Subset match (should fail now because of strict matching)
    with pytest.raises(ValueError, match="No executor found matching exactly"):
        get_executor(["gpu"])

    # 3. Superset match (should fail now)
    with pytest.raises(ValueError, match="No executor found matching exactly"):
        get_executor(["gpu", "high_mem", "extra"])

    # 4. Different order (should pass because frozenset is unordered)
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
