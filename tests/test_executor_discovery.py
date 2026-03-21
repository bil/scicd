"""
Tests for the executor discovery and registration mechanism.
"""

from scicd.executor import reset_executors, get_executor
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
