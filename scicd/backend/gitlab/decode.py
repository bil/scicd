"""GitLab CI/CD YAML decoding and generation."""

import json
import shlex
from copy import deepcopy
from typing import Any

import yaml
import rich

import scicd.yamler
from scicd.config import TaskConfig, get_workspace
from scicd.executor import get_executor
from scicd.dag import DAG, BaseNode, BijectNode, SliceNode


def gitlab_info(cfg: TaskConfig) -> dict:
    """Resolve generic GitLab job configuration from TaskConfig."""
    info = {}

    if cfg.image:
        info["image"] = str(cfg.image)

    variables = dict(cfg.variables) if cfg.variables else {}

    if cfg.tags:
        try:
            executor = get_executor(cfg.tags)
            rich.print(
                f"[bold blue]SciCD:[/bold blue] Matched tags {list(cfg.tags)} to executor [cyan]{executor.name}[/cyan]"
            )
            executor_vars = executor.func(cfg)
            if executor_vars:
                variables.update(executor_vars)
        except ValueError:
            pass

    if cfg.executor_config:
        variables.update(cfg.executor_config)

    if variables:
        info["variables"] = variables

    if cfg.tags:
        info["tags"] = list(cfg.tags)

    if cfg.retry > 0:
        info["retry"] = int(cfg.retry)

    if cfg.timeout:
        info["timeout"] = str(cfg.timeout)

    if cfg.cicd:
        info = scicd.yamler.deep_update(info, dict(cfg.cicd))

    return info


def render_node_gitlab(node: BaseNode) -> list[dict[str, Any]]:
    """Convert a DAG node into one or more GitLab job definitions."""
    if isinstance(node, BijectNode):
        adapter = node.work[0]
        job = gitlab_info(adapter.cfg)
        job["stage"] = f"stage_{node.rank}"
        job["script"] = [shlex.join(adapter.command)]

        variables = job.get("variables", {})
        variables["SCICD_PARAMS"] = adapter.params_json
        job["variables"] = variables

        if node.needs:
            job["needs"] = node.needs

        return [{node.identifier: job}]
    elif isinstance(node, SliceNode):
        # Extract commands and environment variables from all work units
        commands = [adapter.command for adapter in node.work]
        envs = [{"SCICD_PARAMS": adapter.params_json} for adapter in node.work]

        commands_json = json.dumps(commands)
        envs_json = json.dumps(envs)

        cfg = node.work[0].cfg
        cfg_json = cfg.model_dump_json(
            exclude_none=True,
            exclude_computed_fields=True,
            exclude_defaults=True,
            exclude_unset=True
        )

        g_info = gitlab_info(cfg)
        gitlab_info_json = json.dumps(g_info)

        gen_id = f"{node.name}_rank{node.rank}_gen"

        # Generator Job: Dynamically creates the child pipeline YAML
        gen_job = deepcopy(g_info)
        gen_job["stage"] = f"stage_{node.rank}"

        # Pass inputs via environment variables
        gen_vars = gen_job.get("variables", {})
        gen_vars.update({
            "SCICD_COMMANDS_JSON": commands_json,
            "SCICD_ENV_JSON": envs_json,
            "SCICD_CFG_JSON": cfg_json,
            "SCICD_GITLAB_INFO_JSON": gitlab_info_json,
        })
        gen_job["variables"] = gen_vars

        gen_command = [
            "python3",
            "-m",
            "scicd.slice",
            "generate",
            "--target",
            node.name,
            "--gen-id",
            gen_id,
        ]

        gen_job["script"] = [shlex.join(gen_command)]
        gen_job["artifacts"] = {"paths": ["manifest.yml", "child_pipeline.yml"]}

        if node.needs:
            gen_job["needs"] = node.needs

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
    """Generate full GitLab CI/CD pipeline dictionary from DAG."""
    pipeline = deepcopy(boilerplate)
    all_jobs = {}

    for node in dag.nodes:
        for job_dict in render_node_gitlab(node):
            all_jobs.update(job_dict)

    unique_stages = sorted(
        {body["stage"] for body in all_jobs.values() if "stage" in body},
        key=lambda x: int(x.split("_")[1]) if "_" in x else 0,
    )

    pipeline["stages"] = unique_stages
    pipeline.update(all_jobs)
    return pipeline


def write_gitlab_yaml(dag: DAG, filepath: str = ".gitlab-ci.yml", **boilerplate):
    """Serialize rendered pipeline dictionary to YAML file."""
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(
            render_gitlab(dag, **boilerplate),
            f,
            sort_keys=False,
            default_flow_style=False,
        )


def export_gitlab(dag: DAG, filepath: str = ".gitlab-ci.yml"):
    """Render abstract DAG into a GitLab CI/CD pipeline file."""
    wspace = get_workspace()

    boilerplate = {}
    if wspace.cicd:
        boilerplate.update(wspace.cicd)

    write_gitlab_yaml(dag, filepath=filepath, **boilerplate)
