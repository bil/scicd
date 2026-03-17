import json
import hashlib
from functools import wraps
from pathlib import Path
from typing import Type, TypeVar, Union
import luigi

from scicd.config import cascading_config
from scicd.git import get_git_commit

# Type variable to keep track of the original Task class
T = TypeVar("T", bound=luigi.Task)


class AutotaskMetadata:
    """
    This class exists to provide a clear structure for the linter.
    It contains the attributes we inject into the task.
    """

    cfg: dict
    COMMIT_HASH: str

    def get_fingerprint(self) -> str: ...


T = TypeVar("T", bound=luigi.Task)


def autotask(cls: Type[T]) -> Type[T]:
    """
    Dynamic decorator that creates a hybrid class preserving the original
    class name to prevent Luigi registration collisions.
    """

    # Define logic in Mixin
    class AutotaskMixin(AutotaskMetadata):
        COMMIT_HASH = get_git_commit()

        @property
        def cfg(self) -> dict:
            # cascading_config handles the PathConfig/Parameters logic
            return cascading_config(self.get_task_family(), **self.param_kwargs)

        def get_fingerprint(self) -> str:
            fingerprint_data = {
                "commit": self.COMMIT_HASH,
                "params": self.param_kwargs,
                "config": self.cfg,
            }
            dump = json.dumps(fingerprint_data, sort_keys=True)
            return hashlib.sha256(dump.encode()).hexdigest()[:12]

        def fp_path(self, target_path: str) -> Path:
            p = Path(target_path)
            fp_dir = p.parent / ".luigi_fingerprints"
            fp_dir.mkdir(parents=True, exist_ok=True)
            return fp_dir / f"{p.name}.fingerprint"

        def complete(self) -> bool:
            # Standard Luigi completion check
            if not super().complete():
                return False

            outputs = luigi.task.flatten(self.output())
            if not outputs:
                return True

            current_fp = self.get_fingerprint()
            for ot in outputs:
                if hasattr(ot, "path"):
                    f_path = self.fp_path(ot.path)
                    if not f_path.exists() or f_path.read_text().strip() != current_fp:
                        return False
            return True

        def run(self):
            # Ensure directories exist before the original run() executes
            for target in luigi.task.flatten(self.output()):
                if hasattr(target, "makedirs"):
                    target.makedirs()
            return super().run()

    # Dynamically create the class: (Name, Bases, Dict)
    # This ensures TaskA becomes 'TaskA', not 'WrappedTask'
    derived_class = type(
        cls.__name__,
        (AutotaskMixin, cls),
        {"__module__": cls.__module__, "__doc__": cls.__doc__},
    )

    # Re-register the Success Event on the derived class
    @derived_class.event_handler(luigi.Event.SUCCESS)
    def save_fingerprint_callback(task_instance):
        current_fp = task_instance.get_fingerprint()
        for ot in luigi.task.flatten(task_instance.output()):
            if hasattr(ot, "path"):
                task_instance.fp_path(ot.path).write_text(current_fp)

    return derived_class
