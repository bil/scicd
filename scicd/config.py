"""
Module docstring.
"""

import re
import os

from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Literal, Tuple
from types import SimpleNamespace
from dataclasses import dataclass, field, fields, asdict


import yaml

from scicd.yamler import deep_update, load_yaml


@dataclass
class ConcurrencyConfig:
    """
    Configuration for task concurrency strategy.

    Defines how tasks are distributed across workers in the CI/CD pipeline.
    """

    method: Literal["biject", "slice", "queue"] = "biject"
    """
    Concurrency method to employ.
    - 'biject': Direct 1:1 mapping between tasks and jobs.
    - 'slice': Distributes M tasks across N static worker jobs.
    - 'queue': Workers pull tasks dynamically from a central queue.
    """

    workers: Optional[int] = None
    """
    Number of concurrent workers to spawn.
    Must be positive. Required for 'slice' and 'queue' methods.
    """

    def __post_init__(self):
        valid_methods = ["biject", "slice", "queue"]
        if self.method not in valid_methods:
            raise ValueError(
                f"method must be one of {valid_methods}, got '{self.method}'"
            )

        if self.method in ["slice", "queue"]:
            if self.workers is None:
                raise ValueError(
                    f"workers count is required when method is '{self.method}'"
                )
            if self.workers <= 0:
                raise ValueError(
                    f"workers must be a positive integer, got {self.workers}"
                )


@dataclass
class QueueConfig:
    """
    Configuration for queue-based dynamic concurrency.

    Describes the backend message broker used to coordinate task execution
    when using the 'queue' concurrency method.
    """

    platform: Optional[Literal["gcp"]] = None
    """
    Message broker backend.
    Currently supported: 'gcp' (Pub/Sub).
    Planned support: 'aws' (SQS), 'redis'.
    """

    topic: str = ""
    """
    Queue/Topic name for the message broker.
    For GCP: The Pub/Sub topic ID.
    """

    subscription: str = ""
    """
    Subscription or consumer group identifier.
    For GCP: The Pub/Sub subscription ID.
    """

    config: Dict[str, Any] = field(default_factory=dict)
    """
    Extra platform-specific settings.
    Example (GCP): {'project': 'gcp-project-id'}
    """

    def __post_init__(self):
        if self.platform is None:
            # Note: This is checked in TaskConfig if method='queue',
            # but we can enforce it here too if not None.
            pass
        elif self.platform not in ["gcp"]:
            raise ValueError(
                f"Currently only 'gcp' platform is supported for queues, got '{self.platform}'"
            )
        else:
            if not self.topic:
                raise ValueError("queue.topic cannot be empty")
            if not self.subscription:
                raise ValueError("queue.subscription cannot be empty")


@dataclass
# pylint: disable=too-many-instance-attributes
class TaskConfig:
    """
    Unified configuration for a single task within SciCD.

    Aggregates resource requirements, runtime environment, and platform-specific
    overrides. This is the source of truth for generating CI/CD job definitions.
    """

    # ===== Executor Selection =====
    tags: List[str] = field(default_factory=list)
    """
    Targeted runner/executor tags.
    All tags must be present on the CI/CD runner for this task to be scheduled.
    """

    # ===== Resources =====
    cpu: int = 1
    """
    Number of CPU cores requested.
    Must be a positive integer.
    """

    memory: str = "8Gi"
    """
    RAM allocation.
    Supported units: K/Ki, M/Mi, G/Gi, T/Ti (with optional 'B' suffix).
    Default: '8Gi'.
    """

    image: Optional[str] = None
    """
    Container image to use for this task.
    """

    disk: Optional[str] = None
    """
    Ephemeral disk storage allocation.
    Same unit support as 'memory'.
    """

    gpu: Optional[int] = None
    """
    Number of GPUs requested.
    Must be positive if provided.
    """

    gpu_type: Optional[str] = None
    """
    Specific GPU architecture or model (e.g., 'a100', 't4').
    Usage depends on CI/CD executor capability.
    """

    # ===== Scheduling/Placement =====
    partition: Optional[str] = None
    """
    Queue or partition name (e.g., Slurm partitions, specialized runner groups).
    """

    # ===== Time Constraints =====
    timeout: str = "60m"
    """
    Maximum allowed runtime for the task.
    Supports GitLab format: '1h', '45m', '1h 30m'.
    """

    # ===== Reliability =====
    retry: int = 0
    """
    Number of retry attempts on job failure.
    Must be non-negative.
    """

    # ===== Container/Runtime =====
    image: Optional[str] = None
    """
    Docker/Singularity image URL to use for execution.
    """

    python_cmd: str = "python3"
    """
    Python executable name or absolute path within the container/environment.
    """

    # ===== Environment Variables =====
    variables: Dict[str, Union[str, int, float]] = field(default_factory=dict)
    """
    Standard environment variables to inject into the task environment.
    """

    # ===== Executor-Specific Variables =====
    executor_config: Dict[str, Union[str, int, float]] = field(default_factory=dict)
    """
    Backend-specific variables passed directly to the executor (e.g., SLURM_* vars).
    """

    # ===== CI/CD Platform Config =====
    cicd_config: Dict[str, Any] = field(default_factory=dict)
    """
    Direct passthrough to the CI/CD YAML configuration (e.g., 'interruptible: true').
    """

    # ===== Nested Configurations =====
    concurrency: Union[ConcurrencyConfig, Dict[str, Union[str, int]]] = field(
        default_factory=ConcurrencyConfig
    )
    """
    Task-level concurrency strategy.
    """

    queue: Union[QueueConfig, Dict[str, Any], None] = field(default_factory=QueueConfig)
    """
    Messaging queue settings, only relevant if concurrency.method='queue'.
    """

    def __post_init__(self):
        """
        Validate resource constraints and auto-convert nested dictionaries.
        """
        if self.cpu <= 0:
            raise ValueError(f"cpu must be positive, got {self.cpu}")

        if self.retry < 0:
            raise ValueError(f"retry cannot be negative, got {self.retry}")

        if self.gpu is not None and self.gpu <= 0:
            raise ValueError(f"gpu must be positive if specified, got {self.gpu}")

        # Auto-convert concurrency dict to ConcurrencyConfig
        if isinstance(self.concurrency, dict):
            self.concurrency = ConcurrencyConfig(**self.concurrency)

        # Auto-convert queue dict to QueueConfig
        if isinstance(self.queue, dict):
            self.queue = QueueConfig(**self.queue)

        # Validate that queue config exists if using queue concurrency
        if self.concurrency.method == "queue":
            if self.queue is None:
                raise ValueError(
                    "queue configuration is required when concurrency.method='queue'"
                )
            if (
                self.queue.platform is None
                or not self.queue.subscription
                or not self.queue.topic
            ):
                raise ValueError(
                    "Queue must be fully configured (platform, subscription, topic) "
                    "when concurrency.method='queue'"
                )

        # Validate resource formats
        try:
            self.memory = self.validate_memory(self.memory)
        except ValueError as e:
            raise ValueError("Invalid memory format") from e

        if self.disk:
            try:
                self.disk = self.validate_memory(self.disk)
            except ValueError as e:
                raise ValueError("Invalid disk format") from e

        try:
            self.timeout = self.validate_time(self.timeout)
        except ValueError as e:
            raise ValueError("Invalid timeout format") from e

    @property
    def memory_mb(self) -> int:
        return self._parse_memory_to_mb(self.memory)

    @property
    def disk_mb(self) -> Optional[int]:
        return self._parse_memory_to_mb(self.disk)

    @property
    def timeout_minutes(self) -> int:
        return self._parse_time_to_minutes(self.timeout)

    @classmethod
    def _split_memory_str(cls, mem_str: str) -> Tuple[int, str]:
        pattern = r"^(\d+)\s*([KMGT])(i)?$"
        match = re.match(pattern, mem_str)
        if not match:
            raise ValueError(f"Could not match memory string: {mem_str}")

        value = int(match.group(1))
        unit = match.group(2)
        if mem_str.endswith("i"):
            unit += match.group(3)
        return (value, unit)

    @classmethod
    def _split_time_str(cls, time_str: str) -> List[str]:
        # Pattern: one or more "<number><unit>" groups
        pattern = r"(\d+)\s*([hms])"
        matches = re.findall(pattern, time_str.lower())
        if not matches:
            raise ValueError(f"Could not split time string {time_str}")

        out_strs = ["".join(match) for match in matches]
        return out_strs

    @classmethod
    def validate_time(cls, time: Union[int, str]) -> str:
        """
        Converts (or validates) argument as a Gitlab-style time string.

        Takes time specified as integer minutes or as a string".
        """
        if isinstance(time, int):
            return f"{time}m"
        time = time.strip()

        # Pattern: one or more "<number><unit>" groups
        try:
            time_list = cls._split_time_str(time)
        except ValueError as e:
            raise ValueError(
                f"Invalid time format: '{time}'. "
                "Expected format: '1h', '30m', '1h 30m', etc."
            ) from e
        time = " ".join(time_list)
        return time

    @classmethod
    def validate_memory(cls, mem: Union[int, str]) -> str:
        """Check if memory string has valid format."""
        if isinstance(mem, int):
            return f"{mem}Mi"
        if mem is None:
            return mem
        mem = mem.strip()
        valid_units = ["Ki", "Mi", "Gi", "Ti", "K", "M", "G", "T"]
        valid = True
        if mem.endswith(("B", "b")):  # take off final b
            mem = mem[:-1]

        # Ensure we have a valid suffix
        if not any(mem.endswith(unit) for unit in valid_units):
            valid = False

        # Ensure we have an integer/string group
        if valid:
            try:
                cls._split_memory_str(mem)
            except ValueError:
                valid = False

        if valid:
            return mem

        raise ValueError(
            f"{mem} cannot be properly formatted!",
            "Expected format: <number><unit> (e.g., '16Gi', '32000Mi')",
            "Valid units: [K/Ki, M/Mi, G/Gi, T/Ti]",
        )

    @classmethod
    def _parse_memory_to_mb(cls, mem_str: Optional[str]) -> Optional[int]:
        """
        Parse memory string to megabytes.

        Supports: K/Ki, M/Mi, G/Gi, T/Ti
        Examples: '8Gi', '8192Mi', '8G', '8000M', '8GB', '8GiB'

        Note: Treats binary (Ki/Mi/Gi/Ti) and decimal (K/M/G/T) as equivalent
        for simplicity (ignores ~7% difference).
        """
        if mem_str is None:
            return None
        mem_str = mem_str.strip()

        value, unit = cls._split_memory_str(mem_str)
        # We let the decimal/binary conversion be imprecise
        base_unit = unit.rstrip("i").upper()

        # Convert to MB (treating binary and decimal as same)
        multipliers = {
            "K": 1 / 1024,  # KB to MB
            "M": 1,  # MB to MB
            "G": 1024,  # GB to MB
            "T": 1024 * 1024,  # TB to MB
        }

        mb = value * multipliers[base_unit]
        return int(mb)

    @classmethod
    def _parse_time_to_minutes(cls, time_str: str) -> int:
        """
        Parse time string to minutes.

        Supports GitLab formats: '1h', '30m', '90s', '1h 30m', '1h 30m 10s'
        """
        time_str = time_str.strip()

        # Pattern: one or more "<number><unit>" groups
        pattern = r"(\d+)\s*([hms])"
        matches = re.findall(pattern, time_str.lower())

        if not matches:
            raise ValueError(
                f"Invalid time format: '{time_str}'. "
                "Expected format: '1h', '30m', '1h 30m', etc."
            )

        total_minutes = 0
        for value, unit in matches:
            value = int(value)
            if unit == "h":
                total_minutes += value * 60
            elif unit == "m":
                total_minutes += value
            elif unit == "s":
                total_minutes += value // 60  # Round down to minutes

        return total_minutes

    def merge(self, overrides: Dict[str, Any]) -> "TaskConfig":
        """
        Create a new TaskConfig with overrides applied.

        Handles nested merging for concurrency and queue configs.
        Also handles type conversion for string values coming from the CLI.

        Args:
            overrides: Dictionary of fields to override

        Returns:
            New TaskConfig instance with merged values
        """
        current = asdict(self)
        fields_map = {f.name: f.type for f in fields(self)}

        # Cast strings from CLI to correct types in the overrides dict
        casted_overrides = overrides.copy()
        for k, v in casted_overrides.items():
            if k in fields_map:
                target_type = fields_map[k]
                try:
                    if target_type == int or target_type == Optional[int]:
                        casted_overrides[k] = int(v)
                    elif target_type == float or target_type == Optional[float]:
                        casted_overrides[k] = float(v)
                    elif target_type == bool or target_type == Optional[bool]:
                        casted_overrides[k] = str(v).lower() in ("true", "1", "yes")
                except (ValueError, TypeError):
                    pass

        out = deep_update(current, casted_overrides)
        return TaskConfig(**out)


def _dict_to_namespace(d: Any) -> Any:
    """Recursively convert dict to namespace for dot-access."""
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in d.items()})
    elif isinstance(d, list):
        return [_dict_to_namespace(item) for item in d]
    else:
        return d


@dataclass
class RemoteConfig:
    """
    Configuration for remote data synchronization.

    SciCD uses this to automatically generate 'pull' and 'push' steps
    within CI/CD jobs, ensuring data persistence across ephemeral workers.
    """

    root: Optional[str] = None
    """
    Local base directory for synchronization.
    Only files within this directory will be synced to/from the remote.
    """

    url: Optional[str] = None
    """
    Remote storage destination.
    Format depends on protocol (e.g., 's3://my-bucket/path' or 'rclone-remote:path').
    """

    protocol: Literal["rclone", "https"] = "rclone"
    """
    Transfer protocol to use.
    - 'rclone': High-performance sync for various backends (S3, GCS, SFTP).
    - 'https': Direct download/upload via HTTP.
    """

    flags: List[str] = field(default_factory=list)
    """
    Additional CLI flags passed to the underlying sync tool (e.g., ['--transfers=16']).
    """

    pull_inputs: bool = False
    """
    If True, SciCD generates a 'before_script' step to pull data from remote
    before the task begins.
    """

    push_outputs: bool = False
    """
    If True, SciCD generates an 'after_script' step to push local results
    to remote storage upon task completion.
    """

    def __post_init__(self):
        valid_protocols = ["rclone", "https"]
        if self.protocol not in valid_protocols:
            raise ValueError(
                f"protocol must be one of {valid_protocols}, got '{self.protocol}'"
            )

        if self.pull_inputs or self.push_outputs:
            if not self.url:
                raise ValueError(
                    "remote.url is mandatory when pull_inputs or push_outputs is enabled"
                )
            if not self.root:
                raise ValueError(
                    "remote.root is mandatory when pull_inputs or push_outputs is enabled"
                )


@dataclass
class RepositoryConfig:
    """
    Configuration for the source control and CI/CD platform.

    Contains the connection details and platform-specific settings
    for generating and deploying the CI/CD pipeline.
    """

    platform: Literal["gitlab", "github"] = "gitlab"
    """CI/CD platform targeted for pipeline generation."""

    url: str = ""
    """
    Base URL of the repository (e.g., 'https://gitlab.com').
    """

    project: str = ""
    """
    Full project or repository path.
    - GitLab: 'namespace/project-name'
    - GitHub: 'owner/repo-name'
    """

    cicd: Dict[str, Any] = field(default_factory=dict)
    """
    Platform-specific top-level configuration keys.
    Passed through directly to the root of the generated YAML.
    """

    def __post_init__(self):
        valid_platforms = ["gitlab", "github"]
        if self.platform not in valid_platforms:
            raise ValueError(
                f"platform must be one of {valid_platforms}, got '{self.platform}'"
            )

        if not self.url:
            raise ValueError("repository.url is mandatory")
        if not self.project:
            raise ValueError("repository.project is mandatory")


@dataclass
class WorkspaceConfig:
    """
    Root configuration for a SciCD project workspace.

    Defines the environment where SciCD operates, including source control
    integration, remote storage sync, and custom user extensions.
    """

    repository: Union[RepositoryConfig, Dict[str, Any]] = field(
        default_factory=RepositoryConfig
    )
    """
    Platform configuration (GitLab/GitHub).
    Required for CI/CD pipeline generation.
    """

    remote: Union[RemoteConfig, Dict[str, Any], None] = None
    """
    Global remote storage defaults.
    If specified, provides the fallback configuration for task-level sync.
    """

    user: Union[Dict[str, Any], SimpleNamespace] = field(default_factory=dict)
    """
    Extensible user-defined configuration.
    Recursively converted to a SimpleNamespace for convenient dot-notation access.
    """

    def __post_init__(self):
        """
        Auto-convert nested dictionaries to structured dataclasses.
        """
        # Convert repository dict to dataclass
        if isinstance(self.repository, dict):
            self.repository = RepositoryConfig(**self.repository)

        # Convert remote dict to dataclass
        if self.remote is not None and isinstance(self.remote, dict):
            self.remote = RemoteConfig(**self.remote)

        # Convert user dict to namespace for dot-access
        if isinstance(self.user, dict):
            self.user = _dict_to_namespace(self.user)


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


def load_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
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

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config or {}


class _ConfigManager:
    """Internal config manager."""

    _workspace: Optional[WorkspaceConfig] = None
    _base_task_config: Optional[TaskConfig] = None

    @classmethod
    def get_workspace(cls) -> WorkspaceConfig:
        """Get workspace singleton."""
        if cls._workspace is None:
            config_dict = load_config()
            # The 'task' key provides defaults for TaskConfig, not WorkspaceConfig.
            ws_dict = {k: v for k, v in config_dict.items() if k != "task"}
            cls._workspace = WorkspaceConfig(**ws_dict)
        return cls._workspace

    @classmethod
    def get_base_task_config(cls) -> TaskConfig:
        """Get base task config singleton (defaults from task: section)."""
        if cls._base_task_config is None:
            config_dict = load_config()
            task_dict = config_dict.get("task", {})
            cls._base_task_config = TaskConfig(**task_dict)
        return cls._base_task_config

    @classmethod
    def set_runtime_defaults(cls, overrides: Dict[str, Any]):
        """Inject global overrides that apply to all TaskConfig instances."""
        cls._base_task_config = cls.get_base_task_config().merge(overrides)

    @classmethod
    def reset(cls):
        """Reset all cached config (for testing)."""
        cls._workspace = None
        cls._base_task_config = None


def get_workspace() -> WorkspaceConfig:
    """
    Get workspace configuration singleton.

    Loaded once from .scicd/config.yaml and cached.

    Returns:
        WorkspaceConfig singleton instance
    """
    return _ConfigManager.get_workspace()


def get_task_config(**overrides) -> TaskConfig:
    """
    Get TaskConfig with optional runtime overrides.

    Starts with base defaults from .scicd/config.yaml task: section,
    then applies any overrides using the merge() method.

    Args:
        **overrides: Runtime overrides (cpu=16, memory='64Gi', tags=['gpu'], etc.)

    Returns:
        TaskConfig instance with overrides applied

    Examples:
        >>> # Get base defaults
        >>> config = get_task_config()
        >>> config.cpu
        1

        >>> # Override specific fields
        >>> config = get_task_config(cpu=16, memory='64Gi')
        >>> config.cpu
        16

        >>> # Override nested fields
        >>> config = get_task_config(
        ...     concurrency={'method': 'queue', 'workers': 10},
        ...     tags=['slurm', 'gpu']
        ... )
    """
    # Start with cached base defaults
    base_config = _ConfigManager.get_base_task_config()

    # Apply overrides if provided
    if overrides:
        return base_config.merge(overrides)

    return base_config


def reset_config():
    """
    Reset all cached configuration.

    Primarily for testing - forces reload on next get_* call.
    """
    _ConfigManager.reset()


def cascading_config(
    filepath: str | Path,
    config_key: str = "config",
    override_key: str = "override",
    **kwargs,
) -> dict:
    """
    Load a YAML file and apply cascading config logic based on kwargs.

    Args:
        filepath: Path to YAML file containing 'config' and 'override' keys
        **kwargs: Parameters to match against override conditions

    Returns:
        Modified config dict after applying override rules
    """
    path = Path(filepath)

    if not path.exists():
        print(f"Tried to load parameters file at {str(path)} but it doesn't exist!")
        return {}

    cfg = load_yaml(path)

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
