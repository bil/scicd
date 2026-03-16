import pprint
from typing import Optional, List, Dict, Any
from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
import tomli


def deep_update(source, overrides):
    """
    Performs a recursive dictionary merge.

    Args:
        source (dict): The base dictionary to be updated.
        overrides (dict): The dictionary containing overriding values.

    Returns:
        dict: The updated source dictionary.
    """
    source = deepcopy(source)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and value:
            returned = deep_update(source.get(key, {}), value)
            source[key] = returned
        else:
            source[key] = overrides[key]
    return source


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
        # We only look at the base state, ignoring the 'tasks' sub-dictionary
        param = {k: v for k, v in self._base_state.items() if k != "task"}

        return self._build_dataclass(WorkspaceConfig, param)

    def family_config(self, family: str) -> TaskConfig:
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

    def _build_dataclass(
        self, config_class: type[WorkspaceConfig] | type[TaskConfig], config_dict: dict
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
