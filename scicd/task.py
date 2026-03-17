import json
import hashlib
from pathlib import Path
from typing import Type, TypeVar
import luigi

from scicd.config import cascading_config
from scicd.git import get_git_commit

T = TypeVar("T", bound=luigi.Task)


def autotask(cls: Type[T]) -> Type[T]:
    """
    In-place decorator that patches the original class with SciCD logic.
    """
    #  Attach the Global Metadata
    cls.COMMIT_HASH = get_git_commit()

    # Add the Config Property
    @property
    def cfg(self):
        return cascading_config(self.get_task_family(), **self.param_kwargs)

    cls.cfg = cfg

    # Add Fingerprinting Logic
    def get_fingerprint(self) -> str:
        fingerprint_data = {
            "commit": self.COMMIT_HASH,
            "params": self.param_kwargs,
            "config": self.cfg,
        }
        dump = json.dumps(fingerprint_data, sort_keys=True)
        return hashlib.sha256(dump.encode()).hexdigest()[:12]

    cls.get_fingerprint = get_fingerprint

    # Override Complete (preserving original check)
    orig_complete = cls.complete

    def complete(self) -> bool:
        if not orig_complete(self):
            return False

        outputs = luigi.task.flatten(self.output())
        if not outputs:
            return True

        current_fp = self.get_fingerprint()
        for ot in outputs:
            if hasattr(ot, "path"):
                p = Path(ot.path)
                fp_file = p.parent / ".luigi_fingerprints" / f"{p.name}.fingerprint"
                if not fp_file.exists() or fp_file.read_text().strip() != current_fp:
                    return False
        return True

    cls.complete = complete

    # Override Run (to handle directory creation)
    orig_run = cls.run

    def run(self):
        for target in luigi.task.flatten(self.output()):
            if hasattr(target, "makedirs"):
                target.makedirs()
        return orig_run(self)

    cls.run = run

    # Success Callback for saving fingerprints
    @cls.event_handler(luigi.Event.SUCCESS)
    def save_fingerprint_callback(task_instance):
        current_fp = task_instance.get_fingerprint()
        for ot in luigi.task.flatten(task_instance.output()):
            if hasattr(ot, "path"):
                p = Path(ot.path)
                fp_dir = p.parent / ".luigi_fingerprints"
                fp_dir.mkdir(parents=True, exist_ok=True)
                (fp_dir / f"{p.name}.fingerprint").write_text(current_fp)

    return cls
