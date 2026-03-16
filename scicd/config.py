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
class SciCDDefaults:
    """
    Replaces `class scicd(luigi.Config)`.
    Defines all configuration parameters, their types, and their defaults.
    """

    # CI/CD governance
    image: str = "python:3.10-slim"
    tags: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    retries: int = 0
    cpu: str = "1"
    memory: str = "8Gi"
    cpu_request_vars: List[str] = field(default_factory=list)
    memory_request_vars: List[str] = field(default_factory=list)

    # Gitlab
    gitlab_project: str
    gitlab_url: str = "https://gitlab.com"
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
                    if "tasks" not in overrides:
                        overrides["tasks"] = {}
                    if family not in overrides["tasks"]:
                        overrides["tasks"][family] = {}
                    overrides["tasks"][family][option] = val

            elif key.startswith("scicd_"):
                option = key[len("scicd_") :]
                overrides[option] = val

        # Update global state
        self._base_state = deep_update(self._base_state, overrides)

    def family_config(self, family: str) -> SciCDDefaults:
        """
        Resolves global state for a specific family.
        Performs Access Validation (Point 3) by returning the dataclass.
        """
        param = deepcopy(self._base_state)
        tasks_config = param.pop("tasks", {})

        if family and family in tasks_config:
            param = deep_update(param, tasks_config[family])

        return self._build_dataclass(param)

    def _build_dataclass(self, config_dict: dict) -> SciCDDefaults:
        """Helper to enforce strict dataclass schema on a dictionary."""
        valid_keys = {f.name for f in fields(SciCDDefaults)}
        filtered_config = {k: v for k, v in config_dict.items() if k in valid_keys}
        return SciCDDefaults(**filtered_config)
