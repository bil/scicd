"""
Configuration management system for SciCD.

This module provides Pydantic-based configuration models for workspaces and tasks,
along with singleton managers for global configuration state and CLI override
interception.
"""

from __future__ import annotations
import re
import os

from pathlib import Path
from typing import Optional, Any, Union, Literal, Tuple, ClassVar
import ast


import dataclasses
import rich
from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    model_validator,
    field_validator,
    computed_field,
)

from scicd.yamler import deep_update, load_yaml, nest_dict, expand_vars


class DynamicModel(BaseModel):
    """
    A Pydantic model that allows arbitrary extra fields.
    Automatically wraps nested dictionaries in DynamicModel instances.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _recursive_wrap(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Only wrap in DynamicModel if the field is NOT explicitly defined in the model.
            fields = cls.model_fields
            return {
                k: (
                    DynamicModel.model_validate(v)
                    if isinstance(v, dict) and k not in fields
                    else v
                )
                for k, v in data.items()
            }
        return data

    def keys(self):
        """Enable dictionary-like unpacking."""
        return list(self.__class__.model_fields.keys()) + list(
            self.model_extra.keys() if self.model_extra else []
        )

    def __getitem__(self, key):
        """Enable dictionary-like access."""
        return getattr(self, key)


class UserConfig(DynamicModel):
    """
    User-defined configuration namespace.
    Allows dot-access to arbitrary keys defined in configuration under 'user:'.
    """


class ConcurrencyConfig(BaseModel):
    """
    Configuration for task concurrency strategy.
    Determines how work units are distributed across pipeline jobs.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    method: Literal["biject", "slice", "queue"] = "biject"
    workers: Optional[int] = None

    @field_validator("workers", mode="before")
    @classmethod
    def validate_ints(cls, v: Any) -> Any:
        """Coerce strings to integers for CLI compatibility."""
        if isinstance(v, str) and v.strip():
            try:
                return int(v)
            except ValueError:
                return v
        return v

    @model_validator(mode="after")
    def check_workers(self) -> "ConcurrencyConfig":
        """Validate that workers count is present for non-biject methods."""
        if self.method in ["slice", "queue"]:
            if self.workers is None:
                # In partial assignment, we might not have workers yet
                return self
            if self.workers <= 0:
                raise ValueError(
                    f"workers must be a positive integer, got {self.workers}"
                )
        return self


class QueueConfig(BaseModel):
    """
    Configuration for queue-based dynamic concurrency.
    Used when method='queue' to interface with message brokers like GCP Pub/Sub.
    """

    model_config = ConfigDict(extra="allow", validate_assignment=True)

    platform: Optional[Literal["gcp"]] = None
    topic: str = ""
    subscription: str = ""
    config: dict[str, Any] = {}

    @model_validator(mode="after")
    def check_queue(self) -> "QueueConfig":
        """Ensure required fields are set for the selected platform."""
        if self.platform == "gcp":
            if not self.topic:
                raise ValueError("queue.topic cannot be empty")
            if not self.subscription:
                raise ValueError("queue.subscription cannot be empty")
        return self


class RemoteConfig(BaseModel):
    """
    Configuration for remote data synchronization.
    Defines where and how task outputs are stored and retrieved.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    root: Optional[str] = None
    url: Optional[str] = None
    namespace: str = ""
    protocol: Literal["rclone", "https"] = "rclone"
    flags: list[str] = []
    pull_inputs: bool = False
    push_outputs: bool = False

    @field_validator("flags", mode="before")
    @classmethod
    def validate_list(cls, v: Any) -> Any:
        """Coerce string representations of lists (e.g. CLI) into Python lists."""
        if isinstance(v, str) and v.startswith("[") and v.endswith("]"):
            try:
                # Use literal_eval to safely parse ['a', 'b'] from CLI
                return ast.literal_eval(v)
            except (ValueError, SyntaxError):
                return v
        return v

    @model_validator(mode="before")
    @classmethod
    def resolve_path(cls, data: Any) -> Any:
        """Resolve the local root to an absolute path."""
        if isinstance(data, dict) and data.get("root"):
            data["root"] = str(Path(data["root"]).resolve())
        return data

    @model_validator(mode="after")
    def check_sync(self) -> "RemoteConfig":
        """Verify that sync requirements are met."""
        if self.pull_inputs or self.push_outputs:
            if self.url is None or self.root is None:
                # Allow partial assignment
                return self
            if not self.url or not self.root:
                raise ValueError(
                    "remote.url and remote.root are mandatory when syncing is enabled"
                )
        return self

    @computed_field
    @property
    def total_root(self) -> Optional[str]:
        """Base directory for local files, including optional namespace suffix."""
        if self.root and self.namespace:
            return f"{self.root}/{self.namespace}"
        return self.root

    @computed_field
    @property
    def total_url(self) -> Optional[str]:
        """Remote URL for syncing, including optional namespace suffix."""
        if self.url and self.namespace:
            return f"{self.url}/{self.namespace}"
        return self.url


class TaskConfig(BaseModel):
    """
    Unified configuration for a single task within SciCD.
    Defines hardware requirements, container images, and runtime behavior.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # Helpers for parsing/normalization
    _MEM_REGEX: ClassVar[re.Pattern] = re.compile(
        r"^(\d+)\s*([KMGT])(?:i|B|iB)?$", re.IGNORECASE
    )
    _TIME_REGEX: ClassVar[re.Pattern] = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)

    tags: list[str] = []
    cpu: int = Field(default=1, gt=0)
    memory: str = "8Gi"
    disk: Optional[str] = None
    gpu: Optional[int] = Field(default=None, gt=0)
    gpu_type: Optional[str] = None
    partition: Optional[str] = None
    timeout: str = "60m"
    retry: int = Field(default=0, ge=0)
    image: Optional[str] = None
    python_cmd: str = "python3"

    variables: dict[str, Union[str, int, float]] = {}
    executor_config: dict[str, Union[str, int, float]] = {}
    cicd: dict[str, Any] = {}

    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    queue: QueueConfig = QueueConfig()
    remote: RemoteConfig = RemoteConfig()
    user: UserConfig = UserConfig()

    @field_validator("memory", "disk", mode="before")
    @classmethod
    def validate_memory(cls, v: Any) -> Any:
        """Normalize memory strings (e.g., '8GB' -> '8G')."""
        if v is None:
            return v
        if isinstance(v, int):
            return f"{v}Mi"

        v_str = str(v).strip()
        match = cls._MEM_REGEX.match(v_str)
        if not match:
            raise ValueError(
                f"Invalid memory format '{v_str}'. Expected e.g. '8G', '512MiB'"
            )

        val = match.group(1)
        unit = match.group(2).upper()
        # Preserve 'i' if provided
        if "i" in v_str.lower():
            unit += "i"
        return f"{val}{unit}"

    @field_validator("timeout", mode="before")
    @classmethod
    def validate_time(cls, v: Any) -> Any:
        """Normalize timeout strings (e.g., '1h30m' -> '1h 30m')."""
        if isinstance(v, int):
            return f"{v}m"

        v_str = str(v).strip()
        matches = cls._TIME_REGEX.findall(v_str)
        if not matches:
            raise ValueError(
                f"Invalid timeout format '{v_str}'. Expected e.g. '1h 30m', '10s'"
            )

        # Canonical format: normalized space-separated lowercase segments
        return " ".join([f"{val}{unit.lower()}" for val, unit in matches])

    @model_validator(mode="after")
    def check_queue(self) -> "TaskConfig":
        """Verify queue settings if concurrency method is 'queue'."""
        if self.concurrency.method == "queue":
            if (
                self.queue.platform is None
                or not self.queue.subscription
                or not self.queue.topic
            ):
                return self
        return self

    @property
    def memory_mb(self) -> int:
        """The memory requirement converted to megabytes (MiB)."""
        return self._parse_memory_to_mb(self.memory)

    @property
    def disk_mb(self) -> Optional[int]:
        """The disk requirement converted to megabytes (MiB)."""
        if not self.disk:
            return None
        return self._parse_memory_to_mb(self.disk)

    @property
    def timeout_minutes(self) -> int:
        """The timeout converted to total minutes."""
        return self._parse_time_to_minutes(self.timeout)

    @classmethod
    def _split_memory_str(cls, mem_str: str) -> Tuple[int, str]:
        """Internal helper to split value and unit from memory string."""
        match = cls._MEM_REGEX.match(mem_str)
        if not match:
            raise ValueError(f"Could not match memory string: {mem_str}")
        value = int(match.group(1))
        unit = match.group(2)
        if mem_str.endswith("i"):
            unit += match.group(3)
        return (value, unit)

    @classmethod
    def _split_time_str(cls, time_str: str) -> list[str]:
        """Internal helper to split segments of a time string."""
        pattern = r"(\d+)\s*([hms])"
        matches = re.findall(pattern, time_str.lower())
        if not matches:
            raise ValueError(f"Could not split time string {time_str}")
        out_strs = ["".join(match) for match in matches]
        return out_strs

    @classmethod
    def _parse_memory_to_mb(cls, mem_str: Optional[str]) -> Optional[int]:
        """Internal helper to convert memory strings to MiB integers."""
        if mem_str is None:
            return None
        mem_str = mem_str.strip()
        match = cls._MEM_REGEX.match(mem_str)
        if not match:
            raise ValueError(f"Could not match memory string: {mem_str}")
        value = int(match.group(1))
        unit = match.group(2).upper()
        
        # Distinguish between Binary (Gi) and Decimal (G)
        is_binary = "i" in mem_str.lower()
        base_unit = unit.removesuffix("i").upper()
        
        if is_binary:
            # IEC Units (1024 based)
            multipliers = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}
        else:
            # SI Units (1000 based) converted to MiB
            multipliers = {
                "K": 1000 / (1024**2),
                "M": (1000**2) / (1024**2),
                "G": (1000**3) / (1024**2),
                "T": (1000**4) / (1024**2)
            }
            
        mb = value * multipliers[base_unit]
        return int(mb)

    @classmethod
    def _parse_time_to_minutes(cls, time_str: str) -> int:
        """Internal helper to convert time strings to minute integers."""
        time_str = time_str.strip()
        pattern = r"(\d+)\s*([hms])"
        matches = re.findall(pattern, time_str.lower())
        if not matches:
            raise ValueError(f"Invalid time format: '{time_str}'")
        total_minutes = 0
        for value, unit in matches:
            value = int(value)
            if unit == "h":
                total_minutes += value * 60
            elif unit == "m":
                total_minutes += value
            elif unit == "s":
                total_minutes += value // 60
        return total_minutes

    def merge(self, overrides: dict[str, Any]) -> "TaskConfig":
        """
        Create a new TaskConfig by merging an arbitrary dictionary into the current one.
        Handles nested models recursively.
        """
        current = self.model_dump(
            exclude_unset=False, exclude={"remote": {"total_root", "total_url"}}
        )
        out = deep_update(current, overrides)
        return TaskConfig.model_validate(out)


class WorkspaceConfig(BaseModel):
    """Configuration for the source control and CI/CD platform."""

    model_config = ConfigDict(extra="forbid")

    platform: Literal["gitlab", "github"] = "gitlab"
    url: str = ""
    project: str = ""
    cicd: dict[str, Any] = {}


# ================================== HELPERS =================================


def find_config_path() -> Path:
    """
    Search for the SciCD configuration file in prioritized order.

    Priority:
    1. Environment Variable: SCICD_CONFIG_PATH
    2. Root scicd.yaml
    3. .scicd/config.yaml
    4. .scicd/scicd.yaml

    Returns:
        Path object to the found configuration file.

    Raises:
        FileNotFoundError: If no configuration file is found in any standard location.
    """

    # 1. Environment Variable
    env_path = os.getenv("SCICD_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        raise FileNotFoundError(
            f"Config file specified in SCICD_CONFIG_PATH not found: {env_path}"
        )

    # 2. Standard Locations
    candidates = [
        "scicd.yaml",
        ".scicd/config.yaml",
        ".scicd/scicd.yaml",
    ]

    for c in candidates:
        p = Path(c)
        if p.exists():
            return p

    raise FileNotFoundError(
        "SciCD configuration file not found in any standard location. "
        "Please provide a configuration file."
    )


def load_config(config_path: Optional[Union[str, Path]] = None) -> dict[str, Any]:
    """
    Load configuration from YAML file.
    If no path is provided, it uses discovery logic.
    """
    if config_path is None:
        path = find_config_path()
    else:
        path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    config = load_yaml(path)

    return config or {}


class _ConfigManager:
    """Internal singleton manager for configuration state."""

    _workspace: Optional[WorkspaceConfig] = None
    _base_task: Optional[TaskConfig] = None
    _cli_overrides: dict[str, Any] = {}

    @classmethod
    def _initialize(cls):
        if (_ConfigManager._workspace is None) or (_ConfigManager._base_task is None):
            config_dict = load_config()
            ws_data = {}
            task_data = {}

            ws_fields = {
                f"workspace.{k}" for k in WorkspaceConfig.model_fields
            }  # pylint: disable=not-an-iterable
            task_fields = set(
                TaskConfig.model_fields.keys()
            )  # pylint: disable=no-member

            for key, val in config_dict.items():
                if key == "workspace":
                    for key2, val2 in config_dict["workspace"].items():
                        ws_data[key2] = val2
                elif key in task_fields:
                    task_data[key] = val
                else:
                    raise ValueError(
                        f"Unexpected configuration {key};",
                        f"Workspace configurations: {sorted(ws_fields)}",
                        f"Task configurations: {sorted(task_fields)}",
                    )

            cls._workspace = WorkspaceConfig(**ws_data)
            cls._base_task = TaskConfig(**task_data)

    @classmethod
    def get_workspace(cls) -> WorkspaceConfig:
        """Get workspace singleton."""
        cls._initialize()
        return cls._workspace

    @classmethod
    def get_base_task(cls) -> TaskConfig:
        """Get base task configuration singleton."""
        cls._initialize()
        return cls._base_task

    @classmethod
    def set_base_task(cls, task: TaskConfig):
        """Manually set the base task configuration singleton."""
        cls._base_task = task

    @classmethod
    def set_cli_overrides(cls, overrides: dict[str, Any]):
        """Store global CLI overrides to be applied to all TaskConfigs."""
        cls._cli_overrides = overrides

    @classmethod
    def get_cli_overrides(cls) -> dict[str, Any]:
        """Retrieve stored CLI overrides."""
        return cls._cli_overrides

    @classmethod
    def reset(cls):
        """Reset all cached config (for testing)."""
        cls._workspace = None
        cls._base_task = None
        cls._cli_overrides = {}


def get_workspace() -> WorkspaceConfig:
    """Get workspace configuration singleton."""
    return _ConfigManager.get_workspace()


def get_base_task() -> TaskConfig:
    """Get base task configuration singleton."""
    return _ConfigManager.get_base_task()


def set_base_task(task: TaskConfig):
    """
    Manually set the base task configuration singleton.
    Affects all subsequently created TaskConfig objects.
    """
    _ConfigManager.set_base_task(task)


def get_task_config(**overrides) -> TaskConfig:
    """
    Get TaskConfig with optional runtime overrides.
    Priority: Base Defaults -> Manual Overrides -> CLI Overrides.
    """
    # Start with cached base defaults from workspace
    task_config = get_base_task()

    # Apply Task-level overrides if provided
    if overrides:
        task_config = task_config.merge(overrides)

    # Finally apply CLI overrides (highest priority)
    cli_overrides = _ConfigManager.get_cli_overrides()
    if cli_overrides:
        task_config = task_config.merge(cli_overrides)

    return task_config


def reset_config():
    """Reset all cached configuration."""
    _ConfigManager.reset()


def cascading_config(
    filepath: Union[str, Path],
    root_key: Optional[Union[str, list[str]]] = None,
    config_key: str = "config",
    override_key: str = "override",
    **kwargs,
) -> dict:
    """
    Load a YAML file and apply cascading config logic based on regex matching.
    """
    path = Path(filepath)

    if not path.exists():
        return {}

    cfg = load_config(path)

    # Drill down if root_key is provided
    if root_key:
        if isinstance(root_key, str):
            root_key = [root_key]

        for k in root_key:
            cfg = cfg.get(k, {})

    config = cfg.get(config_key, {})
    override = cfg.get(override_key, [])

    return cascade(config, override, **kwargs)


def cascade(config: dict, override: list, **kwargs) -> dict:
    """Apply regex-based cascading override logic to a config dict."""
    out = config.copy()
    if not override:
        return out

    for kws in override[::-1]:  # top rule has priority
        spec = kws.get("match", {})
        # Ensure values are matched as strings for regex compatibility
        if all(re.match(str(v), str(kwargs.get(k))) for k, v in spec.items()):
            out = deep_update(out, kws.get("config", {}))
    return out


def intercept_cli_overrides(kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    Parses CLI **kwargs, intercepts TaskConfig fields, and stores them as overrides.
    """
    task_overrides_flat = {}
    frontend_params = {}

    valid_task_keys = set(TaskConfig.model_fields.keys())  # pylint: disable=no-member

    for k, v in kwargs.items():
        # Normalize key to use underscores for comparison (Cyclopts provides dashes)
        norm_k = k.replace("-", "_")
        root_key = norm_k.split(".")[0]

        if root_key in valid_task_keys:
            task_overrides_flat[norm_k] = v
        else:
            frontend_params[k] = v

    # Nest and Expand overrides
    task_overrides = nest_dict(task_overrides_flat)
    task_overrides = expand_vars(task_overrides)

    # Apply runtime defaults
    if task_overrides:
        try:
            # We use TaskConfig.merge on an empty base to see what the overrides normalize to.
            # This triggers all Pydantic validators (memory, timeout, etc.) correctly.
            base = TaskConfig.model_validate({})
            merged = base.merge(task_overrides)
            
            # Extract only the keys that were in the original task_overrides
            # but take their values from the 'merged' object (which are normalized)
            normalized_overrides = {}
            dumped = merged.model_dump(exclude_computed_fields=True, exclude_defaults=True)
            
            def extract_normalized(raw_dict, normalized_dict, target_dict):
                for k, v in raw_dict.items():
                    if isinstance(v, dict) and k in normalized_dict:
                        target_dict[k] = {}
                        extract_normalized(v, normalized_dict[k], target_dict[k])
                    elif k in normalized_dict:
                        target_dict[k] = normalized_dict[k]

            extract_normalized(task_overrides, dumped, normalized_overrides)

            rich.print(
                f"[bold blue]SciCD:[/bold blue] Storing global CLI overrides: {normalized_overrides}"
            )
            _ConfigManager.set_cli_overrides(normalized_overrides)
        except Exception as e:
            rich.print(f"[bold red]SciCD Error:[/bold red] Invalid CLI override: {e}")
            raise

    return frontend_params
