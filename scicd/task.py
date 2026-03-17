import json
import hashlib
import luigi
from functools import cached_property
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Dict

from scicd.config import cascading_config, get_workspace
from scicd.git import get_git_commit


class SciCDTask(luigi.Task):
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

    @luigi.Task.event_handler(luigi.Event.START)
    def _ensure_output_dirs(self):
        """
        Automatically creates directories for all outputs,
        but ONLY when the task is actually starting execution.
        """
        for target in luigi.task.flatten(self.output()):
            if hasattr(target, "path"):
                Path(target.path).parent.mkdir(parents=True, exist_ok=True)

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
        """Checks both file existence and SciCD fingerprint validity."""
        if not super().complete():
            return False

        current_fp = self.get_fingerprint()
        for ot in luigi.task.flatten(self.output()):
            if hasattr(ot, "path"):
                p = Path(ot.path)
                fp_file = p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"
                if not fp_file.exists() or fp_file.read_text().strip() != current_fp:
                    return False
        return True

    @luigi.Task.event_handler(luigi.Event.SUCCESS)
    def _save_fingerprints(self):
        """Saves the fingerprint sidecar file after a successful run."""
        current_fp = self.get_fingerprint()
        for ot in luigi.task.flatten(self.output()):
            if hasattr(ot, "path"):
                p = Path(ot.path)
                fp_dir = p.parent / ".luigi_fingerprints"
                fp_dir.mkdir(parents=True, exist_ok=True)
                (fp_dir / f"{p.name}.fingerprint").write_text(current_fp)
