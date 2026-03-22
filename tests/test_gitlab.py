"""
Integration tests for GitLab CI/CD YAML generation and linting.
"""

import json
import shlex

import yaml

from scicd.dag import DAG, BijectNode, SliceNode
from scicd.adapter import BaseAdapter
from scicd.config import TaskConfig, ConcurrencyConfig, WorkspaceConfig
from scicd.backend.gitlab.decode import render_node_gitlab, write_gitlab_yaml
from scicd.slice import generate_child_pipeline_config


class MockAdapter(BaseAdapter):
    """
    A mock adapter to simulate task properties for GitLab YAML generation.
    """

    def __init__(self, name, params, identifier, cfg=None):
        self._name = name
        self._params = params
        self._identifier = identifier
        self._cfg = cfg or TaskConfig(cpu=2)
        super().__init__(None)

    @property
    def name(self):
        return self._name

    @property
    def params(self):
        return self._params

    @property
    def cfg(self):
        return self._cfg

    @property
    def params_json(self):
        return json.dumps(self.params)

    @property
    def command(self):
        return ["scicd", "run", "--module", "mod", "--target", self.name]

    @property
    def identifier(self):
        return self._identifier


def test_gitlab_yml_lint_and_json_params(tmp_path):
    """
    Verifies the syntactic validity and parameter integrity of generated GitLab YAML.

    This test:
    1. Generates a .gitlab-ci.yml file from a BijectNode.
    2. Uses PyYAML to load and lint the generated file.
    3. Asserts that task parameters are passed via the SCICD_PARAMS env var.
    """
    adapter = MockAdapter("MyTask", {"id": 123}, "MyTask_123")
    node = BijectNode(work=[adapter], rank=0, node_deps=[])
    dag = DAG([node])

    out_file = tmp_path / ".gitlab-ci.yml"
    write_gitlab_yaml(dag, filepath=str(out_file), image="python:3.10")

    # Lint: Check if it's valid YAML
    with open(out_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    assert config["image"] == "python:3.10"
    assert "MyTask_123" in config

    # env var Validation: Assert that SCICD_PARAMS in variables is valid JSON
    variables = config["MyTask_123"]["variables"]
    assert "SCICD_PARAMS" in variables
    json_str = variables["SCICD_PARAMS"]

    params = json.loads(json_str)
    assert params["id"] == 123


def test_slice_node_child_yml_generation():
    """
    Verifies that SliceNode correctly generates child pipeline configurations.

    This test confirms that:
    1. The parent pipeline contains a generator job with the correct scicd.slice command.
    2. The scicd.slice logic generates a valid child YAML configuration.
    3. The child configuration correctly implements GitLab's parallel execution schema.
    """
    # Mock SliceNode config
    wspace = WorkspaceConfig()
    cfg = TaskConfig(concurrency=ConcurrencyConfig(method="slice", workers=5))
    adapter1 = MockAdapter("Task", {"id": 1}, "Task_1", cfg=cfg)
    adapter2 = MockAdapter("Task", {"id": 2}, "Task_2", cfg=cfg)

    node = SliceNode(work=[adapter1, adapter2], rank=0, node_deps=[])
    jobs = render_node_gitlab(node)

    # The first job is the generator
    gen_job_id = next(k for k in jobs[0].keys())
    gen_job = jobs[0][gen_job_id]
    gen_script = gen_job["script"][0]

    assert "scicd.slice generate" in gen_script
    assert "SCICD_COMMANDS_JSON" in gen_job["variables"]
    assert "SCICD_CFG_JSON" in gen_job["variables"]
    assert "SCICD_GITLAB_INFO_JSON" in gen_job["variables"]

    # Now test the generation logic itself from scicd.slice

    child_yml = generate_child_pipeline_config(
        target="Task",
        manifest_path="manifest.yml",
        cfg=cfg,
        wspace=wspace,
        gitlab_info={"image": "python:3.10"},
        gen_id=gen_job_id,
    )

    # 3. Assert child YML is valid GitLab schema (basic check)
    assert child_yml["stages"] == ["execute"]
    assert "Task_worker" in child_yml
    worker = child_yml["Task_worker"]
    assert worker["parallel"] == 5
    assert worker["needs"][0]["job"] == gen_job_id

    # Verify we can dump it back to YAML
    yaml_str = yaml.dump(child_yml)
    reloaded = yaml.safe_load(yaml_str)
    assert reloaded == child_yml
