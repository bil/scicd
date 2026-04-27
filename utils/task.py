# """Luigi task augmentation factory for SciCD."""

# import hashlib
# import json
# from functools import cached_property
# from pathlib import Path
# from typing import Any, Type, TypeVar, cast, Optional

# import luigi
# import rich
# from pydantic import create_model

# import scicd.config
# import scicd.remote
# from scicd.config import DynamicModel
# from scicd.git import get_git_commit
# from scicd.yamler import deep_merge, nest_dict

# T = TypeVar("T", bound=luigi.Task)


# def augment_task(
#     path_hash: Optional[str] = None,
#     path_cascade: Optional[str] = None,
#     hash_commit: bool = True,
#     name: str = "Task",
# ) -> Type[T]:
#     """
#     Augment a Task with remote sync, cascading config, path parsing, hash-based completion.
#     """

#     _path_hash_arg = path_hash
#     _path_cascade_arg = path_cascade
#     _hash_commit_arg = hash_commit

#     class Task(luigi.Task):
#         """Internal augmented class."""

#         hash_commit = _hash_commit_arg
#         cfg_spec: dict[str, Any] | None = None

#         @cached_property
#         def workspace(self):
#             """Get global WorkspaceConfig."""
#             return scicd.config.get_workspace_config()

#         @cached_property
#         def task_config(self):
#             """Get resolved TaskConfig for this task."""
#             return get_task_config(self)

#         @property
#         def path(self) -> str:
#             """Return subpath for task outputs."""
#             return ""

#         @cached_property
#         def path_output(self) -> Path:
#             """Return workspace-anchored base directory for task outputs."""
#             out = Path(self.task_config.remote.total_root) / str(self.path)
#             return out

#         @cached_property
#         def path_hash(self) -> Path:
#             if not _path_hash_arg:
#                 hashdir = Path(self.path) / ".hash"
#             else:
#                 hashdir = Path(_path_hash_arg)
#             out = (
#                 Path(self.task_config.remote.total_root)
#                 / hashdir
#                 / f"{self.task_id}.sha256"
#             )
#             return out

#         @cached_property
#         def path_cascade(self) -> Path | None:
#             if _path_cascade_arg:
#                 return Path(_path_cascade_arg)
#             return None

#         @cached_property
#         def cfg_dict(self) -> dict[str, Any]:
#             """Return dict of cascading configuration parameters."""
#             if self.path_cascade:
#                 return scicd.config.cascading_config(
#                     self.path_cascade,
#                     root_key=[self.get_task_family()],
#                     **self.param_kwargs,
#                 )
#             return {}

#         @cached_property
#         def cfg(self) -> DynamicModel:
#             """Return the resolved configuration, optionally validated by a cfg_spec."""
#             if self.cfg_spec:
#                 # Dynamically create a model from the spec dictionary
#                 # Base it on DynamicModel to preserve variadics in model_extra
#                 model_cls = create_model(
#                     f"{self.__class__.__name__}Cfg",
#                     __base__=DynamicModel,
#                     **self.cfg_spec,  # pylint: disable=not-a-mapping
#                 )
#                 return model_cls.model_validate(self.cfg_dict)

#             return DynamicModel.model_validate(self.cfg_dict)

#         @cached_property
#         def sha(self) -> str:
#             """Generate deterministic hash of task state."""
#             data = {
#                 "params": self.param_kwargs,
#                 "config": self.cfg.model_dump(),
#                 "requires": {
#                     req.task_id: req.sha
#                     for req in luigi.task.flatten(self.requires())
#                 },
#             }
#             if self.hash_commit:
#                 data["commit"] = get_git_commit()

#             # Deterministic JSON dump using sorted keys to ensure stable hashing
#             dump = json.dumps(data, sort_keys=True)
#             return hashlib.sha256(dump.encode()).hexdigest()

#         def _check_hash(self) -> bool:
#             """Verify existence and validity of hash."""

#             # outputs = luigi.task.flatten(self.output())

#             if (
#                 not self.path_hash.exists()
#                 or self.path_hash.read_text(encoding="utf-8").strip()
#                 != self.sha
#             ):
#                 return False
#             return True

#         def complete(self) -> bool:
#             """Perform local completion check with optional remote pull."""
#             # Perform standard check first
#             is_complete = super().complete()
#             if is_complete:
#                 if self._check_hash():
#                     rich.print(
#                         f"Task [cyan]{self.task_id}[/cyan] detected as complete (local files + valid hash)."
#                     )
#                     return True

#                 rich.print(
#                     f"Task [cyan]{self.task_id}[/cyan] local files exist, but hash is invalid/missing."
#                 )

#             # Remote check: If missing locally, try to pull from remote
#             if self.task_config.remote and self.task_config.remote.pull_inputs:
#                 outputs = luigi.task.flatten(self.output())
#                 files_to_pull = [
#                     Path(ot.path) for ot in outputs if hasattr(ot, "path")
#                 ] + [self.path_hash]

#                 rich.print(
#                     f"[bold blue]SciCD:[/bold blue] Task [cyan]{self.task_id}[/cyan] outputs missing locally. Attempting to pull from remote..."
#                 )
#                 for f in files_to_pull:
#                     rich.print(f"  -> [dim]{f}[/dim]")
#                 if scicd.remote.pull(*files_to_pull):
#                     # Re-verify everything after the pull
#                     if self._check_hash():
#                         rich.print(
#                             f"Successfully pulled and verified outputs for [cyan]{self.task_id}[/cyan]."
#                         )
#                         return True
#                     else:
#                         rich.print(
#                             f"Pulled outputs for [cyan]{self.task_id}[/cyan], but hash does not match current state."
#                         )
#                         return False

#                     is_complete_now = super().complete()
#                     if is_complete_now:
#                         rich.print(
#                             f"Successfully pulled outputs for [cyan]{self.task_id}[/cyan]."
#                         )
#                     return is_complete_now

#             return False

#     # =========================================================================
#     # INTERNAL EVENT REGISTRATION
#     # =========================================================================

#     @Task.event_handler(luigi.Event.START)
#     def _on_start(task):
#         """Prepare local environment before task execution."""
#         rich.print(f"Starting execution for [cyan]{task.task_id}[/cyan]")
#         # Ensure output directories exist
#         for target in luigi.task.flatten(task.output()):
#             if hasattr(target, "path"):
#                 Path(target.path).parent.mkdir(parents=True, exist_ok=True)

#     @Task.event_handler(luigi.Event.SUCCESS)
#     def _on_success(task):
#         """Execute checkpointing and remote push upon task success."""
#         rich.print(f"Task [cyan]{task.task_id}[/cyan] completed successfully.")

#         task_hash = task.sha
#         rich.print(
#             f"Saved hash [green]{task_hash}[/green] for [cyan]{task.task_id}[/cyan]."
#         )
#         path_hash = task.path_hash
#         path_hash.parent.mkdir(parents=True, exist_ok=True)
#         path_hash.write_text(task_hash, encoding="utf-8")

#         # Push to remote if enabled
#         if task.task_config.remote and task.task_config.remote.push_outputs:
#             outputs = luigi.task.flatten(task.output())
#             files_to_push = [path_hash]
#             for ot in outputs:
#                 if hasattr(ot, "path"):
#                     p = Path(ot.path)
#                     files_to_push.append(p)

#             if files_to_push:
#                 rich.print(
#                     f"Pushing {len(files_to_push)} items to remote for [cyan]{task.task_id}[/cyan]..."
#                 )
#                 for f in files_to_push:
#                     rich.print(f"  -> [dim]{f}[/dim]")
#                 scicd.remote.push(*files_to_push)
#         else:
#             rich.print(
#                 f"Skipping push for [cyan]{task.task_id}[/cyan] (remote.push_outputs=False)."
#             )

#     # # Preserve metadata
#     Task.__name__ = name
#     # Task.__module__ = luigi.Task.__module__
#     # Task.__doc__ = luigi.Task.__doc__
#     return cast(Type[T], Task)


# # # Standard export
# # SciTask = augment_task(name="SciTask", hash_commit=False)
# # DevTask = augment_task(name="SciTask", hash_commit=True)
