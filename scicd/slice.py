import importlib
import os
import json
import sys
from typing import Annotated

import luigi
import yaml
from cyclopts import App, Parameter

from scicd.config import TaskConfig

app = App(help="Slicing and child-pipeline generation utilities.")


def generate_child_pipeline_config(
    family: str, manifest_path: str, cfg: TaskConfig, gitlab_info: dict, gen_id: str
) -> dict:
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
            "artifacts": True
        }
    ]

    return {
        "stages": ["execute"],
        f"{family}_worker": worker_job,
    }


@app.command()
def generate(
    module: Annotated[str, Parameter(help="The Python module containing the tasks.")],
    family: Annotated[str, Parameter(help="The Luigi task family class name.")],
    all_params_json: Annotated[
        str, Parameter(help="JSON list of all task parameters.")
    ],
    cfg_json: Annotated[
        str, Parameter(help="JSON string of the TaskConfig dataclass.")
    ],
    gitlab_info_json: Annotated[
        str, Parameter(help="JSON string of compiled GitLab info.")
    ],
    gen_id: Annotated[str, Parameter(help="Trigger job identifier.")],
):
    param_list = json.loads(all_params_json)
    cfg_dict = json.loads(cfg_json)
    gitlab_info = json.loads(gitlab_info_json)

    cfg = TaskConfig(**cfg_dict)

    manifest_data = []
    for params in param_list:
        manifest_data.append({"module": module, "family": family, "params": params})

    with open("manifest.yml", "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f, default_flow_style=False)

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
    manifest_path: Annotated[str, Parameter(help="Path to the manifest.yml file.")],
):
    node_index = int(os.environ.get("CI_NODE_INDEX", 1)) - 1
    node_total = int(os.environ.get("CI_NODE_TOTAL", 1))

    with open(manifest_path, "r", encoding="utf-8") as f:
        all_specs = yaml.safe_load(f)

    my_specs = [
        spec for i, spec in enumerate(all_specs) if i % node_total == node_index
    ]

    if my_specs:
        print(f"Worker {node_index+1}/{node_total} running {len(my_specs)} tasks.")
        _slice_run(my_specs)
    else:
        print(f"Worker {node_index+1}/{node_total} has no tasks to run.")


def _slice_run(task_specs: list):
    luigi_tasks = []
    for spec in task_specs:
        mod = importlib.import_module(spec["module"])
        task_cls = getattr(mod, spec["family"])
        instantiated_task = task_cls.from_str_params(spec["params"])
        luigi_tasks.append(instantiated_task)

    success = luigi.build(luigi_tasks, local_scheduler=True)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    app()
