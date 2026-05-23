"""
Custom executor discovery
"""

import os
import importlib.util
from pathlib import Path
from typing import Callable, NamedTuple, Iterable, Optional


class Executor(NamedTuple):
    """Represents a registered custom executor and its transformation function."""

    name: str
    tags: set[str]
    func: Callable

    def __repr__(self):
        return f"Executor(name={self.name}, tags={self.tags})"


class _ExecutorRegistry:
    """Internal singleton manager for custom executor discovery and storage."""

    _registry: list[Executor] = []
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
        """Search for and load custom executors."""

        # Environment Variable Override
        env_path = os.getenv("SCICD_EXECUTORS_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                cls._load_from_path(p)
                return
            raise FileNotFoundError(
                f"Executor file specified in SCICD_EXECUTORS_PATH not found: {env_path}"
            )

        for executor_file in [
            "scicd_executors.py",
            ".scicd_executors.py",
            ".scicd/executors.py",
        ]:
            path = Path(executor_file)
            if path.exists():
                cls._load_from_path(path)
                return

        #  Default directory
        executor_directory = Path(".scicd/executors")
        if executor_directory.exists() and executor_directory.is_dir():
            for path in executor_directory.iterdir():
                if path.is_file() and path.suffix == ".py":
                    cls._load_from_path(path)

    @classmethod
    def _load_from_path(cls, path: Path):
        spec = importlib.util.spec_from_file_location(
            """Load a Python module from a disk path and trigger registration."""
            "_executors",
            path,
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # print(f"Loaded custom executors from {str(path)}")

    @classmethod
    def reset(cls):
        """Reset the internal registry state."""
        cls._registry.clear()
        cls._loaded = False


def register_executor(tags: Iterable[str], name: Optional[str] = None):
    """
    Decorator to register a function as a SciCD executor for a set of tags.

    The decorated function should take a TaskConfig and return a dict of
    environment variables to inject into a CI/CD job.
    """

    def decorator(func: Callable):
        nonlocal name
        if name is None:
            name = func.__name__

        registry = _ExecutorRegistry.get_registry()
        registry.append(Executor(name, set(tags), func))
        return func

    return decorator


def get_registry() -> list[Executor]:
    return _ExecutorRegistry.get_registry()


def get_executor(tags: Iterable[str]) -> Executor:
    """
    Find the executor that matches the given tags exactly.

    Note that multiple runners can match (i.e. superset) tags.
    This will return the first exact or superset match, and use that function.
    Gitlab may not choose that runner with its central scheduler.
    """
    registry = _ExecutorRegistry.get_registry()
    tags = set(tags)
    # total match
    for executor in registry:
        if executor.tags == tags:
            return executor
    # return first partial match
    for executor in registry:
        if tags.issubset(executor.tags):
            return executor

    raise ValueError(f"No executor found matching or supersetting tags: {tags}")


def reset_executors():
    """Reset all cached executors (for testing)."""
    _ExecutorRegistry.reset()
