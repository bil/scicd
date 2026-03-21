import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import scicd.remote
from scicd.config import WorkspaceConfig, TaskConfig, RemoteConfig


def test_remote_pull_full_rclone(mocker):
    """
    Verifies that the global full-sync command correctly calls rclone.

    This test ensures that 'scicd.remote pull-full' properly translates the
    WorkspaceConfig into a valid system-level 'rclone copy' command.
    """
    ws = WorkspaceConfig(
        **{"platform": "gitlab", "url": "x", "project": "y"},
    )
    mocker.patch("scicd.config.get_workspace", return_value=ws)
    task_config = TaskConfig(
        remote={
            "protocol": "rclone",
            "url": "s3://bucket",
            "root": "/data",
            "flags": ["--verbose"],
        },
    )
    mocker.patch("scicd.config.get_task_config", return_value=task_config)
    mock_sub = mocker.patch("subprocess.check_call")

    assert scicd.remote.pull_full() is True
    mock_sub.assert_called_once_with(
        "rclone copy s3://bucket /data --verbose", shell=True
    )


def test_remote_pull_full_unsupported(mocker):
    """
    Verifies that pull-full fails gracefully for unsupported protocols.

    Currently, complete directory synchronization is only implemented for rclone.
    HTTPS protocols are limited to surgical, file-by-file pulls.
    """
    ws = WorkspaceConfig(
        **{"platform": "gitlab", "url": "x", "project": "y"},
    )
    mocker.patch("scicd.config.get_workspace", return_value=ws)
    task_config = TaskConfig(
        remote={"protocol": "https", "url": "http://example.com", "root": "/data"},
    )
    mocker.patch("scicd.config.get_task_config", return_value=task_config)

    with pytest.raises(NotImplementedError):
        scicd.remote.pull_full()


def test_remote_push_rclone(mocker):
    """
    Verifies surgical file-by-file pushes via rclone.

    This test asserts that when multiple files are pushed, SciCD correctly
    filters those that belong to the workspace root and passes them to
    rclone via the --files-from manifest protocol.
    """
    ws = WorkspaceConfig(
        **{"platform": "gitlab", "url": "x", "project": "y"},
    )
    mocker.patch("scicd.config.get_workspace", return_value=ws)
    task_config = TaskConfig(
        remote={"protocol": "rclone", "url": "s3://bucket", "root": "/data"},
    )
    mocker.patch("scicd.config.get_task_config", return_value=task_config)
    mock_sub = mocker.patch("subprocess.check_call")

    # Pass a path that is within /data
    f_path = Path("/data/file.txt")
    assert scicd.remote.push(f_path) is True

    # Check that subprocess was called with something looking like rclone copy --files-from
    args, kwargs = mock_sub.call_args
    cmd = args[0]
    assert cmd.startswith("rclone copy --files-from")
    assert "/data s3://bucket" in cmd


def test_remote_push_out_of_root(mocker):
    """Verify that files outside the workspace root are NOT pushed."""
    ws = WorkspaceConfig(
        **{"platform": "gitlab", "url": "x", "project": "y"},
    )
    mocker.patch("scicd.config.get_workspace", return_value=ws)
    task_config = TaskConfig(
        remote={"protocol": "rclone", "url": "s3://bucket", "root": "/data"},
    )
    mocker.patch("scicd.config.get_task_config", return_value=task_config)
    mock_sub = mocker.patch("subprocess.check_call")

    # Path outside /data
    out_path = Path("/tmp/outside.txt")

    # This should return True (no error) but NOT call subprocess
    assert scicd.remote.push(out_path) is True
    assert mock_sub.call_count == 0


def test_remote_pull_https(mocker, tmp_path):
    """
    Verifies surgical file-by-file pulls via the HTTPS protocol.

    This test mocks a web session and asserts that:
    1. Requests are made to the correct REST API endpoint (URL mapping).
    2. Downloaded content is correctly streamed and written to the local filesystem.
    """
    root_dir = tmp_path / "data"
    root_dir.mkdir()

    ws = WorkspaceConfig(
        **{"platform": "gitlab", "url": "x", "project": "y"},
    )
    mocker.patch("scicd.config.get_workspace", return_value=ws)
    task_config = TaskConfig(
        remote={
            "protocol": "https",
            "url": "http://example.com",
            "root": str(root_dir),
        },
    )
    mocker.patch("scicd.config.get_task_config", return_value=task_config)

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [b"test"]
    mock_session.get.return_value = mock_resp

    # Using a MagicMock context manager properly
    session_context = MagicMock()
    session_context.__enter__.return_value = mock_session
    mocker.patch("requests.Session", return_value=session_context)

    f_path = root_dir / "file.txt"
    assert scicd.remote.pull(f_path) is True

    mock_session.get.assert_called_once_with(
        "http://example.com/file.txt", stream=True, timeout=60
    )
    assert f_path.read_text() == "test"
