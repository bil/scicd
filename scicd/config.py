"""
Configuration management for SciCD.
"""

from __future__ import annotations
import re
import os
import ast

from pathlib import Path
from typing import Optional, Any, Union, Literal, ClassVar

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    model_validator,
    field_validator,
)

from scicd.yamler import deep_merge, load_yaml

CACHE: dict[Optional[str], dict] = {}


def _validate_ints(v: Any) -> Any:
    """Coerce strings to integers"""
    if isinstance(v, str) and v.strip():
        try:
            return int(v)
        except ValueError as e:
            raise ValueError("String must cast to an int!") from e
    return v


class DynamicModel(BaseModel):
    """
    A Pydantic model that allows arbitrary extra fields.
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
        return list(
            self.__class__.model_fields.keys()  # pylint: disable=no-member
        ) + list(self.model_extra.keys() if self.model_extra else [])

    def __getitem__(self, key):
        """Enable dictionary-like access."""
        return getattr(self, key)


class UserConfig(DynamicModel):
    """
    User-defined configuration namespace.
    """


class ConcurrencyConfig(BaseModel):
    """
    Configuration for task concurrency strategy.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    method: Literal["biject", "slice"] = "biject"
    workers: Optional[int] = None

    @field_validator("workers", mode="before")
    @classmethod
    def validate_ints(cls, v: Any) -> Any:
        """Coerce strings to integers for CLI compatibility."""
        return _validate_ints(v)

    @model_validator(mode="after")
    def check_workers(self) -> "ConcurrencyConfig":
        """Validate that workers count is present for non-biject methods."""
        if self.method in ["slice", "queue"]:
            if self.workers is None:
                raise ValueError(
                    f"workers must be specified for concurrency method {self.method}"
                )
            if self.workers <= 0:
                raise ValueError(
                    f"workers must be a positive integer, got {self.workers}"
                )
        return self


# class QueueConfig(BaseModel):
#     """
#     Configuration for queue-based dynamic concurrency.
#     Used when method='queue' to interface with message brokers like GCP Pub/Sub.
#     """

#     model_config = ConfigDict(extra="allow", validate_assignment=True)

#     platform: Optional[Literal["gcp"]] = None
#     topic: str = ""
#     subscription: str = ""
#     config: dict[str, Any] = {}

#     @model_validator(mode="after")
#     def check_queue(self) -> "QueueConfig":
#         """Ensure required fields are set for the selected platform."""
#         if self.platform == "gcp":
#             if not self.topic:
#                 raise ValueError("queue.topic cannot be empty")
#             if not self.subscription:
#                 raise ValueError("queue.subscription cannot be empty")
#         return self


class TaskConfig(BaseModel):
    """
    Unified configuration for a single node within SciCD.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # Helpers for parsing/normalization
    _mem_regex: ClassVar[re.Pattern] = re.compile(
        r"^(\d+)\s*([KMGT])(?:i|B|iB)?$", re.IGNORECASE
    )
    _time_regex: ClassVar[re.Pattern] = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)

    tags: list[str] = []

    cpu: Optional[int] = Field(default=None, gt=0)
    memory: Optional[str] = None

    disk: Optional[str] = None
    disk_type: Optional[str] = None

    gpu: Optional[int] = Field(default=None, gt=0)
    gpu_type: Optional[str] = None

    compute_type: Optional[str] = None
    machine_type: Optional[str] = None

    max_duration: Optional[str] = None
    retry: int = Field(default=0, ge=0)

    image: Optional[str] = None

    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    flags: Optional[list[str]] = None
    # queue: QueueConfig = QueueConfig()

    # Pre/post script hooks
    # pre: list[str] = []
    # post: list[str] = []

    # Environment variables
    variables: dict[str, Union[str, int, float]] = {}
    # Arbitrary CI/CD that is directly passed through
    cicd: dict[str, Any] = {}

    # Any additional user config
    user: UserConfig = UserConfig()

    @field_validator("tags", mode="before")
    @classmethod
    def valdate_lists(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = ast.literal_eval(v)
            if not isinstance(v, list):
                raise ValueError(f"Could not parse string {v} into a list!")
            return v
        else:
            raise ValueError(f"Could not parse {v} into a list!")

    @field_validator("cpu", "gpu", "retry", mode="before")
    @classmethod
    def validate_ints(cls, v: Any) -> int:
        return _validate_ints(v)

    @field_validator("memory", "disk", mode="before")
    @classmethod
    def validate_memory(cls, v: Any) -> Any:
        """Normalize memory strings (e.g., '8GB' -> '8G')."""
        if v is None:
            return v
        if isinstance(v, int):
            if v < 0:
                raise ValueError(f"Memory cannot be negative, received {v}")
            # Assume units of megabytes
            return f"{v}M"

        v_str = str(v).strip()
        match = cls._mem_regex.match(v_str)
        if not match:
            raise ValueError(
                f"Invalid memory format '{v_str}'. Expected e.g. '8G', '512MiB'"
            )

        val = match.group(1)  # number
        unit = match.group(2).upper()  # unit character
        # Preserve 'i' if provided
        if "i" in v_str.lower():
            unit += "i"
        return f"{val}{unit}"

    @field_validator("max_duration", mode="before")
    @classmethod
    def validate_time(cls, v: Any) -> Any:
        """Normalize max_duration strings (e.g., '1h30m' -> '1h 30m')."""
        if v is None:
            return None
        if isinstance(v, int):
            # Assume minutes
            return f"{v}m"

        v_str = str(v).strip()
        # We can have compound times like 1h 30m
        matches = cls._time_regex.findall(v_str)
        if not matches:
            raise ValueError(
                f"Invalid max_duration format '{v_str}'. Expected e.g. '1h 30m', '10s'"
            )

        # Canonical format: normalized space-separated lowercase segments
        return " ".join([f"{val}{unit.lower()}" for val, unit in matches])

    # @model_validator(mode="after")
    # def check_queue(self) -> "TaskConfig":
    #     """Verify queue settings if concurrency method is 'queue'."""
    #     if self.concurrency.method == "queue":
    #         if (
    #             self.queue.platform is None
    #             or not self.queue.subscription
    #             or not self.queue.topic
    #         ):
    #             raise ValueError(
    #                 "To use queue concurrency method, must provide "
    #                 "queue.{platform,subscription,topic}"
    #             )
    #     return self

    @property
    def memory_mb(self) -> int | None:
        """The memory requirement converted to megabytes (M)."""
        return self._parse_memory_to_mb(self.memory)

    @property
    def disk_mb(self) -> int | None:
        """The disk requirement converted to megabytes (M)."""
        if not self.disk:
            return None
        return self._parse_memory_to_mb(self.disk)

    @property
    def max_duration_minutes(self) -> int | None:
        """The max_duration converted to total minutes."""
        if self.max_duration is None:
            return None
        return self._parse_time_to_minutes(self.max_duration)

    @classmethod
    def _parse_memory_to_mb(cls, mem_str: Optional[str]) -> int | None:
        """Internal helper to convert memory strings to MiB integers."""
        if mem_str is None:
            return None
        mem_str = mem_str.strip()
        match = cls._mem_regex.match(mem_str)
        if not match:
            raise ValueError(f"Could not match memory string: {mem_str}")
        value = int(match.group(1))
        unit = match.group(2).upper()

        # Distinguish between Binary (Gi) and Decimal (G)
        is_binary = "i" in mem_str.lower()

        if not is_binary:
            # Already SI
            multipliers = {"K": 1 / 1000, "M": 1, "G": 1000, "T": 1000 * 1000}
        else:
            multipliers = {
                "K": 1024 / (1000**2),
                "M": (1024**2) / (1000**2),
                "G": (1024**3) / (1000**2),
                "T": (1024**4) / (1000**2),
            }

        mb = value * multipliers[unit]
        return int(mb)

    @classmethod
    def _parse_time_to_minutes(cls, time_str: str) -> int:
        """Internal helper to convert time strings to minute integers."""
        time_str = time_str.strip().lower()
        matches = re.findall(cls._time_regex, time_str)
        if not matches:
            raise ValueError(f"Invalid time format: '{time_str}'")
        total_minutes = 0
        for value, unit in matches:
            value = int(value)
            if unit == "d":
                total_minutes += value * 24 * 60
            elif unit == "h":
                total_minutes += value * 60
            elif unit == "m":
                total_minutes += value
            elif unit == "s":
                total_minutes += value // 60
        return total_minutes

    def merge(self, overrides: dict[str, Any]) -> "TaskConfig":
        """
        Create a new TaskConfig by merging an arbitrary dictionary into the current one.
        """
        current = self.model_dump()
        out = deep_merge(current, overrides)
        return TaskConfig.model_validate(out)


class WorkspaceConfig(BaseModel):
    """Configuration for the source control and CI/CD platform."""

    _remote_protocols: ClassVar[tuple[str, ...]] = ("rclone://",)
    model_config = ConfigDict(extra="forbid")

    url: str = ""
    project: str = ""
    cicd: dict[str, Any] = {}

    data_root: Optional[str] = None
    remote_root: Optional[str] = None
    # this string will be appended to transfer command
    remote_flags: Optional[str] = None

    user: UserConfig = UserConfig()

    @model_validator(mode="after")
    def validate_remote_config(self) -> WorkspaceConfig:
        if self.remote_root is not None:
            if not self.remote_root.startswith(self._remote_protocols):
                raise ValueError(
                    f"the remote root must start with one of {self._remote_protocols}"
                )
            if self.data_root is None:
                raise ValueError("data_root must be set alongside remote_root")
        return self


def find_config_path() -> Path | None:
    """
    Search for the SciCD configuration file in prioritized order.

    Priority:
    1. Environment Variable: SCICD_CONFIG_PATH
    2. Root scicd.yaml
    3. Root .scicd.yaml
    4. .scicd/config.yaml
    5. .scicd/scicd.yaml

    Returns:
        Path object to the found configuration file.

    Raises:
        FileNotFoundError: If no configuration file is found in any standard location.
    """

    # Environment Variable
    env_path = os.getenv("SCICD_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            print(f"Loading config from SCICD_CONFIG_PATH: {env_path}")
            return p
        raise FileNotFoundError(
            f"Config file specified in SCICD_CONFIG_PATH not found: {env_path}"
        )

    # Standard Locations
    candidates = [
        "scicd.yaml",
        ".scicd.yaml",
        ".scicd/config.yaml",
        ".scicd/scicd.yaml",
    ]

    for c in candidates:
        p = Path(c)
        if p.exists():
            print(f"Loading discovered config: {c}")
            return p

    return None


def load_config(
    config_path: str | None = None,
) -> dict[str, Any]:
    """
    Load configuration from YAML file.
    If no path is provided, it uses discovery logic.
    """
    if config_path is None:
        path = find_config_path()
        if not path:
            return {}
        else:
            config_path = str(path)

    if config_path in CACHE:
        return CACHE[config_path]
    else:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

    config = load_yaml(str(path))
    for key, val in config.items():
        if key == "workspace":
            if not isinstance(val, dict):
                raise ValueError(f"{key} configuration should hold a dict")
        elif key == "task":
            if not isinstance(val, dict):
                raise ValueError(f"{key} configuration should hold a dict")
        elif key.startswith("task."):
            if not isinstance(val, dict):
                raise ValueError(f"{key} configuration should hold a dict")
        else:
            raise ValueError(
                f"Unexpected configuration {key};",
                "Top-level should be workspace, task, or task.<family>.",
                f"Workspace configurations: {sorted(WorkspaceConfig.model_fields)}.",
                f"Task configurations: {sorted(TaskConfig.model_fields)}.",
            )
    CACHE[config_path] = config
    return config


# class _ConfigManager:
#     """Internal singleton manager for configuration state."""

#     _workspace: Optional[WorkspaceConfig] = None
#     _base_task: Optional[TaskConfig] = None
#     _task_overrides: dict[str, Any] = {}

#     @classmethod
#     def _initialize(cls):
#         config_dict = load_config()
#         ws_data = {}

#         for key, val in config_dict.items():
#             if key == "workspace":
#                 if not isinstance(val, dict):
#                     raise ValueError(
#                         f"{key} configuration should hold a dict"
#                     )
#                 for key2, val2 in val.items():
#                     ws_data[key2] = val2
#             elif key == "task":
#                 if not isinstance(val, dict):
#                     raise ValueError(
#                         f"{key} configuration should hold a dict"
#                     )
#                 for key2, val2 in val.items():
#                     task_data[key2] = val2
#             elif key.startswith("task."):
#                 family = key[5:]
#                 if not isinstance(val, dict):
#                     raise ValueError(
#                         f"{key} configuration should hold a dict"
#                     )
#                 cls._task_overrides[family] = val
#             else:
#                 raise ValueError(
#                     f"Unexpected configuration {key};",
#                     "Top-level should be workspace, task, or task.<family>.",
#                     f"Workspace configurations: {sorted(WorkspaceConfig.model_fields)}.",
#                     f"Task configurations: {sorted(TaskConfig.model_fields)}.",
#                 )

#         cls._workspace = WorkspaceConfig(**ws_data)
#         cls._base_task = TaskConfig(**task_data)

#     @classmethod
#     def get_workspace_config(cls) -> WorkspaceConfig:
#         """Get workspace singleton."""
#         cls._initialize()
#         assert isinstance(cls._workspace, WorkspaceConfig)
#         return cls._workspace

#     @classmethod
#     def get_base_task(cls) -> TaskConfig:
#         """Get base task configuration singleton."""
#         cls._initialize()
#         assert isinstance(cls._base_task, TaskConfig)
#         return cls._base_task

#     @classmethod
#     def get_task_overrides(cls) -> dict[str, Any]:
#         """Get dictioanry of static task overrides"""
#         cls._initialize()
#         assert isinstance(cls._task_overrides, dict)
#         return cls._task_overrides

#     @classmethod
#     def get_task(cls, task: Optional[str] = None, **overrides) -> TaskConfig:
#         """Get configuration for a task using static and dynamic overrides"""
#         # Defaults
#         base = cls.get_base_task()
#         if task and task in cls._task_overrides:
#             # Apply static overrides from config file
#             overrides = deep_merge(overrides, cls._task_overrides[task])
#         # Apply variadic overrides (discovered in task implementation, for instance)
#         overrides = deep_merge(overrides, overrides)
#         return base.merge(overrides)

#     @classmethod
#     def reset(cls):
#         """Reset all cached config (for testing)."""
#         cls._workspace = None
#         cls._base_task = None
#         cls._cli_overrides = {}

#     @classmethod
#     def as_dict(cls):
#         """
#         Return workspace, task defaults, and task overrides as a single dict.
#         """
#         cls._initialize()
#         workspace_dict = cls.get_workspace_config().model_dump()
#         base_task_dict = cls.get_base_task().model_dump()
#         task_overrides = cls.get_task_overrides()
#         # Flatten
#         data = {
#             "workspace": workspace_dict,
#             "task": base_task_dict,
#             **{f"task.{family}": val for family, val in task_overrides.items()},
#         }
#         return data


def get_workspace_config(config_path: Optional[str] = None) -> WorkspaceConfig:
    """Get workspace configuration."""
    config_dict = load_config(config_path)
    wspace_dict = config_dict.get("workspace", {})
    return WorkspaceConfig(**wspace_dict)


def get_task_config(
    task: Optional[str] = None, config_path: Optional[str] = None, **overrides
) -> TaskConfig:
    """Get base task configuration."""
    config_dict = load_config(config_path)
    task_dict = config_dict.get("task", {})
    if task is not None and f"task.{task}" in config_dict:
        static_overrides = config_dict[f"task.{task}"]
        task_dict = deep_merge(task_dict, static_overrides)
    if overrides:
        task_dict = deep_merge(task_dict, overrides)
    task_config = TaskConfig(**task_dict)
    return task_config


# def get_task_overrides() -> dict[str, Any]:
#     """Get base task configuration singleton."""
#     return _ConfigManager.get_task_overrides()


# def get_task_config(task: Optional[str] = None, config_path: Optional[str] = None, **overrides) -> TaskConfig:
#     """
#     Get TaskConfig with optional runtime overrides.
#     Priority: Base Defaults -> Manual Overrides -> CLI Overrides.
#     """
#     """Get configuration for a task using static and dynamic overrides"""
#     # Defaults
#     base = cls.get_base_task(config_path)
#     if task and task in cls._task_overrides:
#         # Apply static overrides from config file
#         overrides = deep_merge(overrides, cls._task_overrides[task])
#     # Apply variadic overrides (discovered in task implementation, for instance)
#     overrides = deep_merge(overrides, overrides)
#     return base.merge(overrides)
#     return _ConfigManager.get_task(task, **overrides)


# def reset_config():
#     """Reset all cached configuration."""
#     _ConfigManager.reset()
