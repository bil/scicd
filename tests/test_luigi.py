"""
Tests for converting Luigi task trees into SciCD DAGs.
"""

import luigi
from pathlib import Path
from scicd.frontend.luigi.task import SciTask
from scicd.build import luigi2dag
import scicd.config


class ExternalInput(luigi.ExternalTask):
    """
    A mock external Luigi task that provides input files for testing.
    """

    id = luigi.IntParameter()
    base_path = luigi.Parameter(default=".")

    def output(self):
        return luigi.LocalTarget(str(Path(self.base_path) / f"external_{self.id}.txt"))


class LeafTask(SciTask):
    """
    A simple SciTask that depends on an external input.
    """

    id = luigi.IntParameter()
    base_path = luigi.Parameter(default=".")

    def requires(self):
        return ExternalInput(id=self.id, base_path=self.base_path)

    @property
    def path(self):
        return f"leaf_{self.id}"

    def output(self):
        return luigi.LocalTarget(str(self.output_path / "done.txt"))

    def run(self):
        with self.output().open("w") as f:
            f.write("done")


class RootTask(SciTask):
    """
    A SciTask that aggregates multiple leaf tasks into a tree.
    """

    base_path = luigi.Parameter(default=".")

    def requires(self):
        return [LeafTask(id=i, base_path=self.base_path) for i in range(2)]

    @property
    def path(self):
        return "root"

    def output(self):
        return luigi.LocalTarget(str(self.output_path / "done.txt"))

    def run(self):
        with self.output().open("w") as f:
            f.write("done")


def test_luigi_dag_resolution(mocker, tmp_path):
    """
    Verifies that a Luigi task tree is correctly converted into an abstract SciCD DAG.

    This test mocks the Luigi module loading and command-line parsing to simulate
    loading a 'RootTask'. It then asserts that the resulting DAG has the expected
    number of nodes, topological ranks, and parent-child dependencies.
    """
    mocker.patch("scicd.config.load_config", return_value={})

    scicd.config.reset_config()
    # Mock importlib.import_module
    mocker.patch("importlib.import_module")
    # Patch the CmdlineParser in the scicd.frontend.luigi.encode namespace
    mocker.patch("scicd.frontend.luigi.encode.CmdlineParser._attempt_load_module")

    # Mock the CmdlineParser context manager and its return value
    mock_cp = mocker.MagicMock()
    # Provide a real base_path to avoid MagicMock in file paths
    mock_cp.get_task_obj.return_value = RootTask(base_path=str(tmp_path))

    # Patch the global_instance context manager in the encode namespace
    mocker.patch(
        "scicd.frontend.luigi.encode.CmdlineParser.global_instance",
        return_value=mocker.MagicMock(__enter__=lambda s: mock_cp),
    )

    dag = luigi2dag(module="dummy", target="RootTask")

    # RootTask (Rank 2) -> LeafTask (Rank 1) -> ExternalInput (Rank 0)
    # Total nodes: 1 + 2 + 2 = 5
    assert len(dag.nodes) == 5

    root_node = next(n for n in dag.nodes if n.name == "RootTask")
    assert root_node.rank == 2

    leaf_nodes = [n for n in dag.nodes if n.name == "LeafTask"]
    assert len(leaf_nodes) == 2
    assert all(n.rank == 1 for n in leaf_nodes)
    assert all(ln in root_node.node_deps for ln in leaf_nodes)
