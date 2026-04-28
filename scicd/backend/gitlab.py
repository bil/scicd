"""GitLab CI/CD YAML generation, API integration."""

from __future__ import annotations
import os
import json
import shlex
from pathlib import Path
from copy import deepcopy
from typing import Any, Optional, TYPE_CHECKING

import yaml
import rich
import gitlab
from cyclopts import App

from scicd.yamler import deep_merge
from scicd.git import get_branch
from scicd.config import TaskConfig, get_workspace_config
from scicd.executor import get_executor

if TYPE_CHECKING:
    from scicd.dag import DAG
    from scicd.node import Node

app = App(name="gitlab", help="Gitlab sub-command")


def get_pat() -> str:
    if "GITLAB_PAT" in os.environ:
        return os.environ["GITLAB_PAT"]
    raise RuntimeError("Missing 'GITLAB_PAT' in environment file.")


def export_dag(
    dag: DAG,
    file_path: str = ".gitlab-ci.yml",
) -> dict:
    """Render abstract DAG into a GitLab CI/CD pipeline file."""
    wspace = get_workspace_config(dag.config_path)
    boilerplate = wspace.cicd
    pipeline = deepcopy(boilerplate)
    all_jobs = {}

    for node in dag.nodes:
        job_dict = node.export(backend="gitlab")
        all_jobs.update(job_dict)

    unique_stages = sorted(
        {body["stage"] for body in all_jobs.values() if "stage" in body},
        key=lambda x: int(x.split("_")[1]) if "_" in x else 0,
    )

    pipeline["stages"] = unique_stages
    pipeline.update(all_jobs)

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(
            pipeline,
            f,
            sort_keys=False,
            default_flow_style=False,
            width=float("inf"),
        )
    return pipeline


def gitlab_info(cfg: TaskConfig) -> dict:
    """Resolve generic GitLab job configuration from TaskConfig."""
    info: dict[str, Any] = {}

    if cfg.image:
        info["image"] = str(cfg.image)

    variables = dict(cfg.variables) if cfg.variables else {}

    if variables:
        info["variables"] = variables

    if cfg.tags:
        info["tags"] = list(cfg.tags)

    if cfg.retry > 0:
        info["retry"] = int(cfg.retry)

    if cfg.max_duration:
        info["timeout"] = str(cfg.max_duration)

    if cfg.cicd:
        info = scicd.yamler.deep_merge(info, dict(cfg.cicd))

    return info


def export_node(node: Node) -> dict:
    """Generate job dicts for a node"""
    template = gitlab_info(node.cfg)
    template["stage"] = f"stage_{node.rank}"
    # if node.cfg.pre:
    #     job["before_script"] = node.cfg.pre
    # if node.cfg.post:
    #     job["after_script"] = node.cfg.post
    variables = template.get("variables", {})
    # variables.update(node.env_vars)
    variables.update(node.executor_vars)
    if variables:
        template["variables"] = variables

    # always include keyword to execute based on needs not stage
    if node.needs:
        template["needs"] = node.needs
    else:
        template["needs"] = []

    out = {}
    for name, cmds in zip(node.jobs, node.commands):
        job = deepcopy(template)
        job["script"] = cmds
        out[name] = job

    return out


@app.command()
def lint(
    file_path: str = ".gitlab-ci.yml",
    url: Optional[str] = None,
    project: Optional[str] = None,
    config_path: Optional[str] = None,
) -> None:
    """Validate GitLab CI/CD YAML syntax using the GitLab Lint API."""
    yaml_path = Path(file_path)
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Cannot find pipeline file at '{yaml_path.resolve()}'"
        )

    with open(yaml_path, "r", encoding="utf-8") as f:
        yaml_content = f.read()

    pat = get_pat()
    workspace = get_workspace_config(config_path)
    url = url or workspace.url
    project = project or workspace.project

    if not url or not project:
        raise RuntimeError("Missing 'url' or 'project' for GitLab API.")

    client = gitlab.Gitlab(url, private_token=pat)
    try:
        gl_project = client.projects.get(project)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project}' at {url}."
        ) from e

    print(f"Linting '{file_path}' against {url}/{project}...")
    try:
        lint_result = gl_project.ci_lint.create({"content": yaml_content})
    except gitlab.exceptions.GitlabCreateError as e:
        raise RuntimeError(f"GitLab API Error during linting: {e}") from e

    if lint_result.valid:
        print("Pipeline YAML is valid!")
    else:
        print("Pipeline YAML is invalid.")

    if hasattr(lint_result, "warnings") and lint_result.warnings:
        print("Warnings:")
        for warning in lint_result.warnings:
            print(f"  - {warning}")

    if hasattr(lint_result, "errors") and lint_result.errors:
        print("Errors:")
        for error in lint_result.errors:
            print(f"  - {error}")


@app.command()
def run(
    branch: Optional[str] = None,
    url: Optional[str] = None,
    project: Optional[str] = None,
    config_path: Optional[str] = None,
    **pipeline_vars,
):
    """Trigger a remote pipeline run on GitLab."""
    pat = get_pat()
    workspace = get_workspace_config(config_path)
    url = url or workspace.url
    project = project or workspace.project

    if not url or not project:
        raise RuntimeError("Missing 'url' or 'project' for GitLab API.")

    client = gitlab.Gitlab(url, private_token=pat)
    try:
        gl_project = client.projects.get(project)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project}' at {url}."
        ) from e

    branch = branch or get_branch()
    if not branch:
        raise RuntimeError("Git branch required for CI triggering.")

    formatted_vars = [
        {"key": str(k), "value": str(v)} for k, v in pipeline_vars.items()
    ]
    if formatted_vars:
        print(f"Injecting {formatted_vars} into pipeline")

    p = gl_project.pipelines.create(
        {"ref": branch, "variables": formatted_vars}
    )

    print(f"Pipeline {p.id} triggered on branch '{branch}'")
    print(f"View here: {p.web_url}")
