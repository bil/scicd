"""Utilities for generating and executing dynamic child pipelines."""

import os
import json
import subprocess
from typing import Annotated
import yaml
from cyclopts import App, Parameter

from scicd.config import TaskConfig, WorkspaceConfig, get_workspace
from scicd.yamler import deep_update

app = App(help="Slicing and child-pipeline generation utilities.")


def generate_child_pipeline_config(
    target: str,
    manifest_path: str,
    cfg: TaskConfig,
    wspace: WorkspaceConfig,
    gitlab_info: dict,
    gen_id: str,
) -> dict:
    """Generate YAML configuration for a GitLab child pipeline."""
    pipeline_config = {"stages": ["execute"]}
    pipeline_config = deep_update(pipeline_config, wspace.cicd)

    worker_job = gitlab_info.copy()
    workers = cfg.concurrency.workers

    worker_job["stage"] = "execute"
    worker_job["parallel"] = workers
    worker_job["script"] = [
        f"python3 -m scicd.slice slice-run --manifest-path {manifest_path}"
    ]

    worker_job["needs"] = [
        {
            "pipeline": "$PARENT_PIPELINE_ID",
            "job": gen_id,
        }
    ]

    pipeline_config[f"{target}_worker"] = worker_job
    return pipeline_config


@app.command()
def generate(
    target: Annotated[str, Parameter(help="The task class name (target).")],
    gen_id: Annotated[str, Parameter(help="The generator job identifier.")],
):
    """Generate manifest and child pipeline YAML from environment variables."""
    commands_json = os.environ.get("SCICD_COMMANDS_JSON")
    envs_json = os.environ.get("SCICD_ENV_JSON")
    cfg_json = os.environ.get("SCICD_CFG_JSON")
    gitlab_info_json = os.environ.get("SCICD_GITLAB_INFO_JSON")

    if not all([commands_json, envs_json, cfg_json, gitlab_info_json]):
        raise ValueError(
            "Missing required environment variables: "
            "SCICD_COMMANDS_JSON, SCICD_ENV_JSON, SCICD_CFG_JSON, or SCICD_GITLAB_INFO_JSON"
        )

    command_list = json.loads(commands_json)
    env_list = json.loads(envs_json)
    gitlab_info = json.loads(gitlab_info_json)

    if len(command_list) != len(env_list):
        raise ValueError("Mismatch between number of commands and environment dicts.")

    cfg = TaskConfig.model_validate_json(cfg_json)
    wspace = get_workspace()

    # Create unified manifest of work units
    manifest_data = [
        {"command": cmd, "env": env} for cmd, env in zip(command_list, env_list)
    ]

    with open("manifest.yml", "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f, default_flow_style=False)

    pipeline_config = generate_child_pipeline_config(
        target=target,
        manifest_path="manifest.yml",
        cfg=cfg,
        wspace=wspace,
        gitlab_info=gitlab_info,
        gen_id=gen_id,
    )

    with open("child_pipeline.yml", "w", encoding="utf-8") as f:
        yaml.dump(pipeline_config, f, default_flow_style=False)


@app.command()
def slice_run(
    manifest_path: Annotated[str, Parameter(help="Path to the manifest.yml file.")],
):
    """Execute assigned subset of tasks with environment variable overrides."""
    node_index = int(os.environ.get("CI_NODE_INDEX", 1)) - 1
    node_total = int(os.environ.get("CI_NODE_TOTAL", 1))

    with open(manifest_path, "r", encoding="utf-8") as f:
        all_specs = yaml.safe_load(f)

    my_tasks = [
        spec for i, spec in enumerate(all_specs) if i % node_total == node_index
    ]

    if my_tasks:
        print(f"Worker {node_index+1}/{node_total} running {len(my_tasks)} tasks.")
        for task in my_tasks:
            cmd = task["command"]
            task_env_overrides = task.get("env", {})

            # Prepare execution environment
            run_env = os.environ.copy()
            run_env.update(task_env_overrides)

            print(f"Executing: {' '.join(cmd)}")
            subprocess.run(cmd, env=run_env, check=True)
    else:
        print(f"Worker {node_index+1}/{node_total} has no tasks to run.")


if __name__ == "__main__":
    app()
