import json
import shlex
from copy import deepcopy
from typing import Any, Dict, List
from types import SimpleNamespace

import yaml

import scicd.yamler
from scicd.config import TaskConfig, get_workspace
from scicd.executor import get_executor
from scicd.dag import DAG, BaseNode, BijectNode, SliceNode


def gitlab_info(cfg: TaskConfig) -> dict:
    """
    Load generic gitlab job keys.
    """
    info = {}

    if cfg.image:
        info["image"] = str(cfg.image)

    # Resolve variables from standard config and custom executors
    variables = dict(cfg.variables) if cfg.variables else {}

    # Custom Executors
    if cfg.tags:
        try:
            executor = get_executor(cfg.tags)
            # Call the executor function to get additional environment variables
            executor_vars = executor.func(cfg)
            if executor_vars:
                variables.update(executor_vars)
        except ValueError:
            # No matching executor found, which is fine (standard tags)
            pass

    if cfg.executor_config:
        variables.update(cfg.executor_config)

    if variables:
        info["variables"] = variables

    if cfg.tags:
        info["tags"] = list(cfg.tags)

    if cfg.retry > 0:
        info["retry"] = int(cfg.retry)

    # Timeouts in gitlab
    if cfg.timeout:
        info["timeout"] = str(cfg.timeout)

    # Any direct CI/CD passthrough config (interruptible, resource_group, etc)
    if cfg.cicd:
        info = scicd.yamler.deep_update(info, dict(cfg.cicd))

    return info


def render_node_gitlab(node: BaseNode) -> List[Dict[str, Any]]:
    """
    Render a single DAG node into Gitlab CI/CD jobs.
    """
    if isinstance(node, BijectNode):
        job = gitlab_info(node.work[0].cfg)
        job["stage"] = f"stage_{node.rank}"
        job["script"] = [shlex.join(node.work[0].command)]

        if node.needs:
            job["needs"] = node.needs

        return [{node.identifier: job}]

    elif isinstance(node, SliceNode):
        # Extract commands from all work units
        all_commands = [adapter.command for adapter in node.work]
        commands_json = json.dumps(all_commands)

        # Use the configuration from the first work unit as the basis
        cfg = node.work[0].cfg

        def _json_default(o):

            if isinstance(o, SimpleNamespace):
                return vars(o)
            return str(o)

        cfg_json = json.dumps(cfg.model_dump(), default=_json_default)

        # Serialize platform-specific boilerplate
        g_info = gitlab_info(cfg)
        gitlab_info_json = json.dumps(g_info)

        gen_id = f"{node.name}_rank{node.rank}_gen"

        # Generator Job: Dynamically creates the child pipeline YAML
        gen_job = deepcopy(g_info)
        gen_job["stage"] = f"stage_{node.rank}"

        gen_command = [
            "python3",
            "-m",
            "scicd.slice",
            "generate",
            "--target",
            node.name,
            "--commands-json",
            commands_json,
            "--cfg-json",
            cfg_json,
            "--gitlab-info-json",
            gitlab_info_json,
            "--gen-id",
            gen_id,
        ]

        gen_job["script"] = [shlex.join(gen_command)]
        gen_job["artifacts"] = {"paths": ["manifest.yml", "child_pipeline.yml"]}

        if node.needs:
            gen_job["needs"] = node.needs

        # Trigger Job: Launches the child pipeline generated above
        trigger_job = {
            "stage": f"stage_{node.rank}",
            "variables": {"PARENT_PIPELINE_ID": "$CI_PIPELINE_ID"},
            "trigger": {
                "include": [{"artifact": "child_pipeline.yml", "job": gen_id}],
                "strategy": "depend",
                "forward": {
                    "pipeline_variables": True,
                    "yaml_variables": True,
                },
            },
            "needs": [gen_id],
        }

        return [{gen_id: gen_job}, {node.identifier: trigger_job}]

    return []


def render_gitlab(dag: DAG, **boilerplate) -> dict:
    """Generate .gitlab-ci.yml dict from DAG."""
    pipeline = deepcopy(boilerplate)
    all_jobs = {}

    # Actual work
    for node in dag.nodes:
        for job_dict in render_node_gitlab(node):
            all_jobs.update(job_dict)

    # Identify functional stages
    unique_stages = sorted(
        {body["stage"] for body in all_jobs.values() if "stage" in body},
        key=lambda x: int(x.split("_")[1]) if "_" in x else 0,
    )

    pipeline["stages"] = unique_stages
    pipeline.update(all_jobs)
    return pipeline


def write_gitlab_yaml(dag: DAG, filepath: str = ".gitlab-ci.yml", **boilerplate):
    """Writes the rendered dict to a file."""
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(
            render_gitlab(dag, **boilerplate),
            f,
            sort_keys=False,
            default_flow_style=False,
        )


def export_gitlab(dag: DAG, filepath: str = ".gitlab-ci.yml"):
    """Renders the abstract DAG into a GitLab CI/CD pipeline."""
    wspace = get_workspace()

    # Extract workspace boilerplate (default/workflow blocks from scicd.yaml)
    boilerplate = {}
    if wspace.cicd:
        if wspace.cicd:
            boilerplate.update(wspace.cicd)

    write_gitlab_yaml(dag, filepath=filepath, **boilerplate)
