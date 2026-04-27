"""
Tests for the Directed Acyclic Graph (DAG) construction and rendering.
"""

import json
import yaml
from scicd.dag import Node, DAG
from scicd.adapter import BaseAdapter
from scicd.config import TaskConfig, ConcurrencyConfig
from scicd.backend.gitlab import (
    export_node,
    export_dag,
)


class MockAdapter(BaseAdapter):
    """
    A mock adapter for testing DAG node properties and GitLab job generation.
    """

    def __init__(self, name, params, identifier, concurrency="biject"):
        self._name = name
        self._params = params
        self._identifier = identifier
        self._concurrency = concurrency
        super().__init__(None)

    @property
    def params(self) -> TaskConfig:
        from scicd.config import DynamicModel

        return DynamicModel.model_validate(self._params)

    @property
    def cfg(self):
        return TaskConfig(
            cpu=2, concurrency={"method": self._concurrency, "workers": 2}
        )

    @property
    def commands(self):
        return ["echo test"]

    @property
    def deps(self):
        return []

    @property
    def identifier(self):
        return self._identifier

    @property
    def inputs(self):
        return []

    @property
    def outputs(self):
        return []

    @property
    def name(self):
        return self._name

    def run(self):
        pass


def test_biject_properties():
    """
    Verifies that biject concurrency (1:1 task-to-job mapping) correctly handles properties.
    """
    adapter = MockAdapter("MyTask", {"id": 1}, "MyTask_1")
    node = Node(adapters=[adapter], rank=0, deps=[])

    assert node.jobs[0] == "MyTask_1"
    assert node.needs == []


def test_biject_to_gitlab():
    """
    Verifies the conversion of a biject concurrenct to GitLab CI/CD job dictionary.

    Checks that job scripts, stages, and 'needs' dependencies are correctly mapped.
    """
    adapter = MockAdapter("MyTask", {"id": 1}, "MyTask_1")
    dep_adapter = MockAdapter("DepTask", {}, "DepTask_0")

    dep_node = Node(adapters=[dep_adapter], rank=0, deps=[])
    node = Node(adapters=[adapter], rank=1, deps=[dep_node])

    jobs = export_node(node)
    assert len(jobs) == 1
    job = jobs["MyTask_1"]
    assert job["stage"] == "stage_1"
    assert job["script"] == ["echo test"]
    assert job["needs"] == ["DepTask_0"]


def test_slice_properties():
    """
    Verifies properties of slice concurrency (scattered execution).

    Asserts that multiple adapters are correctly grouped.
    """
    adapter1 = MockAdapter("MyTask", {"id": 1}, "MyTask_1", concurrency="slice")
    adapter2 = MockAdapter("MyTask", {"id": 2}, "MyTask_2", concurrency="slice")
    node = Node(adapters=[adapter1, adapter2], rank=1, deps=[])

    assert len(node.jobs) == 2
    assert node.jobs[0].startswith("MyTask")


def test_slice_to_gitlab():
    """
    Verifies the generation of GitLab jobs for slice concurrency.
    """
    adapter1 = MockAdapter("MyTask", {"id": 1}, "MyTask_1", concurrency="slice")
    adapter2 = MockAdapter("MyTask", {"id": 2}, "MyTask_2", concurrency="slice")
    node = Node(adapters=[adapter1, adapter2], rank=0, deps=[])

    jobs = export_node(node)
    assert len(jobs) == 2
    for job in jobs:
        job_dict = jobs[job]
        assert job_dict["stage"] == "stage_0"
        assert job_dict["script"] == ["echo test"]
        assert job_dict["needs"] == []


def test_dag_render_gitlab(tmp_path):
    """
    Verifies the full DAG conversion to a GitLab CI/CD pipeline.

    Asserts that the entire pipeline contains all required jobs,
    correct stages, and global configurations (like the base image).
    """
    adapter1 = MockAdapter("T1", {}, "T1_id")
    node1 = Node(adapters=[adapter1], rank=0, deps=[])

    adapter2 = MockAdapter("T2", {}, "T2_id")
    node2 = Node(adapters=[adapter2], rank=1, deps=[node1])

    dag = DAG([node1, node2])
    out_file = tmp_path / ".gitlab-ci.yml"
    pipeline = export_dag(dag, out_file)
    # make sure produces valid YAML
    with open(out_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    assert pipeline["stages"] == ["stage_0", "stage_1"]
    assert "T1_id" in pipeline
    assert "T2_id" in pipeline


def test_dag_export_dot(tmp_path):
    """
    Verifies that the DAG can be exported to Graphviz DOT format for visualization.
    """
    adapter1 = MockAdapter("T1", {}, "T1_id")
    node1 = Node(adapters=[adapter1], rank=0, deps=[])
    dag = DAG([node1])

    dot_file = tmp_path / "dag.dot"
    dag.export(backend="dot", file_path=dot_file)

    content = dot_file.read_text()
    assert "digraph G {" in content
    assert "T1" in content
