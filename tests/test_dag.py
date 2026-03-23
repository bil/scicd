"""
Tests for the Directed Acyclic Graph (DAG) construction and rendering.
"""

import json
from scicd.dag import BijectNode, SliceNode, DAG
from scicd.adapter import BaseAdapter
from scicd.config import TaskConfig, ConcurrencyConfig
from scicd.backend.gitlab.decode import render_node_gitlab, render_gitlab


class MockAdapter(BaseAdapter):
    """
    A mock adapter for testing DAG node properties and GitLab job generation.
    """

    def __init__(self, name, params, identifier):
        self._name = name
        self._params = params
        self._identifier = identifier
        super().__init__(None)

    @property
    def name(self):
        return self._name

    @property
    def params(self) -> TaskConfig:
        from scicd.config import DynamicModel

        return DynamicModel.model_validate(self._params)

    @property
    def cfg(self):
        return TaskConfig(cpu=2)

    @property
    def command(self):
        return ["echo", "test"]

    @property
    def identifier(self):
        return self._identifier


def test_biject_node_properties():
    """
    Verifies that BijectNode (1:1 task-to-job mapping) correctly handles its properties.

    Ensures that labels, identifiers, and dependencies are correctly
    propagated from the underlying adapter to the node.
    """
    adapter = MockAdapter("MyTask", {"id": 1}, "MyTask_1")
    node = BijectNode(work=[adapter], rank=0, node_deps=[])

    assert node.name == "MyTask"
    assert node.identifier == "MyTask_1"
    assert node.dot_label == "MyTask\\n(id=1)"
    assert node.needs == []


def test_biject_node_to_gitlab():
    """
    Verifies the conversion of a BijectNode into a GitLab CI/CD job dictionary.

    Checks that job scripts, stages, and 'needs' dependencies are correctly mapped.
    """
    adapter = MockAdapter("MyTask", {"id": 1}, "MyTask_1")
    dep_adapter = MockAdapter("DepTask", {}, "DepTask_0")
    dep_node = BijectNode(work=[dep_adapter], rank=0, node_deps=[])

    node = BijectNode(work=[adapter], rank=1, node_deps=[dep_node])

    jobs = render_node_gitlab(node)
    assert len(jobs) == 1
    job = jobs[0]["MyTask_1"]
    assert job["stage"] == "stage_1"
    assert job["script"] == ["echo test"]
    assert job["needs"] == ["DepTask_0"]


def test_slice_node_properties():
    """
    Verifies properties of SliceNode (N:M scattered execution).

    Asserts that multiple adapters are correctly grouped and reflected
    in the node's identifier and DOT label.
    """
    adapter1 = MockAdapter("MyTask", {"id": 1}, "MyTask_1")
    adapter2 = MockAdapter("MyTask", {"id": 2}, "MyTask_2")
    node = SliceNode(work=[adapter1, adapter2], rank=1, node_deps=[])

    assert node.name == "MyTask"
    assert node.identifier == "MyTask_rank1_slice"
    assert "MyTask" in node.dot_label
    assert "[id=1]" in node.dot_label
    assert "[id=2]" in node.dot_label


def test_slice_node_to_gitlab():
    """
    Verifies the generation of GitLab jobs for a SliceNode.

    SliceNodes should generate two jobs:
    1. A 'generator' job that creates the manifest of commands.
    2. A 'trigger' job that kicks off the child pipeline.
    """
    adapter1 = MockAdapter("MyTask", {"id": 1}, "MyTask_1")
    adapter2 = MockAdapter("MyTask", {"id": 2}, "MyTask_2")
    node = SliceNode(work=[adapter1, adapter2], rank=1, node_deps=[])

    jobs = render_node_gitlab(node)
    assert len(jobs) == 2

    gen_id = "MyTask_rank1_gen"
    gen_job = jobs[0][gen_id]
    assert gen_job["stage"] == "stage_1"
    assert "python3 -m scicd.slice generate" in gen_job["script"][0]

    trigger_id = "MyTask_rank1_slice"
    trigger_job = jobs[1][trigger_id]
    assert trigger_job["stage"] == "stage_1"
    assert trigger_job["needs"] == [gen_id]
    assert trigger_job["trigger"]["include"][0]["job"] == gen_id


def test_dag_render_gitlab():
    """
    Verifies the full DAG conversion to a GitLab CI/CD pipeline.

    Asserts that the entire pipeline contains all required jobs,
    correct stages, and global configurations (like the base image).
    """
    adapter1 = MockAdapter("T1", {}, "T1_id")
    node1 = BijectNode(work=[adapter1], rank=0, node_deps=[])

    adapter2 = MockAdapter("T2", {}, "T2_id")
    node2 = BijectNode(work=[adapter2], rank=1, node_deps=[node1])

    dag = DAG([node1, node2])
    pipeline = render_gitlab(dag, image="python:3.9")

    assert pipeline["image"] == "python:3.9"
    assert pipeline["stages"] == ["stage_0", "stage_1"]
    assert "T1_id" in pipeline
    assert "T2_id" in pipeline


def test_dag_export_dot(tmp_path):
    """
    Verifies that the DAG can be exported to Graphviz DOT format for visualization.
    """
    adapter1 = MockAdapter("T1", {}, "T1_id")
    node1 = BijectNode(work=[adapter1], rank=0, node_deps=[])
    dag = DAG([node1])

    dot_file = tmp_path / "dag.dot"
    dag.export_dot(str(dot_file))

    content = dot_file.read_text()
    assert "digraph G {" in content
    assert "T1" in content
