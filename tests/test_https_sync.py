"""
Integration tests for HTTPS-based remote storage synchronization.
"""

import os
import json
import threading
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import luigi
import pytest
from scicd.task import SciTask
from scicd.config import WorkspaceConfig, TaskConfig, reset_config

# =============================================================================
# DUMMY HTTP SERVER
# =============================================================================


class MockStorageHandler(BaseHTTPRequestHandler):
    """
    A simple HTTP handler that stores uploaded files in a local temporary folder.
    """

    # This must be set before use
    storage_path = None

    def do_GET(self):
        print("STORAGE: ", self.storage_path)
        rel_path = self.path.lstrip("/")
        print("GETTING REL: ", rel_path)
        full_path = self.storage_path / rel_path
        print("GETTING: ", full_path)

        if full_path.exists() and full_path.is_file():
            print("GOTIT")
            self.send_response(200)
            self.end_headers()
            with open(full_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            print("DID NOT GET IT")
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        content_length = int(self.headers["Content-Length"])
        data = self.rfile.read(content_length)

        rel_path = self.path.lstrip("/")
        full_path = self.storage_path / rel_path

        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)

        self.send_response(201)
        self.end_headers()

    def log_message(self, format, *args):
        return


@pytest.fixture(scope="module")
def http_server(tmp_path_factory):
    """Starts a local HTTP server for testing."""
    remote_dir = tmp_path_factory.mktemp("remote_storage")
    MockStorageHandler.storage_path = remote_dir

    server = HTTPServer(("127.0.0.1", 0), MockStorageHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"http://127.0.0.1:{port}", remote_dir
    server.shutdown()


# =============================================================================
# TEST TASKS
# =============================================================================


class VanillaTask(SciTask):
    """
    A basic SciTask implementation for testing standard output synchronization.
    """

    name = luigi.Parameter()
    out_dir = luigi.Parameter()

    def output(self):
        # Ensure path is absolute and within the workspace root
        return luigi.LocalTarget(str(Path(self.out_dir) / f"{self.name}.txt"))

    def run(self):
        with self.output().open("w") as f:
            f.write(f"content of {self.name}")


class HashedTask(SciTask):
    """
    A SciTask implementation that uses custom output pathing for fingerprint testing.
    """

    name = luigi.Parameter()
    out_dir = luigi.Parameter()

    @property
    def path(self):
        # We handle pathing manually via out_dir for this test
        return ""

    @property
    def output_path(self):
        return Path(self.out_dir)

    def output(self):
        return luigi.LocalTarget(str(self.output_path / f"{self.name}.hashed"))

    def run(self):
        with self.output().open("w") as f:
            f.write(f"content of {self.name} hashed")


# =============================================================================
# TESTS
# =============================================================================


def test_https_push_on_success(mocker, tmp_path, http_server):
    """Verify that tasks push their outputs to HTTPS on success."""
    reset_config()
    server_url, remote_dir = http_server

    ws = WorkspaceConfig(**{"platform": "gitlab", "url": "x", "project": "y"})
    mocker.patch("scicd.config.get_workspace", return_value=ws)
    task_cfg = TaskConfig(
        remote={
            "protocol": "https",
            "url": server_url,
            "root": str(tmp_path),
            "push_outputs": True,
            "pull_inputs": True,
        }
    )
    mocker.patch("scicd.config.get_task_config", return_value=task_cfg)
    mocker.patch("scicd.task.get_git_commit", return_value="abc")

    task = VanillaTask(name="vanilla", out_dir=str(tmp_path))
    success = luigi.build([task], local_scheduler=True)
    assert success

    remote_file = remote_dir / "vanilla.txt"
    assert remote_file.exists()
    assert remote_file.read_text() == "content of vanilla"


def test_https_pull_and_skip(mocker, tmp_path, http_server):
    """Verify pulling from HTTPS and skipping task run."""
    reset_config()
    server_url, remote_dir = http_server

    task_cfg = TaskConfig(
        remote={
            "protocol": "https",
            "url": server_url,
            "root": str(tmp_path),
            "pull_inputs": True,
            "push_outputs": True,
        }
    )
    mocker.patch("scicd.config.get_task_config", return_value=task_cfg)

    task = VanillaTask(name="remote_file", out_dir=str(tmp_path))
    fp = task.get_fingerprint()

    # Pre-populate remote
    # With target file
    target_file = remote_dir / "remote_file.txt"
    if target_file.exists():
        os.remove(target_file)
    target_file.write_text("remote content")
    # And its fingerprint
    fingerprint_file = (
        remote_dir / ".luigi_fingerprints" / "remote_file.txt.fingerprint"
    )
    if fingerprint_file.exists():
        os.remove(fingerprint_file)
    fingerprint_file.write_text(fp)

    # Run a task that requires 'remote_file'
    # The requirement is NOT local, but is on remote.
    spy = mocker.spy(VanillaTask, "run")

    # This should trigger our patched complete(), pull the file, and skip run()
    success = luigi.build([task], local_scheduler=True)
    assert success

    assert (tmp_path / "remote_file.txt").exists()
    assert (tmp_path / "remote_file.txt").read_text() == "remote content"
    assert spy.call_count == 0


def test_https_sync(mocker, tmp_path, http_server):
    """Verify that HashTask syncs fingerprints over HTTPS."""
    reset_config()
    server_url, remote_dir = http_server

    ws = WorkspaceConfig(**{"platform": "gitlab", "url": "x", "project": "y"})
    mocker.patch("scicd.config.get_workspace", return_value=ws)
    task_cfg = TaskConfig(
        remote={
            "protocol": "https",
            "url": server_url,
            "root": str(tmp_path),
            "push_outputs": True,
            "pull_inputs": True,
        }
    )
    mocker.patch("scicd.config.get_task_config", return_value=task_cfg)
    mocker.patch("scicd.task.get_git_commit", return_value="abc")

    # 1. Run HashTask to push to remote
    task = HashedTask(name="secure", out_dir=str(tmp_path))
    luigi.build([task], local_scheduler=True)

    assert (remote_dir / "secure.hashed").exists()
    assert (remote_dir / ".luigi_fingerprints" / "secure.hashed.fingerprint").exists()

    # 2. Clear local data
    (tmp_path / "secure.hashed").unlink()
    shutil.rmtree(tmp_path / ".luigi_fingerprints")

    # 3. Pull and skip run
    spy = mocker.spy(HashedTask, "run")
    luigi.build(
        [HashedTask(name="secure", out_dir=str(tmp_path))], local_scheduler=True
    )

    assert spy.call_count == 0
    assert (tmp_path / "secure.hashed").exists()
