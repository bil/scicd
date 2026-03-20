import re

from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Literal, Tuple
from types import SimpleNamespace
from dataclasses import dataclass, field, asdict
from abc import ABC


import yaml

from scicd.yamler import deep_update, load_yaml


@dataclass
class ConcurrencyConfig:
    """Configuration for task concurrency strategy."""

    method: Literal["biject", "slice", "queue"] = "biject"
    """
    Concurrency method.
    Options:
        'biject' (1:1 job mapping)
        'slice' (N workers for M tasks)
        'queue' (N workers pull from queue)
    """

    workers: Optional[int] = None
    """
    Number of workers for 'slice' or 'queue' methods.
    Required for slice/queue, ignored for biject.
    """

    def __post_init__(self):
        if self.method in ["slice", "queue"] and self.workers is None:
            raise ValueError(f"workers required when method='{self.method}'")


@dataclass
class QueueConfig:
    """Configuration for queue-based concurrency."""

    platform: Optional[Literal["gcp"]] = None
    """
    Queue backend platform.
    Options: 'gcp'
    Pending: 'aws', 'azure', 'redis'
    """

    topic: str = ""
    """Topic/stream name."""

    subscription: str = ""
    """Subscription/consumer group name."""

    config: Dict[str, Any] = field(default_factory=dict)
    """
    Platform-specific configuration.
    Examples:
        - GCP: {'project': 'my-project'}
        - AWS: {'region': 'us-west-2', 'account_id': '123456789'}
        - Redis: {'host': 'localhost', 'port': 6379}
    """

    def __post_init__(self):
        if not self.topic:
            raise ValueError("queue.topic is required")
        if not self.subscription:
            raise ValueError("queue.subscription is required")


@dataclass
class TaskConfig:
    """
    Configuration for a single task in the workflow.

    This represents the uniform configuration extracted from work definitions
    and merged with defaults from .scicd/config.yaml.
    """

    # ===== Executor Selection =====
    tags: List[str] = field(default_factory=list)
    """
    Tags used to match task to an executor (all tags must match).
    Sets executor specific environmnet variables.
    Shoud align with how CI/CD platform uses tags for runner selection.
    """

    # ===== Resources =====
    cpu: int = 1
    """Number of CPU cores."""

    memory: str = "8Gi"
    disk: Optional[str] = None
    """
    Memory allocation.
    Can be:
    - int: megabytes (e.g., 500 = 0.5GB)
    - str: with units (e.g., '8Gi', '8192Mi', '8G', '8000M')
    Supported units: K/Ki, M/Mi, G/Gi, T/Ti (with optional 'B' suffix)
    """

    gpu: Optional[int] = None
    """Number of GPUs. None means no GPU."""
    gpu_type: Optional[str] = None
    """
    Specific GPU type/model.
    Examples: 'a100', 'v100', 'nvidia-tesla-t4'
    """

    # ===== Scheduling/Placement =====
    partition: Optional[str] = None
    """
    Partition/queue name, used in HPC clusters.
    """

    # ===== Time Constraints =====
    timeout: str = "60m"
    """
    Maximum runtime as a string.
    Uses GitLab format (e.g., '1h', '30m', '1h 30m')
    """

    # ===== Reliability =====
    retry: int = 0
    """Number of times to retry on failure."""

    # ===== Container/Runtime =====
    image: Optional[str] = None
    """Container image to use."""

    python_cmd: str = "python3"
    """Python command for execution."""

    # ===== Environment Variables =====
    variables: Dict[str, Union[str, int, float]] = field(default_factory=dict)
    """Environment variables to set in CI/CD job."""

    # ===== Executor-Specific Variables =====
    executor_config: Dict[str, Union[str, int, float]] = field(default_factory=dict)
    """
    Executor-specific environmnet variables on top of what will be auto-generated.
    Examples:
        - {'SLURM_GRES': 'gpu:a100:4', 'SLURM_QOS': 'high'}
    """

    # ===== CI/CD Platform Config =====
    cicd_config: Dict[str, Any] = field(default_factory=dict)
    """
    CI/CD job configuration (pass-through directly to job YAML).
    For GitLab: resource_group, interruptible, etc.
    """

    # ===== Nested Configurations =====
    concurrency: Union[ConcurrencyConfig, Dict[str, Union[str, int]]] = field(
        default_factory=ConcurrencyConfig
    )
    """Concurrency configuration."""

    queue: Union[QueueConfig, Dict[str, Any], None] = field(default_factory=QueueConfig)
    """Queue configuration (only needed if concurrency.method='queue')."""

    def __post_init__(self):
        """
        Auto-convert nested dicts to dataclasses and validate configuration.
        """
        # Auto-convert concurrency dict to ConcurrencyConfig
        if isinstance(self.concurrency, dict):
            self.concurrency = ConcurrencyConfig(**self.concurrency)

        # Auto-convert queue dict to QueueConfig
        if isinstance(self.queue, dict):
            self.queue = QueueConfig(**self.queue)

        # Validate that queue config exists if using queue concurrency
        if self.concurrency.method == "queue" and (
            self.queue.platform is None
            or self.queue.subscription is None
            or self.queue.topic is None
        ):
            raise ValueError(
                "Queue must be fully configured when concurrency.method='queue'"
            )

        # Validate memory format
        try:
            self.memory = self.validate_memory(self.memory)
        except ValueError as e:
            raise ValueError("`memory` invalid!") from e

        try:
            self.disk = self.validate_memory(self.disk)
        except ValueError as e:
            raise ValueError("`disk` invalid!") from e

        try:
            self.timeout = self.validate_time(self.timeout)
        except ValueError as e:
            raise ValueError("`timeout` invalid!") from e

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
            return f"{mem}M"
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

        Args:
            overrides: Dictionary of fields to override

        Returns:
            New TaskConfig instance with merged values
        """
        current = asdict(self)
        overrides = overrides.copy()
        out = deep_update(current, overrides)
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
    Remote storage configuration.

    SciCD uses this to generate sync jobs in the CI/CD pipeline.
    """

    root: Optional[str] = None
    """
    Local root directory for remote sync.

    Example:
        root: "/workspace/outputs"
        url: "s3://bucket/outputs"
        
    Files in /workspace/outputs/results/file.txt will sync to s3://bucket/outputs/results/file.txt
    Files outside /workspace/outputs are ignored.
    """

    url: Optional[str] = None
    """Remote storage URL (e.g., 'bilgd:bucket/path' for rclone, 's3://bucket' for S3)"""

    protocol: Literal["rclone", "https"] = "rclone"  # future: rsync?
    """Protocol for remote sync."""

    flags: List[str] = field(default_factory=list)
    """Additional flags for the sync command."""

    pull_inputs: bool = False
    """
    Whether to pull required artifacts from remote upon task start.
    """

    push_outputs: bool = False
    """
    Whether to push to remote after completion of each task.
    """

    def __post_init__(self):
        if self.pull_inputs or self.push_outputs:
            if not self.url:
                raise ValueError(
                    "remote.url is required when pull_inputs or push_outputs is enabled"
                )
            if not self.root:
                raise ValueError(
                    "remote.root is required when pull_inputs or push_outputs is enabled"
                )


@dataclass
class RepositoryConfig:
    """Configuration for repository and CI/CD platform."""

    platform: Literal["gitlab", "github"] = "gitlab"
    """CI/CD platform."""

    url: str = ""
    """Repository URL."""

    project: str = ""
    """
    Project identifier.
    For GitLab: 'group/project' or 'user/project'
    For GitHub: 'owner/repo'
    """

    cicd: Dict[str, Any] = field(default_factory=dict)
    """
    Platform-specific CI/CD configuration (pass-through).
    For GitLab: workflow, default, stages, etc.
    For GitHub: on, env, permissions, etc.
    """

    def __post_init__(self):
        if self.platform not in ["gitlab", "github"]:
            raise ValueError(
                f"Invalid platform: {self.platform}. Must be 'gitlab' or 'github'"
            )

        if not self.url:
            raise ValueError("repository.url is required")
        if not self.project:
            raise ValueError("repository.project is required")


class Singleton(ABC):
    _instance = None
    _initialized = None

    def __new__(cls, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, **kwargs):
        if not self._initialized:
            self._first_init(**kwargs)
            self.__class__._initialized = True

    def _first_init(self, **kwargs):
        pass


@dataclass
class WorkspaceConfig(Singleton):
    """
    Workspace configuration.

    Core configuration used by SciCD for CI/CD pipeline generation:
    - repository: Where to generate the pipeline
    - remote: Optional remote storage sync (SciCD generates sync jobs)

    User configuration for utilities and extensions:
    - user: Free-form configuration!
    """

    repository: Union[RepositoryConfig, Dict[str, Any]] = field(
        default_factory=RepositoryConfig
    )
    """Repository and CI/CD platform configuration (core, required)."""

    remote: Union[RemoteConfig, Dict[str, Any], None] = None
    """
    Remote storage configuration (core, optional).
    
    If provided, SciCD generates sync jobs in the pipeline:
    - pull_on_start: Generates before_script to pull data
    - push_on_completion: Generates after_script to push results
    """

    user: Union[Dict[str, Any], SimpleNamespace] = field(default_factory=dict)
    """
    Free-form user configuration
    """

    def __post_init__(self):
        """Auto-convert nested dicts to dataclasses and namespaces."""
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


def load_config(config_path: str = ".scicd/config.yaml") -> Dict[str, Any]:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to config file (default: .scicd/config.yaml)

    Returns:
        Raw configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

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
            config_dict = load_config(".scicd/config.yaml")
            cls._workspace = WorkspaceConfig(**config_dict)
        return cls._workspace

    @classmethod
    def get_base_task_config(cls) -> TaskConfig:
        """Get base task config singleton (defaults from task: section)."""
        if cls._base_task_config is None:
            config_dict = load_config(".scicd/config.yaml")
            task_dict = config_dict.get("task", {})
            cls._base_task_config = TaskConfig(**task_dict)
        return cls._base_task_config

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


def cascading_config_from_file(filepath: str | Path, **kwargs) -> dict:
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

    config = cfg.get("config", {})
    override = cfg.get("override", [])

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


# def cascading_config(family: str, **kwargs):
#     """
#     Parameter-dependent overwrite of insignificant Task configuration.
#     These are basically "insignificant" (non-identifying) parameters.
#     """
#     path = SciCDConfig().workspace_config().path_parameters
#     path = yml_suffix(path)  # if a suffix wasn't provided, tries to infer!

#     # Not using feature
#     if path is None:
#         return {}

#     if not Path(path).exists():
#         print(f"Tried to load parameters file at {str(path)} but didn't exist!")
#         return {}

#     cfg = load_yaml(path)

#     # Nothing provided for this Task
#     if family not in cfg:
#         return {}

#     # Override default config
#     cfg = cfg[family]
#     config = cfg.get("config", {})
#     override = cfg.get("override", [])
#     # Cascading logic
#     return specify(config, override, **kwargs)


# class SciCDConfig(Singleton):
#     """Singleton configuration manager for SciCD."""

#     def __init__(self, **overrides):
#         super().__init__(**overrides)
#         if overrides:
#             self.override(**overrides)

#     def __repr__(self) -> str:
#         """Provides a pretty-printed dictionary representation for the CLI."""
#         return pprint.pformat(self.config_dict, indent=2, sort_dicts=False)

#     def _expand_env_vars(self, data: Any) -> Any:
#         """Recursively expand environment variables in strings, lists, and dicts."""
#         if isinstance(data, dict):
#             return {k: self._expand_env_vars(v) for k, v in data.items()}
#         elif isinstance(data, list):
#             return [self._expand_env_vars(i) for i in data]
#         elif isinstance(data, str):
#             return os.path.expandvars(data)
#         return data

#     def _load_toml_state(self):
#         """Loads pyproject.toml into the base state."""
#         toml_path = Path("pyproject.toml")
#         if toml_path.exists():
#             with open(toml_path, "rb") as f:
#                 pyproject_data = self._expand_env_vars(tomli.load(f))
#                 self.config_dict = pyproject_data.get("tool", {}).get("scicd", {})

#     def override(self, **kwargs):
#         """
#         Only permits overrides for TaskConfig settings.
#         Workspace settings (paths, GitLab URLs) are protected to ensure
#         consistency between local DAG generation and CI/CD execution.
#         """
#         task_overrides = {}

#         for key, val in kwargs.items():
#             if key.startswith("scicd_"):
#                 # Can override with scicd namespace
#                 # Or with direct key!
#                 key = key[len("scicd_") :]
#             # Handle specific task overrides: --scicd-tasks-MyTask-cpu="4"
#             if key.startswith("task_"):
#                 remainder = key[len("task_") :]
#                 parts = remainder.split("_", 1)  # Expect <Task>_<key>
#                 if len(parts) == 2:  # we should
#                     family, option = parts
#                     # We only allow overriding fields that exist in TaskConfig
#                     if option in fields(TaskConfig):
#                         task_overrides.setdefault("task", {}).setdefault(family, {})[
#                             option
#                         ] = val
#                     else:
#                         print(
#                             f"Cannot override workspace configuration {option} for {family}!\n",
#                             f"Set {option} in pyproject.toml under [tool.scicd] namespace.",
#                         )

#             # Handle global task defaults (e.g. cpu)
#             else:
#                 option = (
#                     key  # we're not in task namespace, so we are using key directly
#                 )
#                 # Block workspace-only keys from being overridden at CLI
#                 if option in fields(TaskConfig):
#                     task_overrides[option] = val
#                 else:
#                     print(
#                         f"Ignoring override for protected workspace setting: {option}\n",
#                         f"Set {option} in pyproject.toml under [tool.scicd] namespace.",
#                     )

#         # Update global state with validated task overrides only
#         task_overrides = self._expand_env_vars(task_overrides)
#         self.config_dict = deep_update(self.config_dict, task_overrides)

#     def workspace_config(self) -> WorkspaceConfig:
#         """
#         Returns only the global workspace settings from the root of pyproject.toml.
#         Ignores any task-specific overrides.
#         """

#         return self._build_dataclass(WorkspaceConfig, self.config_dict)

#     def family_config(self, family: str = None) -> TaskConfig:
#         """
#         Returns the resolved execution settings for a specific task family.
#         Applies task-specific overrides on top of the root defaults.
#         """
#         param = deepcopy(self.config_dict)
#         tasks_config = param.pop("task", {})

#         # Apply the specific family overrides
#         if family and family in tasks_config:
#             param = deep_update(param, tasks_config[family])

#         return self._build_dataclass(TaskConfig, param)

#     def _build_dataclass(
#         self,
#         config_class: type[WorkspaceConfig] | type[TaskConfig],
#         config_dict: dict,
#     ) -> WorkspaceConfig | TaskConfig:
#         """Helper to enforce strict dataclass schema on a dictionary."""
#         valid_keys = {f.name for f in fields(config_class)}
#         filtered_config = {k: v for k, v in config_dict.items() if k in valid_keys}
#         return config_class(**filtered_config)


# def get_config(family: str = None, **kwargs):
#     """
#     CLI utility to inspect the active configuration state.

#     Args:
#         family (str, optional): The Luigi task family to inspect. If None,
#                                 returns the raw global config state.
#         **kwargs: Variadic overrides (e.g., scicd_image="ubuntu:latest").
#     """
#     cfg = SciCDConfig()

#     # Apply any CLI overrides first so the user sees the final state
#     if kwargs:
#         cfg.override(**kwargs)

#     # Return the dataclass if they asked for a specific task, else the raw singleton instance
#     if family:
#         cfg = cfg.family_config(family)

#     return str(cfg)


# def get_workspace():
#     return SciCDConfig().workspace_config()


# def get_family(family: str = None, **kwargs):
#     return SciCDConfig(**kwargs).family_config(family)
