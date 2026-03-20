"""
Custom Executor Registry for SciCD.
"""

import os
import importlib.util
from pathlib import Path
from typing import Callable, NamedTuple, Iterable, Dict


class Executor(NamedTuple):
    name: str
    func: Callable


class _ExecutorRegistry:
    """Internal manager for custom executors."""

    _registry: Dict[frozenset[str], Executor] = {}
    _loaded: bool = False

    @classmethod
    def get_registry(cls) -> Dict[frozenset[str], Executor]:
        """Lazy-load and return the executor registry."""
        if not cls._loaded:
            cls._loaded = True
            cls._load_custom_executors()
        return cls._registry

    @classmethod
    def _load_custom_executors(cls):
        """Load custom executors from standard locations."""

        # Environment Variable
        env_path = os.getenv("SCICD_EXECUTORS_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                cls._load_from_path(p)
                return  # If env var is set and exists, only use that
            raise FileNotFoundError(
                f"Executor file specified in SCICD_EXECUTORS_PATH not found: {env_path}"
            )

        # Check for single file
        executor_file = Path(".scicd/executors.py")
        if executor_file.exists():
            cls._load_from_path(executor_file)

        # Check for directory
        executor_directory = Path(".scicd/executors")
        if executor_directory.exists() and executor_directory.is_dir():
            for path in executor_directory.iterdir():
                if path.is_file() and path.suffix == ".py":
                    cls._load_from_path(path)

    @classmethod
    def _load_from_path(cls, path: Path):
        """Helper to load a module from a specific path."""
        spec = importlib.util.spec_from_file_location("scicd_user_executors", path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # Printing is helpful for verifying discovery in CI logs
            print(f"SciCD: Loaded custom executors from {str(path)}")

    @classmethod
    def reset(cls):
        """Reset the registry state."""
        cls._registry.clear()
        cls._loaded = False


def register_executor(tags: Iterable[str], name: str = None):
    """
    Decorator to register an executor function.
    """

    def decorator(func: Callable):
        nonlocal name
        if name is None:
            name = func.__name__

        registry = _ExecutorRegistry.get_registry()
        # Use frozenset for hashable dictionary key
        tag_set = frozenset(tags)
        registry[tag_set] = Executor(name, func)
        return func

    return decorator


def get_executor(tags: Iterable[str]) -> Executor:
    """Find the matching executor for the given tags (strict match)."""
    registry = _ExecutorRegistry.get_registry()
    task_tags = frozenset(tags)

    if task_tags in registry:
        return registry[task_tags]

    raise ValueError(f"No executor found matching exactly these tags: {tags}")


def reset_executors():
    """
    Reset the executor registry.
    Primarily used for testing to ensure a clean state.
    """
    _ExecutorRegistry.reset()
