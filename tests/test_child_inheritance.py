import json
from scicd.config import (
    TaskConfig,
    ConcurrencyConfig,
    WorkspaceConfig,
    set_base_task,
    reset_config,
)
from scicd.dag import SliceNode
from scicd.adapter import BaseAdapter
from scicd.backend.gitlab.decode import render_node_gitlab
from scicd.slice import generate_child_pipeline_config
import scicd.config


class MockAdapter(BaseAdapter):
    def __init__(self, name, cfg):
        self._name = name
        self._cfg = cfg
        super().__init__(None)

    @property
    def name(self):
        return self._name

    @property
    def cfg(self):
        return self._cfg

    @property
    def params(self):
        return {}

    @property
    def command(self):
        return ["echo", "hello"]

    @property
    def identifier(self):
        return self._name


def test_child_pipeline_inheritance():
    reset_config()
    # Setup workspace with boilerplate
    workspace = scicd.config.get_workspace()
    workspace.cicd = {
        "default": {"image": "global-image:latest"},
        "variables": {"GLOBAL_VAR": "value"},
    }

    cfg = TaskConfig(concurrency=ConcurrencyConfig(method="slice", workers=2))
    adapter = MockAdapter("MyTask", cfg)
    node = SliceNode(work=[adapter], rank=0, node_deps=[])

    # 1. Render parent jobs
    jobs = render_node_gitlab(node)
    gen_job_id = next(k for k in jobs[0].keys())

    # The generator command should contain the boilerplate in gitlab-info-json
    # We can't easily check the JSON string here, so we test generate_child_pipeline_config directly
    # as it's called by the generator job in the real CI.

    # Simulate the data passed to the generator
    gitlab_info = {
        "default": {"image": "global-image:latest"},
        "variables": {"GLOBAL_VAR": "value"},
        "timeout": "60m",
    }

    child_yml = generate_child_pipeline_config(
        target="MyTask",
        manifest_path="manifest.yml",
        cfg=cfg,
        wspace=workspace,
        gitlab_info=gitlab_info,
        gen_id=gen_job_id,
    )

    # Assertions
    assert child_yml["default"] == {"image": "global-image:latest"}
    assert child_yml["variables"] == {"GLOBAL_VAR": "value"}
    assert "MyTask_worker" in child_yml
    worker = child_yml["MyTask_worker"]
    assert worker["timeout"] == "60m"
    # Ensure timeout was popped from root but remains in worker if it was there
    assert "timeout" not in child_yml
