import pprint
import os

from typing import Optional, List, Dict, Any
from copy import deepcopy
from dataclasses import dataclass, field, fields
from pathlib import Path

import tomli

from scicd.yamler import deep_update, specify, load_yaml


@dataclass
class PathsConfig:
    output: str = "output"
    download: str = "download"
    remote: str | None = None
    parameters: str | None = None
    rclone_flags: List[str] = field(default_factory=lambda: ["-P", "--transfers", "4"])

    def __post_init__(self):
        """
        Automatically expands environment variables in all string path fields
        immediately after instantiation.
        """
        # Expand simple strings
        if self.output:
            self.output = os.path.expandvars(self.output)
        if self.download:
            self.download = os.path.expandvars(self.download)
        if self.remote:
            self.remote = os.path.expandvars(self.remote)
        if self.parameters:
            self.parameters = os.path.expandvars(self.parameters)


@dataclass(kw_only=True)
class WorkspaceConfig:
    """Global repository settings. Never overridden by task families."""

    # Gitlab
    gitlab_project: str
    gitlab_url: str = "https://gitlab.com"
    gitlab_workflow: Dict[str, Any] = field(default_factory=dict)
    gitlab_default: Dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class TaskConfig:
    """Execution settings. Defined as defaults at the root, overridable per task."""

    # CI/CD governance
    image: str = "python:3.10-slim"
    python_executable: str = "python"
    tags: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    retries: int = 0
    cpu: str = "1"
    memory: str = "8Gi"
    cpu_request_vars: List[str] = field(default_factory=list)
    memory_request_vars: List[str] = field(default_factory=list)

    # Gitlab
    gitlab_extras: Dict[str, Any] = field(default_factory=dict)

    # GCP
    gcp_project: Optional[str] = None
    gcp_pubsub_topic: Optional[str] = None
    gcp_pubsub_subscription: Optional[str] = None

    # Concurrency
    concurrency_method: str = "biject"
    concurrency_workers: int = 1


class SciCDConfig:
    """Singleton configuration manager for SciCD."""

    _instance = None
    _initialized = False  # Class-level flag to protect __init__

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._base_state: dict = {}

            self._load_toml_state()

            self.__class__._initialized = True

    def __repr__(self) -> str:
        """Provides a pretty-printed dictionary representation for the CLI."""
        return pprint.pformat(self._base_state, indent=2, sort_dicts=False)

    def _load_toml_state(self):
        """Loads pyproject.toml into the base state."""
        toml_path = Path("pyproject.toml")
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                pyproject_data = tomli.load(f)
                self._base_state = pyproject_data.get("tool", {}).get("scicd", {})

    def override(self, **kwargs):
        """
        Takes variadic kwargs, parses them into a nested dictionary,
        """
        overrides = {}

        for key, val in kwargs.items():
            if key.startswith("scicd_tasks_"):
                # E.g., scicd_tasks_Task_cpu_request_vars -> "Task", "cpu_request_vars"
                remainder = key[len("scicd_tasks_") :]
                parts = remainder.split("_", 1)

                if len(parts) == 2:
                    family, option = parts
                    if "task" not in overrides:
                        overrides["task"] = {}
                    if family not in overrides["task"]:
                        overrides["task"][family] = {}
                    overrides["task"][family][option] = val

            elif key.startswith("scicd_"):
                option = key[len("scicd_") :]
                overrides[option] = val

        # Update global state
        self._base_state = deep_update(self._base_state, overrides)

    def workspace_config(self) -> WorkspaceConfig:
        """
        Returns only the global workspace settings from the root of pyproject.toml.
        Ignores any task-specific overrides.
        """

        return self._build_dataclass(WorkspaceConfig, self._base_state)

    def family_config(self, family: str = None) -> TaskConfig:
        """
        Returns the resolved execution settings for a specific task family.
        Applies task-specific overrides on top of the root defaults.
        """
        param = deepcopy(self._base_state)
        tasks_config = param.pop("task", {})

        # Apply the specific family overrides
        if family and family in tasks_config:
            param = deep_update(param, tasks_config[family])

        return self._build_dataclass(TaskConfig, param)

    def paths_config(self) -> PathsConfig:
        param = deepcopy(self._base_state.get("paths", {}))
        return self._build_dataclass(PathsConfig, param)

    def get_sync_command(self, direction: str = "push") -> str:
        """
        Generates an rclone sync command.
        direction: 'pull' (remote -> local) or 'push' (local -> remote)
        """
        p = self.paths_config()

        if not p.remote:
            return None

        if direction == "pull":
            src, dest = p.remote, p.output
        else:
            src, dest = p.output, p.remote

        flags = " ".join(p.rclone_flags)

        cmd = f"rclone copy {src} {dest} {flags}"

        return cmd

    def _build_dataclass(
        self,
        config_class: type[WorkspaceConfig] | type[TaskConfig] | type[PathsConfig],
        config_dict: dict,
    ) -> WorkspaceConfig | TaskConfig:
        """Helper to enforce strict dataclass schema on a dictionary."""
        valid_keys = {f.name for f in fields(config_class)}
        filtered_config = {k: v for k, v in config_dict.items() if k in valid_keys}
        return config_class(**filtered_config)


def get_config(family: str = None, **kwargs):
    """
    CLI utility to inspect the active configuration state.

    Args:
        family (str, optional): The Luigi task family to inspect. If None,
                                returns the raw global config state.
        **kwargs: Variadic overrides (e.g., scicd_image="ubuntu:latest").
    """
    cfg = SciCDConfig()

    # Apply any CLI overrides first so the user sees the final state
    if kwargs:
        cfg.override(**kwargs)

    # Return the dataclass if they asked for a specific task, else the raw singleton instance
    if family:
        cfg = cfg.family_config(family)

    return str(cfg)


def cascading_config(key, **kwargs):
    """
    Parameter-dependent overwrite of insignificant Task configuration.
    These are basically "insignificant" (non-identifying) parameters.
    """
    path = SciCDConfig().paths_config().parameters

    # Not using feature
    if path is None:
        return {}

    path = Path(path)
    if not path.exists():
        print(f"Tried to load parameters file at {str(path)} but didn't exist!")
        return {}

    cfg = load_yaml(path)

    # Nothing provided for this Task
    if key not in cfg:
        return {}

    # Override default config
    cfg = cfg[key]
    config = cfg.get("config", {})
    override = cfg.get("override", [])

    # Cascading logic
    return specify(config, override, **kwargs)
