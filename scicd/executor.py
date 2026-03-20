"""
Module docstring.
"""
from pathlib import Path
import importlib.util
from typing import Callable, NamedTuple, Iterable
from scicd.config import Singleton


class Executor(NamedTuple):
    name: str
    func: Callable


def register_executor(tags: Iterable[str], name: str = None):
    """
    Decorator to register an executor function.

    Args:
        tags: List of tags this executor handles
        name (str): Registered name of executor.
            If `None`, then use function name.

    Example:
        @register_executor(tags=["slurm", "sherlock"])
        def slurm(task):
            return {"SLURM_CPUS": str(task.cpu)}
    """

    def decorator(func: Callable):
        if name is None:
            name = func.__name__

        # Register this function for each tag individually
        for tag in tags:
            ExecutorRegistry().registry[tag] = Executor(name, func)
        return func

    return decorator


class ExecutorRegistry(Singleton):

    def _first_init(self, **kwargs):
        self.registry = {}
        self.load_executors()

    def _next_init(self, **kwargs):
        pass

    def load_executors(self):
        """Load custom executors if they exist."""
        executor_directory = Path(".scicd/executors")

        if executor_directory.exists() and executor_directory.is_dir():
            for path in executor_directory.iterdir():
                if path.is_file() and path.suffix == ".py":
                    spec = importlib.util.spec_from_file_location(
                        "scicd_user_executors", path
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        print(f"Loaded custom executors from {str(path)}")

    def get(self, tags: Iterable[str]) -> Executor:
        """Find the first matching executor for the given tags."""
        for tag in tags:
            if tag in self.registry:
                return self.registry[tag]
        raise ValueError(f"No executor found matching tags: {tags}")

