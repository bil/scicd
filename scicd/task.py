"""
Luigi tasks for SciCD pipeline.
"""
import json
import hashlib
from functools import cached_property
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Dict

import luigi

import scicd.remote
from scicd.config import cascading_config, get_workspace
from scicd.git import get_git_commit


class HashTask(luigi.Task):
    """
    Augmented luigi task, with cascading configuration and hash-based completion checks.
    """

    @property
    def path(self) -> str:
        """
        The task-specific subpath.
        This is a suffix on the workspace path_output configuration.
        Override this in child classes.
        """
        return ""

    @cached_property
    def output_path(self) -> Path:
        """The base directory for this task's outputs."""
        if self.workspace.remote and self.workspace.remote.root:
            base_dir = self.workspace.remote.root
        else:
            base_dir = "."
        return Path(base_dir) / self.path

    @cached_property
    def workspace(self):
        """Global workspace configuration (paths, gitlab settings)."""
        return get_workspace()

    @cached_property
    def cfg_dict(self) -> Dict[str, Any]:
        """Raw dictionary of 'insignificant' parameters from YAML/TOML."""
        return cascading_config(self.get_task_family(), **self.param_kwargs)

    @cached_property
    def cfg(self) -> Any:
        """Dot-access wrapper for configuration: self.cfg.savgol_window"""
        return SimpleNamespace(**self.cfg_dict)

    def get_fingerprint(self) -> str:
        """Unique hash of code version, significant params, and config."""
        data = {
            "commit": get_git_commit(),
            "params": self.param_kwargs,
            "config": self.cfg_dict,
        }
        dump = json.dumps(data, sort_keys=True)
        return hashlib.sha256(dump.encode()).hexdigest()[:12]

    def complete(self) -> bool:
        """Modified completion that checks file existence and fingerprint hash."""
        outputs = luigi.task.flatten(self.output())

        current_fp = self.get_fingerprint()
        missing_locally = []

        # Local check
        for ot in outputs:
            if not hasattr(ot, "path"):
                continue
            p = Path(ot.path)
            fp_file = p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"

            # Check if valid fingerprint exists locally
            if (
                not p.exists()
                or not fp_file.exists()
                or fp_file.read_text(encoding="utf-8").strip() != current_fp
            ):
                missing_locally.append(p)
                missing_locally.append(fp_file)

        return not missing_locally


@HashTask.event_handler(luigi.Event.START)
def _ensure_output_dirs(task: HashTask):
    """Just make sure the folders exist before the task writes to them."""
    for target in luigi.task.flatten(task.output()):
        if hasattr(target, "path"):
            Path(target.path).parent.mkdir(parents=True, exist_ok=True)


@HashTask.event_handler(luigi.Event.SUCCESS)
def _checkpoint_task(task: HashTask):
    """Saves fingerprints."""
    current_fp = task.get_fingerprint()
    outputs = luigi.task.flatten(task.output())

    if not outputs:
        return

    for ot in outputs:
        if hasattr(ot, "path"):
            p = Path(ot.path)

            # Local Fingerprint
            fp_dir = p.parent / ".luigi_fingerprints"
            fp_dir.mkdir(parents=True, exist_ok=True)
            fp_file = fp_dir / f"{p.name}.fingerprint"
            fp_file.write_text(current_fp, encoding="utf-8")


@luigi.Task.event_handler(luigi.Event.START)
def _pull_inputs_on_start(task: luigi.Task):
    """Generic global callback to pull inputs before a task starts."""
    wspace = get_workspace()
    if wspace.remote and getattr(wspace.remote, "pull_inputs", False):
        inputs = luigi.task.flatten(task.input())
        files_to_pull = [Path(it.path) for it in inputs if hasattr(it, "path")]
        if files_to_pull:
            scicd.remote.pull(*files_to_pull)


@luigi.Task.event_handler(luigi.Event.SUCCESS)
def _push_outputs_on_success(task: luigi.Task):
    """Generic global callback to push outputs after a task succeeds."""
    wspace = get_workspace()
    if wspace.remote and getattr(wspace.remote, "push_outputs", False):
        outputs = luigi.task.flatten(task.output())
        files_to_archive = []
        for ot in outputs:
            if hasattr(ot, "path"):
                p = Path(ot.path)
                files_to_archive.append(p)
                fp_file = p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"
                if fp_file.exists():
                    files_to_archive.append(fp_file)
        if files_to_archive:
            scicd.remote.push(*files_to_archive)
