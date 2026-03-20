import luigi
from pathlib import Path

from scicd.task import (
    HashTask,
    _ensure_output_dirs,
    _checkpoint_task,
    _pull_inputs_on_start,
    _push_outputs_on_success,
)


class MyMockTask(HashTask):
    param = luigi.Parameter()

    @property
    def path(self):
        return "my_path"

    def output(self):
        return luigi.LocalTarget(str(self.output_path / f"out_{self.param}.txt"))


def test_hash_task_properties(mocker):
    """
    Verifies the fundamental properties of a HashTask.

    Checks that output paths are correctly derived from the workspace root
    and that fingerprints include code commit, parameters, and configuration.
    """
    mocker.patch("scicd.task.get_git_commit", return_value="abc1234")
    mocker.patch("scicd.task.cascading_config", return_value={"window": 5})

    mock_ws = mocker.MagicMock()
    mock_ws.remote.root = "/tmp/root"
    mocker.patch("scicd.task.get_workspace", return_value=mock_ws)

    task = MyMockTask(param="test")

    assert str(task.output_path) == "/tmp/root/my_path"
    assert task.cfg.window == 5

    fp = task.get_fingerprint()
    assert len(fp) == 12


def test_hash_task_complete(mocker, tmp_path):
    """
    Verifies the fingerprint-based completion logic of HashTask.

    A task is only considered complete if:
    1. The output file exists.
    2. A corresponding fingerprint file exists.
    3. The fingerprint file content matches the current task hash.
    """
    # Mock commit for fingerprint
    mocker.patch("scicd.task.get_git_commit", return_value="abc1234")
    # Mock config for fingerprint
    mocker.patch("scicd.task.cascading_config", return_value={"window": 5})

    mock_ws = mocker.MagicMock()
    mock_ws.remote.root = str(tmp_path)
    mocker.patch("scicd.task.get_workspace", return_value=mock_ws)

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


def test_event_handlers(mocker, tmp_path):
    """
    Verifies that task event handlers perform their side effects correctly.

    - _ensure_output_dirs must create the parent directories for outputs.
    - _checkpoint_task must write the fingerprint file upon success.
    """
    # Test _ensure_output_dirs
    mock_ws = mocker.MagicMock()
    mock_ws.remote.root = str(tmp_path)
    mocker.patch("scicd.task.get_workspace", return_value=mock_ws)

    task = MyMockTask(param="handler_test")

    _ensure_output_dirs(task)
    out_file = Path(task.output().path)
    assert out_file.parent.exists()

    # Test _checkpoint_task
    mocker.patch("scicd.task.get_git_commit", return_value="abc1234")
    mocker.patch("scicd.task.cascading_config", return_value={})

    _checkpoint_task(task)
    fp_file = out_file.parent / ".luigi_fingerprints" / f"{out_file.name}.fingerprint"
    assert fp_file.exists()
    assert fp_file.read_text() == task.get_fingerprint()


def test_global_pull_push(mocker):
    """
    Verifies the global pull/push triggers for generic Luigi tasks.

    Ensures that when remote syncing is enabled, any task entering START
    will trigger a pull of its inputs, and any task reaching SUCCESS
    will trigger a push of its outputs.
    """
    mock_ws = mocker.MagicMock()
    mock_ws.remote.pull_inputs = True
    mock_ws.remote.push_outputs = True
    mocker.patch("scicd.task.get_workspace", return_value=mock_ws)

    mock_pull = mocker.patch("scicd.remote.pull")
    mock_push = mocker.patch("scicd.remote.push")

    class DummyTask(luigi.Task):
        def input(self):
            return luigi.LocalTarget("in.txt")

        def output(self):
            return luigi.LocalTarget("out.txt")

    task = DummyTask()

    _pull_inputs_on_start(task)
    mock_pull.assert_called_once()

    _push_outputs_on_success(task)
    mock_push.assert_called_once()
