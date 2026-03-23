
import pytest
from scicd.config import intercept_cli_overrides, _ConfigManager, TaskConfig

def test_cli_memory_normalization():
    """Verify that '--memory 16GB' is normalized to '16G' in overrides."""
    _ConfigManager.reset()
    
    cli_args = {"memory": "16GB", "cpu": "4", "other-param": "val"}
    
    # This should store '16G' and '4' (int) in _ConfigManager
    frontend_params = intercept_cli_overrides(cli_args)
    
    overrides = _ConfigManager.get_cli_overrides()
    
    assert overrides["memory"] == "16G"
    assert overrides["cpu"] == 4
    assert frontend_params == {"other-param": "val"}

def test_cli_timeout_normalization():
    """Verify that '--timeout 1h30m' is normalized to '1h 30m'."""
    _ConfigManager.reset()
    
    intercept_cli_overrides({"timeout": "1h30m"})
    overrides = _ConfigManager.get_cli_overrides()
    
    assert overrides["timeout"] == "1h 30m"

def test_cli_nested_overrides():
    """Verify that nested dot-notation is handled and validated."""
    _ConfigManager.reset()
    
    # Cyclopts might pass 'remote-pull-inputs' or we might get 'remote.pull_inputs'
    intercept_cli_overrides({"remote.pull-inputs": "true"})
    overrides = _ConfigManager.get_cli_overrides()
    
    assert overrides["remote"]["pull_inputs"] is True

def test_cli_invalid_override():
    """Verify that invalid inputs (like negative CPU) raise errors."""
    _ConfigManager.reset()
    
    with pytest.raises(Exception):
        intercept_cli_overrides({"cpu": "-1"})
