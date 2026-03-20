import luigi
from pathlib import Path
from scicd.task import HashTask
from scicd.build import luigi2dag
from scicd.dag import BijectNode


class ExternalInput(luigi.ExternalTask):
    id = luigi.IntParameter()
    base_path = luigi.Parameter(default=".")

    def output(self):
        return luigi.LocalTarget(str(Path(self.base_path) / f"external_{self.id}.txt"))


class LeafTask(HashTask):
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


class RootTask(HashTask):
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


def test_luigi_lifecycle_and_events(mocker, tmp_path):
    """
    Verifies that the full Luigi execution lifecycle correctly triggers SciCD events.
    
    This test runs a real Luigi task tree and asserts that:
    1. _pull_inputs_on_start is triggered (mock_pull).
    2. _push_outputs_on_success is triggered (mock_push).
    3. Output files and their corresponding fingerprints are created in the workspace.
    """
    mocker.patch("scicd.config.load_config", return_value={})
    import scicd.config

    scicd.config.reset_config()
    # Mock workspace and git
    mock_ws = mocker.MagicMock()
    mock_ws.remote.root = str(tmp_path)
    mock_ws.remote.pull_inputs = True
    mock_ws.remote.push_outputs = True
    mocker.patch("scicd.task.get_workspace", return_value=mock_ws)
    mocker.patch("scicd.task.get_git_commit", return_value="abc1234")

    # Mock remote actions
    mock_pull = mocker.patch("scicd.remote.pull")
    mock_push = mocker.patch("scicd.remote.push")

    # Create the external inputs so tasks can run
    (tmp_path / "external_0.txt").write_text("input0")
    (tmp_path / "external_1.txt").write_text("input1")

    # Run the root task
    task = RootTask(base_path=str(tmp_path))
    success = luigi.build([task], local_scheduler=True, workers=1)
    assert success

    # Verify events:
    # Root + 2 Leaves = 3 tasks.
    # Each Leaf pulls its ExternalInput.
    # Root pulls the 2 Leaf outputs.
    assert mock_pull.call_count == 3
    assert mock_push.call_count == 3
    # Verify outputs and fingerprints
    assert (tmp_path / "root" / "done.txt").exists()
    assert (tmp_path / "root" / ".luigi_fingerprints" / "done.txt.fingerprint").exists()


def test_luigi_dag_resolution(mocker):
    """
    Verifies that a Luigi task tree is correctly converted into an abstract SciCD DAG.
    
    This test mocks the Luigi module loading and command-line parsing to simulate
    loading a 'RootTask'. It then asserts that the resulting DAG has the expected
    number of nodes, topological ranks, and parent-child dependencies.
    """
    mocker.patch("scicd.config.load_config", return_value={})
    import scicd.config

    scicd.config.reset_config()
    # Mock importlib.import_module
    mocker.patch("importlib.import_module")

    # Mock the CmdlineParser context manager and its return value
    mock_cp = mocker.MagicMock()
    mock_cp.get_task_obj.return_value = RootTask()

    # Patch the global_instance context manager
    mocker.patch(
        "luigi.cmdline_parser.CmdlineParser.global_instance",
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
