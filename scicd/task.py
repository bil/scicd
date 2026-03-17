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


class Autotask(luigi.Task):
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
        return Path(self.workspace.path_output) / self.path

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
        """Modified completion that checks file existence and fingerprint hash"""
        wspace = self.workspace
        if not super().complete():
            return False

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
                or fp_file.read_text().strip() != current_fp
            ):
                missing_locally.append(p)
                missing_locally.append(fp_file)

        if not missing_locally:
            return True

        # Optional remote check
        # If enabled, try to pull the missing pieces
        if wspace.remote_completion_enabled and wspace.path_remote:
            if scicd.remote.pull(*missing_locally):
                for ot in outputs:
                    p = Path(ot.path)
                    f_p = p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"
                    if not f_p.exists() or f_p.read_text().strip() != current_fp:
                        return False
                print(
                    f"Pulled {missing_locally} from {wspace.path_remote}",
                    f"to confirm {self.task_family} completion",
                )
                return True

        return False


@Autotask.event_handler(luigi.Event.START)
def _ensure_output_dirs(task: Autotask):
    """Just make sure the folders exist before the task writes to them."""
    for target in luigi.task.flatten(task.output()):
        if hasattr(target, "path"):
            Path(target.path).parent.mkdir(parents=True, exist_ok=True)


@Autotask.event_handler(luigi.Event.SUCCESS)
def _checkpoint_task(task: Autotask):
    """Saves fingerprints and archives outputs."""
    wspace = task.workspace
    current_fp = task.get_fingerprint()
    outputs = luigi.task.flatten(task.output())

    if not outputs:
        return

    files_to_archive = []

    for ot in outputs:
        if hasattr(ot, "path"):
            p = Path(ot.path)

            # Local Fingerprint
            fp_dir = p.parent / ".luigi_fingerprints"
            fp_dir.mkdir(parents=True, exist_ok=True)
            fp_file = fp_dir / f"{p.name}.fingerprint"
            fp_file.write_text(current_fp)

            # Add to batch list
            files_to_archive.append(p)
            files_to_archive.append(fp_file)

    # Remote Push (if configured)
    if wspace.remote_push_enabled and wspace.path_remote and files_to_archive:
        print(
            f"Pushing {files_to_archive} to {wspace.path_remote} after {task.task_family} completion."
        )
        scicd.remote.push(*files_to_archive)
