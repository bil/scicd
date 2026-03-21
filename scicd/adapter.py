"""
Module docstring.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import scicd.config


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
