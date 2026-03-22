"""
Core adapter abstractions for SciCD.

Adapters provide a unified interface to bridge different pipeline frameworks
(like Luigi) with the abstract SciCD DAG and execution engine.
"""

from abc import ABC, abstractmethod
from typing import Any

import scicd.config
from scicd.config import DynamicModel


class BaseAdapter(ABC):
    """
    Abstract base class for all work unit adapters.
    
    An adapter wraps a framework-specific task (e.g., a Luigi Task) and
    provides standard properties for name, parameters, resource requirements,
    and the command-line string required to execute it.
    """

    def __init__(self, work: Any) -> None:
        """
        Initialize the adapter.

        Args:
            work: The underlying framework-specific task object.
        """
        self.work = work

    @property
    @abstractmethod
    def name(self) -> str:
        """The logical name of the work unit (usually the class name)."""

    @property
    @abstractmethod
    def params(self) -> DynamicModel:
        """Return task parameters as a flexible Pydantic model."""

    @property
    def params_json(self) -> str:
        """Serialize task parameters to a JSON string for CI/CD transport."""
        return self.params.model_dump_json()

    @property
    @abstractmethod
    def cfg(self) -> scicd.config.TaskConfig:
        """The fully resolved TaskConfig for this specific work unit."""

    @property
    @abstractmethod
    def command(self) -> list[str]:
        """The command-line array required to execute this work unit."""

    @property
    @abstractmethod
    def identifier(self) -> str:
        """A unique, deterministic string identifying this specific unit of work."""
