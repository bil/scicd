"""
Custom Executor Discovery and Registry for SciCD.

This module allows users to define custom 'executors' that map specific task tags
(like 'gpu' or 'slurm') to environment variables and configuration overrides.
"""

import os
import importlib.util
from pathlib import Path
from typing import Callable, NamedTuple, Iterable


class Executor(NamedTuple):
    """Represents a registered custom executor and its transformation function."""
    name: str
    func: Callable


class _ExecutorRegistry:
    """Internal singleton manager for custom executor discovery and storage."""

    _registry: dict[frozenset[str], Executor] = {}
    _loaded: bool = False

    @classmethod
    def get_registry(cls) -> dict[frozenset[str], Executor]:
        """Lazy-load and return the executor registry."""
        if not cls._loaded:
            cls._loaded = True
            cls._load_custom_executors()
        return cls._registry

    @classmethod
    def _load_custom_executors(cls):
        """Search for and load custom executors from standard locations."""

        # 1. Environment Variable Override
        env_path = os.getenv("SCICD_EXECUTORS_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                cls._load_from_path(p)
                return
            raise FileNotFoundError(
                f"Executor file specified in SCICD_EXECUTORS_PATH not found: {env_path}"
            )

        # 2. Default single file
        executor_file = Path(".scicd/executors.py")
        if executor_file.exists():
            cls._load_from_path(executor_file)

        # 3. Default directory
        executor_directory = Path(".scicd/executors")
        if executor_directory.exists() and executor_directory.is_dir():
            for path in executor_directory.iterdir():
                if path.is_file() and path.suffix == ".py":
                    cls._load_from_path(path)

    @classmethod
    def _load_from_path(cls, path: Path):
        """Load a Python module from a disk path and trigger registration."""
        spec = importlib.util.spec_from_file_location("scicd_user_executors", path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            print(f"SciCD: Loaded custom executors from {str(path)}")

    @classmethod
    def reset(cls):
        """Reset the internal registry state."""
        cls._registry.clear()
        cls._loaded = False


def register_executor(tags: Iterable[str], name: str = None):
    """
    Decorator to register a function as a SciCD executor for a set of tags.
    
    The decorated function should take a TaskConfig and return a dict of 
    environment variables to inject into the CI/CD job.
    """

    def decorator(func: Callable):
        nonlocal name
        if name is None:
            name = func.__name__

        registry = _ExecutorRegistry.get_registry()
        tag_set = frozenset(tags)
        registry[tag_set] = Executor(name, func)
        return func

    return decorator


def get_executor(tags: Iterable[str]) -> Executor:
    """
    Find the executor that matches the given tags exactly.
    """
    registry = _ExecutorRegistry.get_registry()
    task_tags = frozenset(tags)

    if task_tags in registry:
        return registry[task_tags]

    raise ValueError(f"No executor found matching exactly these tags: {tags}")


def reset_executors():
    """Reset all cached executors (for testing)."""
    _ExecutorRegistry.reset()
