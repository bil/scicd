"""
Core adapter abstractions for SciCD.

Adapters provide a unified interface to bridge different pipeline frameworks
(like Luigi) with the abstract SciCD DAG and execution engine.
"""

from __future__ import annotations
import json
from abc import ABC, abstractmethod
from typing import Any, Optional
import scicd.config
from scicd.config import DynamicModel


class BaseAdapter(ABC):
    """
    An adapter provides a standard interface for framework-specific procedures.
    """

    def __init__(self, work: Any, config_path: Optional[str] = None) -> None:
        """
        Initialize the adapter.

        Args:
            work: The underlying framework-specific task object.
        """
        self.work = work
        self.config_path = config_path

    @property
    @abstractmethod
    def name(self) -> str:
        """
        The name of the task.

        All adapters with this name should share the same config; example is a luigi family.
        """

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
    def cfg_json(self) -> str:
        """Serialized configuration"""
        return self.cfg.model_dump_json(
            exclude_none=True,
            exclude_computed_fields=True,
            exclude_defaults=True,
            exclude_unset=True,
        )

    @property
    def setup_commands(self) -> list[str]:
        return []

    @property
    @abstractmethod
    def commands(self) -> list[str]:
        """
        Shell commands to run the adapter
        """

    @property
    def teardown_commands(self) -> list[str]:
        return []

    @property
    @abstractmethod
    def identifier(self) -> str:
        """A unique, deterministic string identifying this specific unit of work."""

    @property
    @abstractmethod
    def inputs(self) -> list[str]:
        """A list of input files"""

    @property
    @abstractmethod
    def outputs(self) -> list[str]:
        """A list of output files"""

    # @abstractmethod
    # def run(self) -> None:
    #     """Local run"""

    @property
    @abstractmethod
    def deps(self) -> list[BaseAdapter]:
        """Adapters for immediately upstream work"""

    @property
    def deps_count(self) -> dict[str, int]:
        """A string representation of dependencies chain"""
        out: dict[str, int] = {}
        visited: set[str] = set()

        def _recurse(dep: BaseAdapter):
            if dep.identifier in visited:
                return
            visited.add(dep.identifier)

            out.setdefault(dep.name, 0)
            out[dep.name] += 1
            for d in dep.deps:
                _recurse(d)

        for d in self.deps:
            _recurse(d)
        return out

    @property
    def deps_str(self) -> str:
        return json.dumps(self.deps_count, sort_keys=True)
