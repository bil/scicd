"""
Module docstring.
"""

from __future__ import annotations
import re
import os

from pathlib import Path
from typing import Optional, Any, Union, Literal, Tuple, ClassVar
from types import SimpleNamespace

import rich
from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    model_validator,
    field_validator,
    computed_field,
)

from scicd.yamler import deep_update, load_yaml, nest_dict

class UserConfig(BaseModel):
    """Extensible user-defined configuration namespace."""

    model_config = ConfigDict(extra="allow")


class ConcurrencyConfig(BaseModel):
    """Configuration for task concurrency strategy."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["biject", "slice", "queue"] = "biject"
    workers: Optional[int] = None

    @model_validator(mode="after")
    def check_workers(self) -> "ConcurrencyConfig":
        if self.method in ["slice", "queue"]:
            if self.workers is None:
                raise ValueError(
                    f"workers count is required when method is '{self.method}'"
                )
            if self.workers <= 0:
                raise ValueError(
                    f"workers must be a positive integer, got {self.workers}"
                )
        return self


class QueueConfig(BaseModel):
    """Configuration for queue-based dynamic concurrency."""

    model_config = ConfigDict(extra="allow")

    platform: Optional[Literal["gcp"]] = None
    topic: str = ""
    subscription: str = ""
    config: dict[str, Any] = {}

    @model_validator(mode="after")
    def check_queue(self) -> "QueueConfig":
        if self.platform == "gcp":
            if not self.topic:
                raise ValueError("queue.topic cannot be empty")
            if not self.subscription:
                raise ValueError("queue.subscription cannot be empty")
        return self


class RemoteConfig(BaseModel):
    """Configuration for remote data synchronization."""

    model_config = ConfigDict(extra="forbid")

    root: Optional[str] = None
    url: Optional[str] = None
    namespace: str = ""
    protocol: Literal["rclone", "https"] = "rclone"
    flags: list[str] = []
    pull_inputs: bool = False
    push_outputs: bool = False

    @model_validator(mode="before")
    @classmethod
    def expand_env_vars(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for k in ["root", "url", "namespace"]:
                if data.get(k):
                    data[k] = os.path.expandvars(data[k])
            if data.get("root"):
                data["root"] = str(Path(data["root"]).resolve())
        return data

    @model_validator(mode="after")
    def check_sync(self) -> "RemoteConfig":
        if self.pull_inputs or self.push_outputs:
            if not self.url or not self.root:
                raise ValueError(
                    "remote.url and remote.root are mandatory when syncing is enabled"
                )
        return self

    @computed_field
    @property
    def total_root(self) -> Optional[str]:
        if self.root and self.namespace:
            return f"{self.root}/{self.namespace}"
        return self.root

    @computed_field
    @property
    def total_url(self) -> Optional[str]:
        if self.url and self.namespace:
            return f"{self.url}/{self.namespace}"
        return self.url


def _dict_to_namespace(d: Any) -> Any:
    """Recursively convert dict to namespace for dot-access."""
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in d.items()})
    if isinstance(d, list):
        return [_dict_to_namespace(item) for item in d]
    return d


class TaskConfig(BaseModel):
    """Unified configuration for a single task within SciCD."""

    model_config = ConfigDict(extra="forbid")

    # Helpers for parsing/normalization
    _MEM_REGEX: ClassVar[re.Pattern] = re.compile(
        r"^(\d+)\s*([KMGT])(?:i|B|iB)?$", re.IGNORECASE
    )
    _TIME_REGEX: ClassVar[re.Pattern] = re.compile(r"(\d+)\s*([hms])", re.IGNORECASE)

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

    @model_validator(mode="before")
    @classmethod
    def expand_image(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("image"):
            data["image"] = os.path.expandvars(data["image"])
        return data

    @field_validator("memory", "disk", mode="before")
    @classmethod
    def validate_memory_str(cls, v: Any) -> Any:
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
        # Canonicalize units (8GB -> 8G, 8GiB -> 8Gi)
        if "i" in v_str.lower():
            unit += "i"
        return f"{val}{unit}"

    @field_validator("timeout", mode="before")
    @classmethod
    def validate_time_str(cls, v: Any) -> Any:
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
        if self.concurrency.method == "queue":
            if (
                self.queue.platform is None
                or not self.queue.subscription
                or not self.queue.topic
            ):
                raise ValueError("Queue must be fully configured when method='queue'")
        return self

    @property
    def user_ns(self) -> SimpleNamespace:
        return _dict_to_namespace(self.user.model_dump())

    @property
    def memory_mb(self) -> int:
        return self._parse_memory_to_mb(self.memory)

    @property
    def disk_mb(self) -> Optional[int]:
        if not self.disk:
            return None
        return self._parse_memory_to_mb(self.disk)

    @property
    def timeout_minutes(self) -> int:
        return self._parse_time_to_minutes(self.timeout)

    @classmethod
    def _split_memory_str(cls, mem_str: str) -> Tuple[int, str]:
        match = cls._MEM_REGEX.match(mem_str)
        if not match:
            raise ValueError(f"Could not match memory string: {mem_str}")

        val = int(match.group(1))
        unit = match.group(2).upper()
        if "i" in mem_str.lower():
            unit += "i"
        return val, unit

    @classmethod
    def _split_time_str(cls, time_str: str) -> list[str]:
        matches = cls._TIME_REGEX.findall(time_str)
        if not matches:
            raise ValueError(f"Could not split time string {time_str}")
        return ["".join(m) for m in matches]

    @classmethod
    def _parse_memory_to_mb(cls, mem_str: Optional[str]) -> Optional[int]:
        if mem_str is None:
            return None
        value, unit = cls._split_memory_str(mem_str)
        base_unit = unit.removesuffix("i").upper()
        multipliers = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}
        mb = value * multipliers[base_unit]
        return int(mb)

    @classmethod
    def _parse_time_to_minutes(cls, time_str: str) -> int:
        matches = cls._TIME_REGEX.findall(time_str)
        if not matches:
            raise ValueError(f"Invalid time format: '{time_str}'")
        total_minutes = 0
        for value, unit in matches:
            value = int(value)
            unit = unit.lower()
            if unit == "h":
                total_minutes += value * 60
            elif unit == "m":
                total_minutes += value
            elif unit == "s":
                total_minutes += value // 60
        return total_minutes

    def merge(self, overrides: dict[str, Any]) -> "TaskConfig":
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

    @model_validator(mode="before")
    @classmethod
    def expand_vars(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("url"):
                data["url"] = os.path.expandvars(data["url"])
            if data.get("project"):
                data["project"] = os.path.expandvars(data["project"])
        return data


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
        "SciCD configuration file not found. "
        "Create 'scicd.yaml' or '.scicd/config.yaml' in your project root."
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
    """Internal config manager."""

    _workspace: Optional[WorkspaceConfig] = None
    _base_task: Optional[TaskConfig] = None
    _cli_overrides: dict[str, Any] = {}

    @classmethod
    def _initialize(cls):
        if (_ConfigManager._workspace is None) or (_ConfigManager._base_task is None):
            config_dict = load_config()
            ws_data = {}
            task_data = {}

            ws_fields = {f"workspace.{k}" for k in WorkspaceConfig.model_fields} # pylint: disable=not-an-iterable
            task_fields = set(TaskConfig.model_fields.keys()) # pylint: disable=no-member

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
        return cls._cli_overrides

    @classmethod
    def reset(cls):
        """Reset all cached config (for testing)."""
        cls._workspace = None
        cls._base_task = None
        cls._cli_overrides = {}


def get_workspace() -> WorkspaceConfig:
    """
    Get workspace configuration singleton.

    Loaded once from .scicd/config.yaml and cached.

    Returns:
        WorkspaceConfig singleton instance
    """
    return _ConfigManager.get_workspace()


def get_base_task() -> TaskConfig:
    """
    Get base task configuration singleton.

    Loaded once from .scicd/config.yaml and cached.

    Returns:
        TaskConfig singleton instance (defaults)
    """
    return _ConfigManager.get_base_task()


def set_base_task(task: TaskConfig):
    """
    Manually set the base task configuration singleton.

    This is useful for applying global overrides (e.g., from the CLI)
    that should affect all subsequently created TaskConfig objects.

    Args:
        task: The new base TaskConfig instance.
    """
    _ConfigManager.set_base_task(task)


def get_task_config(**overrides) -> TaskConfig:
    """
    Get TaskConfig with optional runtime overrides.

    Starts with base defaults from WorkspaceConfig,
    then applies any overrides using the merge() method,
    and finally applies CLI-level overrides (highest priority).

    Args:
        **overrides: Runtime overrides (cpu=16, memory='64Gi', tags=['gpu'], etc.)

    Returns:
        TaskConfig instance with overrides applied
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
    """
    Reset all cached configuration.

    Primarily for testing - forces reload on next get_* call.
    """
    _ConfigManager.reset()


def cascading_config(
    filepath: Union[str, Path],
    root_key: Optional[Union[str, list[str]]] = None,
    config_key: str = "config",
    override_key: str = "override",
    **kwargs,
) -> dict:
    """
    Load a YAML file and apply cascading config logic based on kwargs.

    Args:
        filepath: Path to YAML file
        root_key: Optional key (or list of keys) to jump into before looking for config/override
        **kwargs: Parameters to match against override conditions

    Returns:
        Modified config dict after applying override rules
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
    """
    Apply cascading override logic to a config dict.

    Args:
        config: Base configuration dictionary
        override: List of override rules to apply
        **kwargs: Parameters to match against override conditions

    Returns:
        Modified config dict after applying matching override rules
    """
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
    Parses arbitrary CLI **kwargs. Keys matching TaskConfig fields are intercepted
    and applied directly to the global base task configuration. The remaining keys
    are returned as frontend-specific parameters.

    Returns:
        A dictionary containing only the frontend-specific parameters.
    """
    task_overrides_flat = {}
    frontend_params = {}

    valid_task_keys = set(TaskConfig.model_fields.keys()) # pylint: disable=no-member

    for k, v in kwargs.items():
        # Normalize key to use underscores for comparison (Cyclopts provides dashes)
        norm_k = k.replace("-", "_")
        root_key = norm_k.split(".")[0]

        if root_key in valid_task_keys:
            # Simple type casting for CLI values
            if isinstance(v, str):
                vl = v.lower()
                if vl in ("true", "yes", "1"):
                    v = True
                elif vl in ("false", "no", "0"):
                    v = False
                elif vl.isdigit():
                    v = int(v)

            task_overrides_flat[norm_k] = v
        else:
            frontend_params[k] = v

    # Nest the overrides
    task_overrides = nest_dict(task_overrides_flat)

    # Apply runtime defaults
    if task_overrides:
        rich.print(
            f"[bold blue]SciCD:[/bold blue] Storing global CLI overrides: {task_overrides}"
        )
        _ConfigManager.set_cli_overrides(task_overrides)

    return frontend_params
