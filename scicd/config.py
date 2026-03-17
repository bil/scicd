import pprint
import os

from typing import Optional, List, Dict, Any
from copy import deepcopy
from dataclasses import dataclass, field, fields
from pathlib import Path

import tomli

from scicd.yamler import deep_update, specify, load_yaml, yml_suffix


@dataclass(kw_only=True)
class WorkspaceConfig:
    """Global environment settings. Includes GitLab, GCP, and Paths."""

    # Gitlab
    gitlab_project: str
    gitlab_url: str = "https://gitlab.com"
    gitlab_workflow: Dict[str, Any] = field(default_factory=dict)
    gitlab_default: Dict[str, Any] = field(default_factory=dict)

    # Paths (Naming matches TOML exactly)
    path_output: str = "output"
    path_download: str = "download"
    path_remote: Optional[str] = None
    path_parameters: Optional[str] = None
    path_namespace: Optional[str] = None

    remote_completion_enabled: bool = False
    remote_protocol: str = "rclone"  # ignore if path_remote is None
    https_header: Dict[str, Any] = field(default_factory=dict)
    rclone_flags: List[str] = field(default_factory=lambda: ["-P", "--transfers", "4"])

    def __post_init__(self):
        """Expand environment variables for all string fields."""
        for f in fields(self):
            if f.name.startswith("path"):
                # Avoid collision with namespace-overrided getattribute
                val = super().__getattribute__(f.name)
                setattr(self, f.name, os.path.expandvars(val))

    def __getattribute__(self, name: str) -> Any:
        """
        Intercepts path access to append the namespace.
        """
        # Use super() to avoid infinite recursion
        val = super().__getattribute__(name)

        # Only apply joining logic to 'path_' fields (but not the namespace itself!)
        if name in ("path_output", "path_remote", "path_download") and isinstance(
            val, str
        ):
            namespace = super().__getattribute__("path_namespace")
            if namespace is not None:
                return str(Path(val) / namespace)

        return val


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
        Only permits overrides for TaskConfig settings.
        Workspace settings (paths, GitLab URLs) are protected to ensure
        consistency between local DAG generation and CI/CD execution.
        """
        task_overrides = {}

        for key, val in kwargs.items():
            if key.startswith("scicd_"):
                # Can override with scicd namespace
                # Or with direct key!
                key = key[len("scicd_") :]
            # Handle specific task overrides: --scicd-tasks-MyTask-cpu="4"
            if key.startswith("task_"):
                remainder = key[len("task_") :]
                parts = remainder.split("_", 1)  # Expect <Task>_<key>
                if len(parts) == 2:  # we should
                    family, option = parts
                    # We only allow overriding fields that exist in TaskConfig
                    if option in fields(TaskConfig):
                        task_overrides.setdefault("task", {}).setdefault(family, {})[
                            option
                        ] = val
                    else:
                        print(
                            f"Cannot override workspace configuration {option} for {family}!\n",
                            f"Set {option} in pyproject.toml under [tool.scicd] namespace.",
                        )

            # Handle global task defaults (e.g. cpu)
            else:
                option = (
                    key  # we're not in task namespace, so we are using key directly
                )
                # Block workspace-only keys from being overridden at CLI
                if option in fields(TaskConfig):
                    task_overrides[option] = val
                else:
                    print(
                        f"Ignoring override for protected workspace setting: {option}\n",
                        f"Set {option} in pyproject.toml under [tool.scicd] namespace.",
                    )

        # Update global state with validated task overrides only
        self._base_state = deep_update(self._base_state, task_overrides)

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

    def get_sync_command(self, direction: str = "push") -> str:
        """
        Generates an rclone command with a safety check for pulls.
        """
        wspace = self.workspace_config()

        if not wspace.path_remote:
            return None

        # Get flags from config
        flags = " ".join(wspace.rclone_flags)

        if direction == "pull":
            src = wspace.path_remote
            dest = wspace.path_output

            return (
                f"if rclone lsf {src} >/dev/null 2>&1; then "
                f"rclone copy {src} {dest} {flags}; "
                f"else echo 'Remote source {src} not found, starting with empty local directory.'; fi"
            )

        src = wspace.path_output
        dest = wspace.path_remote
        return f"rclone copy {src} {dest} {flags}"

    def _build_dataclass(
        self,
        config_class: type[WorkspaceConfig] | type[TaskConfig],
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
    path = SciCDConfig().workspace_config().path_parameters
    path = yml_suffix(path)  # if a suffix wasn't provided, tries to infer!

    # Not using feature
    if path is None:
        return {}

    if not Path(path).exists():
        print(f"Tried to load parameters file at {str(path)} but didn't exist!")
        return {}

    cfg = load_yaml(path)

    # Nothing provided for this Task
    if key not in cfg:
        print("No config for task")
        return {}

    # Override default config
    print("Overriding!")
    cfg = cfg[key]
    config = cfg.get("config", {})
    override = cfg.get("override", [])
    print(config, override)
    # Cascading logic
    return specify(config, override, **kwargs)


def get_workspace(**kwargs):
    return SciCDConfig(**kwargs).workspace_config()


def get_family(family=None, **kwargs):
    return SciCDConfig(**kwargs).family_config(family)
