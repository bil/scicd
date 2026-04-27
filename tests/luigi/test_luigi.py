"""
Tests for the LuigiAdapter class
"""

import json
import luigi
import scicd.config
from scicd.frontend.luigi import LuigiAdapter
from scicd.config import TaskConfig


class DummyTask(luigi.Task):
    """
    A dummy Luigi task used for testing property extraction and configuration overrides.
    """

    date = luigi.Parameter()

    @property
    def resources(self):
        return {"cpu": 4, "memory": 8192, "time": 90}

    scicd = {"memory": "64Gi", "tags": ["slurm"]}

    def output(self):
        return [luigi.LocalTarget("file1.txt"), luigi.LocalTarget("file2.txt")]


def test_luigi_adapter_properties(mocker):
    """
    Verifies that LuigiAdapter correctly extracts properties and configurations from a Luigi Task.

    This includes checking the task name, parameters, and the transformation of
    Luigi resources/scicd dict into a validated TaskConfig object.
    """
    mocker.patch("scicd.config.load_config", return_value={})
    task = DummyTask(date="2024-01-01")
    adapter = LuigiAdapter(task)

    assert adapter.name == "DummyTask"
    assert adapter.params.model_dump() == {"date": "2024-01-01"}
    assert "file1.txt" in adapter.outputs
    assert "file2.txt" in adapter.outputs
    assert not adapter.inputs
    assert not adapter.deps

    # Check config generation
    cfg = adapter.cfg
    assert isinstance(cfg, TaskConfig)
    assert cfg.cpu == 4
    # The scicd dict overrides resources() dict
    assert cfg.memory == "64Gi"
    assert cfg.max_duration == "90m"
    assert cfg.tags == ["slurm"]
