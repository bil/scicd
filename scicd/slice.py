import importlib
import os
import json
from typing import Dict, Any

import luigi
import yaml
import fire


def generate_child_pipeline_config(
    family: str, manifest_path: str, num_workers: int, image: str
) -> Dict[str, Any]:
    """
    Generates the .yml dict for the child pipeline.
    Uses GitLab Parallel Matrix syntax.
    """
    return {
        "stages": ["execute"],
        f"{family}_worker": {
            "stage": "execute",
            "image": image,
            "parallel": num_workers,  # This is the "Magic" Matrix part
            "script": [
                f"python -m scicd.slice slice_run --manifest_path {manifest_path}"
            ],
        },
    }


def generate(
    module: str,
    family: str,
    all_params_json: str,
    num_workers: int,
    image: str,
):
    """
    Creates a manifest where every entry explicitly defines its module and family.
    """
    param_list = json.loads(all_params_json)

    manifest_data = []
    for params in param_list:
        manifest_data.append(
            {"module": module, "family": family, "params": params}
        )

    with open("manifest.yml", "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f, default_flow_style=False)

    # Generate the CI config (the child pipeline)
    pipeline_config = generate_child_pipeline_config(
        family=family,
        manifest_path="manifest.yml",
        num_workers=num_workers,
        image=image,
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
