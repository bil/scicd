from scicd.executor import register_executor
from typing import Dict, Union
import scicd.config


@register_executor(tags=["bilkube"])
def kubernetes(task: scicd.config.TaskConfig) -> Dict[str, Union[int, str]]:
    return {
        "KUBERNETES_CPU_REQUEST": task.cpu,
        "KUBERNETES_MEMORY_REQUEST": str(task.memory),
    }


@register_executor(tags=["worm"])
def docker(task: scicd.config.TaskConfig) -> Dict[str, str]:
    assert isinstance(task, scicd.config.TaskConfig)  # linting
    return dict()
