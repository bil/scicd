"""
Module docstring.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import luigi

import scicd.config
import scicd.task
from scicd.yamler import deep_update, slugify


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
    def cfg(self) -> scicd.config.TaskConfig:
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

    @property
    def name(self) -> str:
        """
        Return the Luigi task family name.

        Returns:
            Task family
        """
        return self.work.task_family

    @property
    def params(self) -> Dict[str, Any]:
        """
        Return task parameters as a serializable dict.

        Returns:
            Dictionary of parameter values (all converted to strings)
        """
        return self.work.param_kwargs

    @property
    def cfg(self) -> scicd.config.TaskConfig:
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
            >>> config.cpu
            16
            >>> config.memory
            '64Gi'  # scicd dict overrides resources()
        """
        if hasattr(self.work, "task_config"):
            return self.work.task_config

        return scicd.task.get_task_config(self.work)

    @property
    def command(self) -> List[str]:
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
            self.name,
            "--params",
            json.dumps(self.params),
        ]

    @property
    def identifier(self) -> str:
        """
        Return Luigi's task_id (deterministic hash of family + params).

        Returns:
            Unique identifier (e.g., 'MyTask_2024_01_01_abc123')
        """
        params = self.work.to_str_params(only_significant=True)
        params_str = "_".join([f"{k}_{v}" for k, v in params.items()])
        return slugify(f"{self.name}_{params_str}")[:64]
