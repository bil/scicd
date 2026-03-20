"""
Custom Executor Registry for SciCD.
"""
import importlib.util
from pathlib import Path
from typing import Callable, NamedTuple, Iterable, Dict, Optional, Any

class Executor(NamedTuple):
    name: str
    func: Callable

class _ExecutorRegistry:
    """Internal manager for custom executors."""
    
    _registry: Optional[Dict[str, Executor]] = None

    @classmethod
    def get_registry(cls) -> Dict[str, Executor]:
        """Lazy-load and return the executor registry."""
        if cls._registry is None:
            cls._registry = {}
            cls._load_custom_executors()
        return cls._registry

    @classmethod
    def _load_custom_executors(cls):
        """Load custom executors from standard locations."""
        import os
        # 1. Environment Variable
        env_path = os.getenv("SCICD_EXECUTORS_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                cls._load_from_path(p)
                return  # If env var is set and exists, only use that
            raise FileNotFoundError(f"Executor file specified in SCICD_EXECUTORS_PATH not found: {env_path}")

        # 2. Check for single file
        executor_file = Path(".scicd/executors.py")
        if executor_file.exists():
            cls._load_from_path(executor_file)

        # 3. Check for directory
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

def register_executor(tags: Iterable[str], name: str = None):
    """
    Decorator to register an executor function.
    """
    def decorator(func: Callable):
        nonlocal name
        if name is None:
            name = func.__name__

        registry = _ExecutorRegistry.get_registry()
        for tag in tags:
            registry[tag] = Executor(name, func)
        return func
    return decorator

def get_executor(tags: Iterable[str]) -> Executor:
    """Find the first matching executor for the given tags."""
    registry = _ExecutorRegistry.get_registry()
    for tag in tags:
        if tag in registry:
            return registry[tag]
    raise ValueError(f"No executor found matching tags: {tags}")
