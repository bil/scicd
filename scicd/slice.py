import importlib
import os
import json

import luigi
import yaml
import fire

from scicd.config import TaskConfig

# Assuming TaskConfig is imported


def generate_child_pipeline_config(
    family: str, manifest_path: str, cfg: TaskConfig, gitlab_info: dict
) -> dict:
    """
    Generates the .yml dict for the child pipeline.
    Uses GitLab Parallel Matrix syntax.
    """

    # Start with pre-compiled boilerplate (image, tags, vars, retries)
    worker_job = gitlab_info.copy()

    # Add the worker-specific execution logic
    worker_job["stage"] = "execute"
    worker_job["parallel"] = cfg.concurrency_workers
    worker_job["script"] = [
        f"{cfg.python_executable} -m scicd.slice slice_run --manifest_path {manifest_path}"
    ]

    return {
        "stages": ["execute"],
        f"{family}_worker": worker_job,
    }


def generate(
    module: str,
    family: str,
    all_params_json: str,
    cfg_json: str,
    gitlab_info_json: str,
):
    """
    Creates a manifest where every entry explicitly defines its module and family.
    Uses serialized TaskConfig to govern the generated child pipeline.
    """
    # Deserialize the state
    param_list = json.loads(all_params_json)
    cfg_dict = json.loads(cfg_json)
    gitlab_info = json.loads(gitlab_info_json)

    # Reconstruct the dataclass to get our strict types and attributes back
    cfg = TaskConfig(**cfg_dict)

    # Build the Manifest
    manifest_data = []
    for params in param_list:
        manifest_data.append({"module": module, "family": family, "params": params})

    with open("manifest.yml", "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f, default_flow_style=False)

    # Generate the CI config (the child pipeline)
    # Right now I am mapping the config attributes back to your existing arguments.
    pipeline_config = generate_child_pipeline_config(
        family=family, manifest_path="manifest.yml", cfg=cfg, gitlab_info=gitlab_info
    )

    with open("child_pipeline.yml", "w", encoding="utf-8") as f:
        yaml.dump(pipeline_config, f, default_flow_style=False)


def slice_run(manifest_path: str):
    """
    The GitLab Worker entry point.
    """
    node_index = int(os.environ.get("CI_NODE_INDEX", 1)) - 1
    node_total = int(os.environ.get("CI_NODE_TOTAL", 1))

    with open(manifest_path, "r", encoding="utf-8") as f:
        all_specs = yaml.safe_load(f)

    # Modulus math picks the tasks for this worker
    my_specs = [
        spec for i, spec in enumerate(all_specs) if i % node_total == node_index
    ]

    if my_specs:
        print(f"Worker {node_index+1} running {len(my_specs)} tasks.")
        _slice_run(my_specs)


def _slice_run(task_specs: list):
    """
    Uses the explicit module/family/params to hydrate tasks.
    """
    luigi_tasks = []
    for spec in task_specs:
        # Dynamically import the specific module
        mod = importlib.import_module(spec["module"])
        task_cls = getattr(mod, spec["family"])

        # Instantiate with params
        instantiated_task = task_cls.from_str_params(spec["params"])
        luigi_tasks.append(instantiated_task)

    luigi.build(luigi_tasks, local_scheduler=True)


if __name__ == "__main__":
    fire.Fire()
