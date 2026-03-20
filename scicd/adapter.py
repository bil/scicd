import json

from abc import ABC, abstractmethod
from typing import Any, Dict, List

import luigi

from scicd.yamler import deep_update


class Adapter(ABC):
    """
    Wraps a single unit of work (Luigi task instance).
    Provides an interface for extracting metadata and execution commands.
    """

    def __init__(self, work_unit: Any) -> None:
        """
        Args:
            work_unit: The underlying work object (luigi.Task)
        """
        self.work_unit = work_unit

    @abstractmethod
    def get_family(self) -> str:
        """Return the task/rule family name."""

    @abstractmethod
    def get_params(self) -> Dict[str, Any]:
        """Return serializable parameters as a dict."""

    @abstractmethod
    def get_config(self) -> Dict[str, Any]:
        """
        Extract resource configuration.

        Returns:
            Dict with keys like 'cpu', 'memory', 'tags', 'gpu', etc.
        """

    @abstractmethod
    def get_run_command(self) -> List[str]:
        """
        Generate the command to execute this work unit.

        Returns:
            Command as list of strings (e.g., ['scicd', 'run-luigi', ...])
        """

    @abstractmethod
    def get_unique_id(self) -> str:
        """
        Return a unique identifier for this work unit.

        Should be deterministic based on family + parameters.
        """

class LuigiAdapter(Adapter):
    """Adapter for a Luigi task instance."""

    def __init__(self, work_unit: luigi.Task) -> None:
        """
        Args:
            work_unit: A Luigi Task instance
        """
        super().__init__(work_unit)
        self.work_unit: luigi.Task

    def get_family(self) -> str:
        """Return the Luigi task family name."""
        return self.work_unit.get_task_family()

    def get_params(self) -> Dict[str, Any]:
        """Return task parameters as a serializable dict."""
        return self.work_unit.to_str_params()

    def get_config(self) -> Dict[str, Any]:
        """
        Extract task-specific configuration.

        Checks for:
        1. task.scicd dict attribute
        2. task.scicd_* attributes

        Returns:
            Dict with resource configuration (cpu, memory, tags, etc.)
        """
        config: Dict[str, Any] = {}

        if hasattr(self.work_unit, "scicd"):
            scicd_attr = getattr(self.work_unit, "scicd")
            if isinstance(scicd_attr, dict):
                config.update(scicd_attr)

        # Option 2: scicd_ prefixed attributes
        for attr in dir(self.work_unit):
            if attr.startswith("scicd_"):
                key = attr.replace("scicd_", "")
                config[key] = getattr(self.work_unit, attr)

        return config

    def get_run_command(self) -> List[str]:
        """
        Generate the command to run this Luigi task.

        Returns:
            Command that will be executed in CI/CD job
        """
        return [
            "scicd",
            "run-luigi",
            "--module",
            self.work_unit.__class__.__module__,
            "--family",
            self.get_family(),
            "--params",
            json.dumps(self.get_params()),
        ]

    def get_unique_id(self) -> str:
        """Return the Luigi task_id (family + param hash)."""
        return self.work_unit.task_id
