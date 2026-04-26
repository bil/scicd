from scicd.executor import register_executor
from typing import Dict
from scicd.config import TaskConfig

@register_executor(tags=["bilkube"])
def gke_autopilot(cfg: TaskConfig) -> Dict[str, str]:
    out = {
        "KUBERNETES_CPU_REQUEST": cfg.cpu,
        "KUBERNETES_MEMORY_REQUEST": cfg.memory,
    }
    if cfg.disk:
        out["KUBERNETES_EPHEMERAL_STORAGE_REQUEST"] = cfg.disk

    if cfg.disk_type and "ssd" in cfg.disk_type:
        out["KUBERNETES_NODE_SELECTOR_SSD"] = "cloud.google.com/gke-ephemeral-storage-ssd=true"

    if cfg.compute_type:
        out["KUBERNETES_NODE_SELECTOR_COMPUTE"] = f"cloud.google.com/compute-class={cfg.compute_type}"

    if cfg.machine_type:
        out["KUBERNETES_NODE_SELECTOR_FAMILY"] = f"cloud.google.com/machine-family={cfg.machine_type}"

    if cfg.gpu:
        out["KUBERNETES_NODE_SELECTOR_GPU_COUNT"] = f"cloud.google.com/gke-accelerator-count={cfg.gpu}"

    if cfg.gpu_type:
        out["KUBERNETES_NODE_SELECTOR_GPU"] = f"cloud.google.com/gke-accelerator={cfg.gpu_type}"


@register_executor(tags=["worm"])
def docker(cfg: TaskConfig) -> Dict[str, str]:
    assert isinstance(cfg, TaskConfig)  # linting
    return {} 
