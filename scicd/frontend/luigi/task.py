"""Luigi task augmentation factory for SciCD."""

import hashlib
import json
from functools import cached_property
from pathlib import Path
from typing import Any, Type, TypeVar, cast

import luigi
import rich

import scicd.config
import scicd.remote
from scicd.config import DynamicModel
from scicd.git import get_git_commit
from scicd.yamler import deep_update, nest_dict

T = TypeVar("T", bound=luigi.Task)


def _normalize_luigi_resources(resources: dict[str, Any]) -> dict[str, Any]:
    """Normalize Luigi resources() dict to TaskConfig format."""
    normalized: dict[str, Any] = {}

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
    """Extract and resolve TaskConfig for a Luigi task instance."""
    overrides: dict[str, Any] = {}

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


def augment_task(
    cls: Type[T], hash_cfg: bool = True, hash_commit: bool = True
) -> Type[T]:
    """Augment a Luigi task class with SciCD features (sync, pathing, fingerprinting)."""

    class Task(cls):
        """Internal augmented class."""

        hashed = hash_cfg
        hashed_commit = hash_commit

        scicd_local = luigi.BoolParameter(
            default=False,
            significant=False,
            parsing=luigi.BoolParameter.EXPLICIT_PARSING,
            description="Disable SciCD remote sync for local execution.",
        )

        @cached_property
        def workspace(self):
            """Get global WorkspaceConfig."""
            return scicd.config.get_workspace()

        @cached_property
        def task_config(self):
            """Get resolved TaskConfig for this task."""
            return get_task_config(self)

        @property
        def path(self) -> str:
            """Return subpath for task outputs."""
            return ""

        @cached_property
        def output_path(self) -> Path:
            """Return workspace-anchored base directory for task outputs."""
            base_dir = "."
            if self.task_config.remote and self.task_config.remote.root:
                base_dir = self.task_config.remote.total_root

            subpath = self.path

            return Path(base_dir) / str(subpath)

        @cached_property
        def cfg_dict(self) -> dict[str, Any]:
            """Return dict of cascading configuration parameters."""
            user_cfg = self.task_config.user
            path_cascade = getattr(user_cfg, "path_cascade", None)

            if not path_cascade:
                return {}

            return scicd.config.cascading_config(
                path_cascade, root_key=[self.get_task_family()], **self.param_kwargs
            )

        @cached_property
        def cfg(self) -> DynamicModel:
            """Return DynamicModel wrapper for cascading configuration."""
            return DynamicModel.model_validate(self.cfg_dict)

        def get_fingerprint(self) -> str:
            """Generate deterministic hash of task state."""
            data = {
                "params": self.param_kwargs,
                "config": self.cfg_dict,
            }
            if self.hashed_commit:
                data["commit"] = get_git_commit()

            # Deterministic JSON dump using Pydantic's optimized logic
            dump = DynamicModel.model_validate(data).model_dump_json()
            return hashlib.sha256(dump.encode()).hexdigest()[:12]

        def _check_fingerprints(self) -> bool:
            """Verify existence and validity of all output fingerprints."""
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
            """Perform local completion check with optional remote pull."""
            # Perform standard check first
            is_complete = super().complete()
            if is_complete:
                if not self.hashed:
                    rich.print(
                        f"[bold green]SciCD:[/bold green] Task [cyan]{self.task_id}[/cyan] detected as complete (local files)."
                    )
                    return True

                if self._check_fingerprints():
                    rich.print(
                        f"[bold green]SciCD:[/bold green] Task [cyan]{self.task_id}[/cyan] detected as complete (local files + valid fingerprint)."
                    )
                    return True

                rich.print(
                    f"[bold yellow]SciCD:[/bold yellow] Task [cyan]{self.task_id}[/cyan] local files exist, but fingerprint is invalid/missing."
                )

            # Remote check: If missing locally, try to pull from remote
            if (
                self.task_config.remote
                and self.task_config.remote.pull_inputs
                and not self.scicd_local
            ):
                outputs = luigi.task.flatten(self.output())
                files_to_pull = [Path(ot.path) for ot in outputs if hasattr(ot, "path")]

                if self.hashed:
                    fp_files = []
                    for p in files_to_pull:
                        fp_files.append(
                            p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"
                        )
                    files_to_pull.extend(fp_files)
                if files_to_pull:
                    rich.print(
                        f"[bold blue]SciCD:[/bold blue] Task [cyan]{self.task_id}[/cyan] outputs missing locally. Attempting to pull from remote..."
                    )
                    for f in files_to_pull:
                        rich.print(f"  -> [dim]{f}[/dim]")
                    if scicd.remote.pull(*files_to_pull):
                        # Re-verify everything after the pull
                        if self.hashed:
                            if self._check_fingerprints():
                                rich.print(
                                    f"[bold green]SciCD:[/bold green] Successfully pulled and verified outputs for [cyan]{self.task_id}[/cyan]."
                                )
                                return True
                            else:
                                rich.print(
                                    f"[bold yellow]SciCD:[/bold yellow] Pulled outputs for [cyan]{self.task_id}[/cyan], but fingerprints do not match current code/config state."
                                )
                                return False

                        is_complete_now = super().complete()
                        if is_complete_now:
                            rich.print(
                                f"[bold green]SciCD:[/bold green] Successfully pulled outputs for [cyan]{self.task_id}[/cyan]."
                            )
                        return is_complete_now

            return False

    # =========================================================================
    # INTERNAL EVENT REGISTRATION
    # =========================================================================

    @Task.event_handler(luigi.Event.START)
    def _scicd_on_start(task):
        """Prepare local environment before task execution."""
        rich.print(
            f"[bold blue]SciCD:[/bold blue] Starting execution for [cyan]{task.task_id}[/cyan]"
        )
        # Ensure output directories exist
        for target in luigi.task.flatten(task.output()):
            if hasattr(target, "path"):
                Path(target.path).parent.mkdir(parents=True, exist_ok=True)

    @Task.event_handler(luigi.Event.SUCCESS)
    def _scicd_on_success(task):
        """Execute checkpointing and remote push upon task success."""
        rich.print(
            f"[bold green]SciCD:[/bold green] Task [cyan]{task.task_id}[/cyan] completed successfully."
        )
        if task.hashed:
            current_fp = task.get_fingerprint()
            rich.print(
                f"[bold blue]SciCD:[/bold blue] Saved fingerprint [green]{current_fp}[/green] for [cyan]{task.task_id}[/cyan]."
            )
            for ot in luigi.task.flatten(task.output()):
                if hasattr(ot, "path"):
                    p = Path(ot.path)
                    fp_dir = p.parent / ".luigi_fingerprints"
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
                rich.print(
                    f"[bold blue]SciCD:[/bold blue] Pushing {len(files_to_push)} items to remote for [cyan]{task.task_id}[/cyan]..."
                )
                for f in files_to_push:
                    rich.print(f"  -> [dim]{f}[/dim]")
                scicd.remote.push(*files_to_push)
        else:
            rich.print(
                f"[bold yellow]SciCD:[/bold yellow] Skipping push for [cyan]{task.task_id}[/cyan] (local execution or push_outputs=False)."
            )

    # Preserve metadata
    Task.__name__ = cls.__name__
    Task.__module__ = cls.__module__
    Task.__doc__ = cls.__doc__

    return cast(Type[T], Task)


# Standard export
AutoTask = augment_task(luigi.Task, hash_cfg=False)
SciTask = augment_task(luigi.Task, hash_cfg=True, hash_commit=False)
DevTask = augment_task(luigi.Task, hash_cfg=True, hash_commit=True)
