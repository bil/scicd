"""
Tests for the LuigiAdapter class, which bridges Luigi tasks and scicd's configuration.
"""

import json
import luigi
import scicd.config
from scicd.frontend.luigi.encode import LuigiAdapter
from scicd.config import TaskConfig


class DummyTask(luigi.Task):
    """
    A dummy Luigi task used for testing property extraction and configuration overrides.
    """

    date = luigi.Parameter()

    def resources(self):
        return {"cpu": 4, "memory": 8192, "time": 90}

    scicd = {"memory": "64Gi", "tags": ["slurm"]}


def test_luigi_adapter_properties(mocker):
    """
    Verifies that LuigiAdapter correctly extracts properties and configurations from a Luigi Task.

    This includes checking the task name, parameters, and the transformation of
    Luigi resources/scicd dict into a validated TaskConfig object.
    """
    mocker.patch("scicd.config.load_config", return_value={})
    scicd.config.reset_config()
    task = DummyTask(date="2024-01-01")
    adapter = LuigiAdapter(task)

    assert adapter.name == "DummyTask"
    assert adapter.params == {"date": "2024-01-01"}

    # Check config generation
    cfg = adapter.cfg
    assert isinstance(cfg, TaskConfig)
    assert cfg.cpu == 4
    # The scicd dict overrides resources() dict
    assert cfg.memory == "64Gi"
    assert cfg.timeout == "90m"
    assert cfg.tags == ["slurm"]


def test_luigi_adapter_command():
    """
    Asserts that the adapter generates the correct 'scicd run' shell command.

    It verifies that the command includes the necessary module, family,
    frontend flag, and correctly serialized JSON parameters.
    """
    task = DummyTask(date="2024-01-01")
    adapter = LuigiAdapter(task)
    cmd = adapter.command

    assert cmd[0] == "scicd"
    assert cmd[1] == "run"
    assert "--module" in cmd
    assert "--family" in cmd
    assert "DummyTask" in cmd
    assert "--frontend" in cmd
    assert "luigi" in cmd

    # check that params is a valid json string
    params_idx = cmd.index("--params") + 1
    # Strip the single quotes around the json string
    params_str = cmd[params_idx].strip("'")
    params_dict = json.loads(params_str)
    assert params_dict == {"date": "2024-01-01"}


def test_luigi_adapter_identifier():
    """
    Verifies that the adapter generates a unique and stable identifier for the task.

    The identifier is used as the GitLab job name and must be <= 64 characters.
    """
    task = DummyTask(date="2024-01-01")
    adapter = LuigiAdapter(task)
    # The identifier should contain the class name and parameter
    assert "DummyTask" in adapter.identifier
    assert "2024" in adapter.identifier
    assert len(adapter.identifier) <= 64


class SimpleTask(luigi.Task):
    """
    A minimal Luigi task with no resource definitions, used for default value testing.
    """


def test_luigi_adapter_no_resources(mocker):
    """
    Ensures that the adapter provides sensible defaults when a Task has no resource definitions.
    """
    mocker.patch("scicd.config.load_config", return_value={})
    scicd.config.reset_config()
    task = SimpleTask()
    adapter = LuigiAdapter(task)
    cfg = adapter.cfg
    assert cfg.cpu == 1  # Base config default
    assert cfg.memory == "8Gi"  # Base config default
