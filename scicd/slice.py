import importlib
import os
import json
from typing import Annotated

import luigi
import yaml
import typer

from scicd.config import TaskConfig

# Initialize Typer App
app = typer.Typer(help="Slicing and child-pipeline generation utilities.")


def generate_child_pipeline_config(
    family: str, manifest_path: str, cfg: TaskConfig, gitlab_info: dict, gen_id: str
) -> dict:
    """
    Generates the .yml dict for the child pipeline.
    Uses GitLab Parallel Matrix syntax.
    """
    worker_job = gitlab_info.copy()

    worker_job["stage"] = "execute"
    worker_job["parallel"] = cfg.concurrency_workers
    worker_job["script"] = [
        f"{cfg.python_executable} -m scicd.slice slice-run --manifest-path {manifest_path}"
    ]
    worker_job["needs"] = [
        {
            "pipeline": "$CI_PIPELINE_ID",
            "job": gen_id,
            "artifacts": True,
            "project": "$CI_PROJECT_PATH",
        }
    ]

    return {
        "stages": ["execute"],
        f"{family}_worker": worker_job,
    }


@app.command()
def generate(
    module: Annotated[
        str, typer.Option(help="The Python module containing the tasks.")
    ],
    family: Annotated[str, typer.Option(help="The Luigi task family class name.")],
    all_params_json: Annotated[
        str, typer.Option(help="JSON list of all task parameters.")
    ],
    cfg_json: Annotated[
        str, typer.Option(help="JSON string of the TaskConfig dataclass.")
    ],
    gitlab_info_json: Annotated[
        str, typer.Option(help="JSON string of compiled GitLab info.")
    ],
    gen_id: Annotated[str, typer.Option(help="Trigger job identifier.")],
):
    """
    Creates a manifest where every entry explicitly defines its module and family.
    Uses serialized TaskConfig to govern the generated child pipeline.
    """
    # Typer guarantees these are raw strings, so json.loads is now safe
    param_list = json.loads(all_params_json)
    cfg_dict = json.loads(cfg_json)
    gitlab_info = json.loads(gitlab_info_json)

    # Reconstruct the dataclass
    cfg = TaskConfig(**cfg_dict)

    # Build the Manifest
    manifest_data = []
    for params in param_list:
        manifest_data.append({"module": module, "family": family, "params": params})

    with open("manifest.yml", "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f, default_flow_style=False)

    # Generate the CI config (the child pipeline)
    pipeline_config = generate_child_pipeline_config(
        family=family,
        manifest_path="manifest.yml",
        cfg=cfg,
        gitlab_info=gitlab_info,
        gen_id=gen_id,
    )

    with open("child_pipeline.yml", "w", encoding="utf-8") as f:
        yaml.dump(pipeline_config, f, default_flow_style=False)


@app.command()
def slice_run(
    manifest_path: Annotated[str, typer.Option(help="Path to the manifest.yml file.")],
):
    """
    The GitLab Worker entry point.
    """
    # 1 is the default for local testing, GitLab provides these automatically
    node_index = int(os.environ.get("CI_NODE_INDEX", 1)) - 1
    node_total = int(os.environ.get("CI_NODE_TOTAL", 1))

    with open(manifest_path, "r", encoding="utf-8") as f:
        all_specs = yaml.safe_load(f)

    # Modulus math picks the tasks for this worker
    my_specs = [
        spec for i, spec in enumerate(all_specs) if i % node_total == node_index
    ]

    if my_specs:
        print(f"Worker {node_index+1}/{node_total} running {len(my_specs)} tasks.")
        _slice_run(my_specs)
    else:
        print(f"Worker {node_index+1}/{node_total} has no tasks to run.")


def _slice_run(task_specs: list):
    """
    Uses the explicit module/family/params to hydrate tasks.
    """
    luigi_tasks = []
    for spec in task_specs:
        mod = importlib.import_module(spec["module"])
        task_cls = getattr(mod, spec["family"])

        # Instantiate with params
        instantiated_task = task_cls.from_str_params(spec["params"])
        luigi_tasks.append(instantiated_task)

    luigi.build(luigi_tasks, local_scheduler=True)


if __name__ == "__main__":
    app()
