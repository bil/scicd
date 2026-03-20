import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import luigi

from scicd.config import TaskConfig
from scicd.yamler import deep_update

class BaseAdapter(ABC):
    """
    Wraps a single unit of work.
    Provides a unified interface for extracting metadata and execution commands.
    """

    def __init__(self, work: Any) -> None:
        """
        Args:
            work: The underlying work object (luigi.Task, etc.)
        """
        self.work = work

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the task/rule name."""

    @property
    @abstractmethod
    def params(self) -> Dict[str, Any]:
        """Return serializable parameters as a dict."""

    @property
    @abstractmethod
    def cfg(self) -> Dict[str, Any]:
        """
        Extract task-specific resource configuration.
        
        Returns:
            Dict with resource configuration that can be merged into TaskConfig.
        """

    @property
    @abstractmethod
    def command(self) -> List[str]:
        """Generate the command to execute this work unit."""

    @property
    @abstractmethod
    def identifier(self) -> str:
        """Return a unique, deterministic identifier for this work unit."""


class LuigiAdapter(BaseAdapter):
    """
    Adapter for Luigi task instances.
    
    Configuration cascade (priority order):
    1. Default from .scicd/config.yaml task: section (lowest)
    2. task.resources() with integer assumptions (medium-high)
    3. task.scicd dict (highest)
    
    Integer assumptions for task.resources():
    - memory: megabytes (e.g., 8192 = 8GB)
    - disk: gigabytes (e.g. 2 = 2GB)
    - cpu: number of cores
    - gpu: number of gpus
    - time/timeout: minutes
    """

    def __init__(self, work: luigi.Task) -> None:
        """
        Args:
            work: A Luigi Task instance
        """
        super().__init__(work)
        self.work: luigi.Task

    def get_name(self) -> str:
        """
        Return the Luigi task family name.
        
        Returns:
            Task family
        """
        return self.work.get_task_family()

    @property
    def params(self) -> Dict[str, Any]:
        """
        Return task parameters as a serializable dict.
        
        Returns:
            Dictionary of parameter values (all converted to strings)
        """
        return self.work.to_str_params()

    @property
    def cfg(self) -> Dict[str, Any]:
        """
        Extract task-specific configuration for SciCD.

        Returns:
            Dict with resource configuration compatible with TaskConfig
            
        Examples:
            >>> class MyTask(luigi.Task):
            ...     def resources(self):
            ...         return {'cpu': 16, 'memory': 65536}  # MB
            ...     scicd = {'memory': '64Gi', 'tags': ['slurm']}
            >>> adapter = LuigiAdapter(MyTask())
            >>> config = adapter.cfg
            >>> config['cpu']
            16
            >>> config['memory']
            '64Gi'  # scicd dict overrides resources()
        """
        config: Dict[str, Any] = {}

        config = 

        # Level 2: Luigi native resources()
        resources = self.work.resources()
        if isinstance(resources, dict):
            config = deep_update(config, self._normalize_luigi_resources(resources))

        # Level 3: scicd dict attribute (highest priority)
        if hasattr(self.work, "scicd"):
            scicd_attr = getattr(self.work, "scicd")
            if isinstance(scicd_attr, dict):
                config = deep_update(config, scicd_attr)

        return config

    def _normalize_luigi_resources(self, resources: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Luigi's resources() dict to SciCD TaskConfig format.
        
        Integer assumptions:
        - cpu: cores (pass through)
        - memory: megabytes → convert to 'XMi' format
        - time/timeout: minutes → convert to 'Xm' format
        - gpu: count (pass through)
        
        Args:
            resources: Dict from task.resources()
            
        Returns:
            Normalized dict compatible with TaskConfig
            
        Examples:
            >>> _normalize_luigi_resources({'cpu': 4, 'memory': 8192, 'time': 90})
            {'cpu': 4, 'memory': '8192Mi', 'timeout': '90m'}
        """
        normalized: Dict[str, Any] = {}

        # CPU: direct pass-through (integer = cores)
        if "cpu" in resources:
            normalized["cpu"] = int(resources["cpu"])

        # Memory: assume MB if integer, pass through if string
        if "memory" in resources:
            mem = resources["memory"]
            # Assume megabytes
            normalized["memory"] = f"{int(mem)}Mi"

        # Time/Timeout: assume minutes if integer, pass through if string
        for time_key in ["time", "timeout"]:
            if time_key in resources:
                time_val = resources[time_key]
                # Assume minutes
                normalized["timeout"] = f"{int(time_val)}m"

        # GPU: direct pass-through if present
        if "gpu" in resources:
            normalized["gpu"] = int(resources["gpu"])

        # Disk: assume MB if integer, pass through if string
        if "disk" in resources:
            disk = resources["disk"]
            normalized["disk"] = f"{int(disk)}Gi"

        return normalized

    def get_command(self) -> List[str]:
        """
        Generate the command to run this Luigi task in CI/CD.
        
        Returns:
            Command array for subprocess execution
            
        Example:
            ['scicd', 'run-luigi', 
             '--module', 'workflow', 
             '--family', 'MyTask',
             '--params', '{"date": "2024-01-01"}']
        """
        return [
            "scicd",
            "run-luigi",
            "--module",
            self.work.__class__.__module__,
            "--family",
            self.get_name(),
            "--params",
            json.dumps(self.get_params()),
        ]

    def get_id(self) -> str:
        """
        Return Luigi's task_id (deterministic hash of family + params).
        
        Returns:
            Unique identifier (e.g., 'MyTask_2024_01_01_abc123')
        """
        return self.work.task_id

    def build_final_config(self, base_config: TaskConfig) -> TaskConfig:
        """
        Build final TaskConfig by merging base with task-specific config.
        
        Merge order:
        1. Base config from .scicd/config.yaml task: section
        2. Family override from task.FamilyName: section (applied externally)
        3. Task-specific config from this adapter
        
        Args:
            base_config: Base TaskConfig (from defaults + family override)
            
        Returns:
            Final TaskConfig with all overrides applied
            
        Example:
            >>> # In .scicd/config.yaml:
            >>> # task:
            >>> #   cpu: 1
            >>> #   memory: 8Gi
            >>> # task.Test:
            >>> #   cpu: 4
            >>> 
            >>> base = TaskConfig(cpu=4, memory='8Gi')  # After family override
            >>> task_config = adapter.build_final_config(base)
        """
        task_overrides = self.cfg()
        return base_config.merge(task_overrides)