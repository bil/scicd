"""
Luigi task augmentation factory for SciCD.
"""

import hashlib
import json
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Type, TypeVar, cast

import luigi

import scicd.config
import scicd.remote
from scicd.git import get_git_commit
from scicd.yamler import deep_update, nest_dict

T = TypeVar("T", bound=luigi.Task)


def _normalize_luigi_resources(resources: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize Luigi's resources() dict to SciCD TaskConfig format.
    """
    normalized: Dict[str, Any] = {}

    # CPU: direct pass-through (integer = cores)
    if "cpu" in resources:
        normalized["cpu"] = int(resources["cpu"])

    # Memory: assume MB if integer, pass through if string
    for mem_key in ["memory", "disk"]:
        if mem_key in resources:
            mem = resources[mem_key]
            # Assume megabytes
            normalized[mem_key] = f"{int(mem)}Mi"

    # Time/Timeout: assume minutes if integer, pass through if string
    for time_key in ["time", "timeout"]:
        if time_key in resources:
            time_val = resources[time_key]
            # Assume minutes
            normalized["timeout"] = f"{int(time_val)}m"

    # GPU: direct pass-through if present
    if "gpu" in resources:
        normalized["gpu"] = int(resources["gpu"])

    return normalized


def get_task_config(task: luigi.Task) -> "scicd.config.TaskConfig":
    """Extract task-specific configuration for a Luigi task instance."""
    overrides: Dict[str, Any] = {}

    # Luigi native resources()
    resources = getattr(task, "resources", {})
    if callable(resources):
        try:
            resources = resources()
        except TypeError:
            pass
    resources = nest_dict(resources)  # expand dot notation

    if isinstance(resources, dict):
        overrides = deep_update(overrides, _normalize_luigi_resources(resources))

    if task.retry_count:
        overrides["retry"] = int(task.retry_count)
    if task.worker_timeout:  # in seconds
        overrides["timeout"] = scicd.config.TaskConfig.validate_time(
            int(task.worker_timeout / 60)
        )

    # `scicd` dict attribute (highest priority)
    if hasattr(task, "scicd"):
        scicd_attr = getattr(task, "scicd")
        if isinstance(scicd_attr, dict):
            scicd_attr = nest_dict(scicd_attr)
            overrides = deep_update(overrides, scicd_attr)

    return scicd.config.get_task_config(**overrides)


def generate_scitask(cls: Type[T], hashed: bool = True) -> Type[T]:
    """
    Class factory that augments a standard Luigi task with SciCD features.

    Features injected:
    1. Standardized 'output_path' property anchored to workspace root.
    2. 'complete()' override that attempts to pull missing outputs from remote.
    3. Self-contained event handlers for directory creation and remote pushing.
    4. (Optional) Fingerprint-based completion checks (default: True).

    Args:
        cls: The base Luigi task class to augment.
        hashed: If True, enables content-based fingerprinting.

    Returns:
        A new class inheriting from 'cls' with SciCD capabilities.
    """

    class Task(cls):
        """Internal augmented class."""

        _is_hashed = hashed

        scicd_local = luigi.BoolParameter(
            default=False,
            significant=False,
            parsing=luigi.BoolParameter.EXPLICIT_PARSING,
            description="Disable SciCD remote sync for local execution.",
        )

        @cached_property
        def workspace(self):
            """Global workspace configuration."""
            return scicd.config.get_workspace()

        @cached_property
        def task_config(self):
            """Task configuration with overrides."""
            return get_task_config(self)

        @property
        def path(self) -> str:
            """
            Subpath for task outputs.
            Override this or the 'path' method in your task.
            """
            return ""

        @cached_property
        def output_path(self) -> Path:
            """Standardized base directory for task outputs."""
            base_dir = "."
            if self.task_config.remote and self.task_config.remote.root:
                base_dir = self.task_config.remote.root

            subpath = self.path

            return Path(base_dir) / str(subpath)

        @cached_property
        def cfg_dict(self) -> Dict[str, Any]:
            """Raw dictionary of 'insignificant' parameters from YAML/TOML."""
            user_cfg = self.task_config.user
            cascade_path = (
                user_cfg.get("cascade_path")
                if isinstance(user_cfg, dict)
                else getattr(user_cfg, "cascade_path", None)
            )

            if not cascade_path:
                return {}

            return scicd.config.cascading_config(
                cascade_path, root_key=[self.get_task_family()], **self.param_kwargs
            )

        @cached_property
        def cfg(self) -> Any:
            """Dot-access wrapper for configuration."""
            return SimpleNamespace(**self.cfg_dict)

        def get_fingerprint(self) -> str:
            """Unique hash of code version, params, and config."""
            data = {
                "commit": get_git_commit(),
                "params": self.param_kwargs,
                "config": self.cfg_dict,
            }
            dump = json.dumps(data, sort_keys=True)
            return hashlib.sha256(dump.encode()).hexdigest()[:12]

        def _check_fingerprints(self) -> bool:
            """Verify all outputs have valid fingerprints matching current state."""
            outputs = luigi.task.flatten(self.output())
            current_fp = self.get_fingerprint()
            for ot in outputs:
                if hasattr(ot, "path"):
                    p = Path(ot.path)
                    fp_file = p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"
                    if (
                        not p.exists()
                        or not fp_file.exists()
                        or fp_file.read_text(encoding="utf-8").strip() != current_fp
                    ):
                        return False
            return True

        def complete(self) -> bool:
            """
            Augmented completion check with self-healing (auto-pull).
            """
            # 1. Perform standard local check first
            is_complete = super().complete()
            if is_complete:
                if not hashed or self._check_fingerprints():
                    return True

            # 2. Remote check: If missing locally, try to pull from remote
            if (
                self.task_config.remote
                and self.task_config.remote.pull_inputs
                and not self.scicd_local
            ):
                outputs = luigi.task.flatten(self.output())
                files_to_pull = [Path(ot.path) for ot in outputs if hasattr(ot, "path")]

                if hashed:
                    fp_files = []
                    for p in files_to_pull:
                        fp_files.append(
                            p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"
                        )
                    files_to_pull.extend(fp_files)
                if files_to_pull:
                    if scicd.remote.pull(*files_to_pull):
                        # Re-verify everything after the pull
                        if hashed:
                            return self._check_fingerprints()
                        return super().complete()

            return False

    # =========================================================================
    # INTERNAL EVENT REGISTRATION
    # =========================================================================

    @Task.event_handler(luigi.Event.START)
    def _scicd_on_start(task):
        """Prepare environment before task runs."""
        # Ensure output directories exist
        for target in luigi.task.flatten(task.output()):
            if hasattr(target, "path"):
                Path(target.path).parent.mkdir(parents=True, exist_ok=True)

    @Task.event_handler(luigi.Event.SUCCESS)
    def _scicd_on_success(task):
        """Handle checkpointing and remote pushing."""
        # If hashed, save the fingerprint first
        if hashed:
            current_fp = task.get_fingerprint()
            for ot in luigi.task.flatten(task.output()):
                if hasattr(ot, "path"):
                    p = Path(ot.path)
                    fp_dir = p.parent / ".luigi_fingerprints"
                    print(fp_dir / f"{p.name}.fingerprint")
                    fp_dir.mkdir(parents=True, exist_ok=True)
                    (fp_dir / f"{p.name}.fingerprint").write_text(
                        current_fp, encoding="utf-8"
                    )

        # Push to remote if enabled
        if (
            task.task_config.remote
            and task.task_config.remote.push_outputs
            and not getattr(task, "scicd_local", False)
        ):
            outputs = luigi.task.flatten(task.output())
            files_to_push = []
            for ot in outputs:
                if hasattr(ot, "path"):
                    p = Path(ot.path)
                    files_to_push.append(p)
                    # Also push the fingerprint if it exists
                    fp_file = p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"
                    if fp_file.exists():
                        files_to_push.append(fp_file)

            if files_to_push:
                scicd.remote.push(*files_to_push)

    # Preserve metadata
    Task.__name__ = cls.__name__
    Task.__module__ = cls.__module__
    Task.__doc__ = cls.__doc__

    return cast(Type[T], Task)


# Standard export
SciTask = generate_scitask(luigi.Task, hashed=True)
