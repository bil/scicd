"""
Module docstring.
"""

import os
import json
import subprocess
from typing import Annotated, List, Dict, Any

import yaml
from cyclopts import App, Parameter

from scicd.config import TaskConfig

app = App(help="Slicing and child-pipeline generation utilities.")


def generate_child_pipeline_config(
    family: str, manifest_path: str, cfg: TaskConfig, gitlab_info: dict, gen_id: str
) -> dict:
    """
    Generate the YAML configuration for a GitLab child pipeline.
    """
    worker_job = gitlab_info.copy()
    workers = cfg.concurrency.workers

    worker_job["stage"] = "execute"
    worker_job["parallel"] = workers
    worker_job["script"] = [
        f"python3 -m scicd.slice slice-run --manifest-path {manifest_path}"
    ]

    # Ensure the workers can access the manifest from the generator job
    worker_job["needs"] = [
        {
            "pipeline": "$PARENT_PIPELINE_ID",
            "job": gen_id,
        }
    ]

    return {
        "stages": ["execute"],
        f"{family}_worker": worker_job,
    }


@app.command()
def generate(
    family: Annotated[str, Parameter(help="The task family name.")],
    commands_json: Annotated[
        str, Parameter(help="JSON list of all task commands (List[List[str]]).")
    ],
    cfg_json: Annotated[
        str, Parameter(help="JSON string of the TaskConfig dataclass.")
    ],
    gitlab_info_json: Annotated[
        str, Parameter(help="JSON string of compiled GitLab info.")
    ],
    gen_id: Annotated[str, Parameter(help="The generator job identifier.")],
):
    """
    Generate a manifest of commands and a child pipeline YAML.
    """
    command_list = json.loads(commands_json)
    cfg_dict = json.loads(cfg_json)
    gitlab_info = json.loads(gitlab_info_json)

    # Reconstruct TaskConfig for validation and helper access
    cfg = TaskConfig(**cfg_dict)

    # The manifest now stores raw commands instead of Luigi metadata
    manifest_data = [{"command": cmd} for cmd in command_list]

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
    """
    Execute the slice of tasks assigned to this parallel worker.
    """
    # GitLab CI provides these variables for parallel jobs
    node_index = int(os.environ.get("CI_NODE_INDEX", 1)) - 1
    node_total = int(os.environ.get("CI_NODE_TOTAL", 1))

    with open(manifest_path, "r", encoding="utf-8") as f:
        all_specs = yaml.safe_load(f)

    # Determine which tasks this specific node is responsible for
    my_tasks = [
        spec for i, spec in enumerate(all_specs) if i % node_total == node_index
    ]

    if my_tasks:
        print(f"Worker {node_index+1}/{node_total} running {len(my_tasks)} tasks.")
        for task in my_tasks:
            cmd = task["command"]
            print(f"Executing: {' '.join(cmd)}")
            # Execute the command and fail if any task fails
            subprocess.run(cmd, check=True)
    else:
        print(f"Worker {node_index+1}/{node_total} has no tasks to run.")


if __name__ == "__main__":
    app()
