from typing import Dict

from scicd.executor import register_executor
from scicd.config import TaskConfig


@register_executor(tags=["pc"])
def pc(cfg: TaskConfig) -> Dict[str, str]:
    _ = cfg
    return {"PATH_OUTPUT": "/scratch/tmp/pc"}


@register_executor(tags=["pc2"])
def pc2(cfg: TaskConfig) -> Dict[str, str]:
    _ = cfg
    return {"PATH_OUTPUT": "/scratch/tmp/pc2"}
