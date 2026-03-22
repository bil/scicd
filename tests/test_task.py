"""
Tests for the core SciTask lifecycle, fingerprinting, and event handlers.
"""

import luigi
from pathlib import Path

import scicd.config
from scicd.frontend.luigi.task import SciTask
from scicd.config import reset_config, TaskConfig


class MyMockTask(SciTask):
    """
    A mock SciTask used for testing properties, completion logic, and event handlers.
    """

    param = luigi.Parameter()

    @property
    def path(self):
        return f"tmp/{self.param}"

    def output(self):
        return luigi.LocalTarget(str(self.output_path / f"out_{self.param}.txt"))


def test_task_properties(mocker, tmp_path):
    """
    Verifies the fundamental properties of a SciTask.

    Checks that output paths are correctly derived from the workspace root
    and that fingerprints include code commit, parameters, and configuration.
    """
    reset_config()
    mocker.patch("scicd.frontend.luigi.task.get_git_commit", return_value="abc1234")
    mocker.patch("scicd.config.cascading_config", return_value={"window": 5})

    task_config = TaskConfig(
        remote={"url": "a-wonderful-splendid-url", "root": str(tmp_path / "root")},
        user={"cascade_path": "an-arbitrary-path"},
    )
    mocker.patch("scicd.frontend.luigi.task.get_task_config", return_value=task_config)

    task = MyMockTask(param="test")

    assert str(task.output_path) == str(tmp_path / "root/tmp/test")
    assert task.cfg.window == 5

    fp = task.get_fingerprint()
    assert len(fp) == 12


def test_task_complete(mocker, tmp_path):
    """
    Verifies the fingerprint-based completion logic of SciTask.
    """
    reset_config()
    # Mock commit for fingerprint
    mocker.patch("scicd.frontend.luigi.task.get_git_commit", return_value="abc1234")
    # Mock config for fingerprint
    mocker.patch("scicd.config.cascading_config", return_value={"window": 5})

    task_config = TaskConfig(
        remote={
            "url": "a-wonderful-splendid-url",
            "root": str(tmp_path / "root"),
            "pull_inputs": False,
        },
        user={"cascade_path": "i-could-write-anything"},
    )

    mocker.patch("scicd.frontend.luigi.task.get_task_config", return_value=task_config)

    task = MyMockTask(param="test_complete")

    # Not complete initially
    assert not task.complete()

    # Create the output file but no fingerprint
    out_file = Path(task.output().path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("data", encoding="utf-8")
    assert not task.complete()

    # Create valid fingerprint
    fp_dir = out_file.parent / ".luigi_fingerprints"
    fp_dir.mkdir(exist_ok=True)
    fp_file = fp_dir / f"{out_file.name}.fingerprint"
    fp_file.write_text(task.get_fingerprint(), encoding="utf-8")

    assert task.complete()


def test_event_handlers_and_sync(mocker, tmp_path):
    """
    Verifies that the factory-generated task event handlers perform their side effects correctly.
    """
    reset_config()

    task_config = TaskConfig(
        remote={
            "url": "a-wonderful-splendid-url",
            "root": str(tmp_path),
            "pull_inputs": False,
            "push_outputs": True,
        },
    )
    mocker.patch("scicd.frontend.luigi.task.get_task_config", return_value=task_config)
    mocker.patch("scicd.frontend.luigi.task.get_git_commit", return_value="abc1234")
    mocker.patch("scicd.config.cascading_config", return_value={})

    task = MyMockTask(param="handler_test")

    # Call the START handler (should create dirs)
    task.trigger_event(luigi.Event.START, task)
    out_file = Path(task.output().path)
    assert out_file.parent.exists()

    # Call the SUCCESS handler (should checkpoint and push)
    mock_push = mocker.patch("scicd.remote.push")
    task.trigger_event(luigi.Event.SUCCESS, task)

    fp_file = out_file.parent / ".luigi_fingerprints" / f"{out_file.name}.fingerprint"

    assert fp_file.exists()
    assert fp_file.read_text() == task.get_fingerprint()
    mock_push.assert_called_once()


def test_centralized_cascading_config(mocker, tmp_path):
    """
    Verifies that HashTask correctly uses a centralized configuration file
    with potentially multi-level nested keys.
    """
    reset_config()
    # Create a centralized config file with nested keys
    cascade_file = tmp_path / "global_params.yaml"
    cascade_file.write_text(
        """
MyMockTask:
    config:
        window: 10
    override:
        - match: { param: "special" }
          config: { window: 99 }
""",
        encoding="utf-8",
    )

    # Mock task_config to point to this file and define the hierarchy
    task_config = TaskConfig(user={"cascade_path": str(cascade_file)})
    # mock_task_config = mocker.MagicMock()
    # mock_task_config.user.cascade_path = str(cascade_file)
    mocker.patch("scicd.frontend.luigi.task.get_task_config", return_value=task_config)
    mocker.patch("scicd.frontend.luigi.task.get_git_commit", return_value="abc")

    # Test lookup from nested central file
    task1 = MyMockTask(param="normal")
    assert task1.cfg.window == 10

    # 4. Test override matching from central file
    task2 = MyMockTask(param="special")
    assert task2.cfg.window == 99


class ExternalInput(luigi.ExternalTask):
    """
    A mock external task for lifecycle integration tests.
    """

    id = luigi.IntParameter()
    base_path = luigi.Parameter(default=".")

    def output(self):
        return luigi.LocalTarget(str(Path(self.base_path) / f"external_{self.id}.txt"))


class LeafTask(SciTask):
    """
    A mock leaf task for lifecycle integration tests.
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
    A mock root task for lifecycle integration tests.
    """

    base_path = luigi.Parameter(default=".")

    def requires(self):
        return [
            LeafTask(id=i, base_path=self.base_path, scicd_local=self.scicd_local)
            for i in range(2)
        ]

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
    """
    mocker.patch("scicd.config.load_config", return_value={})

    scicd.config.reset_config()
    # Mock workspace and git
    task_config = TaskConfig(
        remote={
            "url": "www.monkey-magic.com",
            "root": str(tmp_path),
            "pull_inputs": True,
            "push_outputs": True,
        }
    )

    mocker.patch("scicd.frontend.luigi.task.get_task_config", return_value=task_config)
    mocker.patch("scicd.frontend.luigi.task.get_git_commit", return_value="abc1234")

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

    assert mock_pull.call_count == 3
    assert mock_push.call_count == 3
    assert (tmp_path / "root" / "done.txt").exists()
    assert (tmp_path / "root" / ".luigi_fingerprints" / "done.txt.fingerprint").exists()


def test_local_opts_disable_remote(mocker, tmp_path):
    """
    Ensures that overriding scicd_local disables network calls.
    """

    scicd.config.reset_config()
    mock_task_config = mocker.MagicMock()
    mock_task_config.remote.root = str(tmp_path)
    mock_task_config.remote.pull_inputs = True
    mock_task_config.remote.push_outputs = True
    mocker.patch(
        "scicd.frontend.luigi.task.get_task_config", return_value=mock_task_config
    )
    mocker.patch("scicd.frontend.luigi.task.get_git_commit", return_value="abc1234")

    mock_pull = mocker.patch("scicd.remote.pull")
    mock_push = mocker.patch("scicd.remote.push")

    (tmp_path / "external_0.txt").write_text("input0")
    (tmp_path / "external_1.txt").write_text("input1")

    # Pass scicd_local=True directly to the task
    task = RootTask(base_path=str(tmp_path), scicd_local=True)

    success = luigi.build([task], local_scheduler=True, workers=1)
    assert success
    assert mock_pull.call_count == 0
    assert mock_push.call_count == 0
