"""
Module docstring.
"""

import os
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List
from dataclasses import asdict

import yaml
import gitlab
from dotenv import load_dotenv

import scicd.yamler
from scicd.config import TaskConfig, get_workspace
from scicd.git import get_branch
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
        job["script"] = [" ".join(node.work[0].command)]

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
            from types import SimpleNamespace

            if isinstance(o, SimpleNamespace):
                return vars(o)
            return str(o)

        cfg_json = json.dumps(asdict(cfg), default=_json_default)

        # Serialize platform-specific boilerplate
        g_info = gitlab_info(cfg)
        gitlab_info_json = json.dumps(g_info)

        gen_id = f"{node.name}_rank{node.rank}_gen"

        # Generator Job: Dynamically creates the child pipeline YAML
        gen_job = deepcopy(g_info)
        gen_job["stage"] = f"stage_{node.rank}"

        gen_job["script"] = [
            f"python3 -m scicd.slice generate "
            f"--family {node.name} "
            f"--commands-json '{commands_json}' "
            f"--cfg-json '{cfg_json}' "
            f"--gitlab-info-json '{gitlab_info_json}' "
            f"--gen-id '{gen_id}'"
        ]
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


def lint_pipeline(yml_filepath: str = ".gitlab-ci.yml") -> bool:
    """
    Validates the generated GitLab CI/CD YAML file using the GitLab API.

    Args:
        yml_filepath (str): Path to the YAML file to lint. Defaults to ".gitlab-ci.yml".

    Returns:
        bool: True if valid, False if invalid.
    """
    # Verify the file actually exists locally
    yaml_path = Path(yml_filepath)
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"SciCD Error: Cannot find pipeline file at '{yaml_path.resolve()}'"
        )

    with open(yaml_path, "r", encoding="utf-8") as f:
        yaml_content = f.read()

    # Load environment and check for PAT
    dotenv_path = os.path.join(os.getcwd(), ".env")
    load_dotenv(dotenv_path, override=True)

    pat = os.getenv("GITLAB_PAT")
    if not pat:
        raise RuntimeError(
            "Missing 'GITLAB_PAT' in environment or .env file.\n"
            "This is required to authenticate with the GitLab Lint API."
        )

    # Grab the global workspace config
    workspace = get_workspace()

    if workspace.platform != "gitlab":
        raise RuntimeError(
            "Workspace is not configured for GitLab",
            f"(workspace.platform = {workspace.platform})",
        )

    url = workspace.url
    project_path = workspace.project

    if not project_path or not url:
        raise RuntimeError("Missing 'url' or 'project' in workspace configuration")

    # Connect to GitLab and get the project context
    client = gitlab.Gitlab(url, private_token=pat)
    try:
        project = client.projects.get(project_path)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project_path}' at {url}.\n"
            f"Check workspace configuration!"
        ) from e

    # Send the content to the project-level CI Linter
    print(f"Linting '{yml_filepath}' against {url}/{project_path}...")
    try:
        lint_result = project.ci_lint.create({"content": yaml_content})
    except gitlab.exceptions.GitlabCreateError as e:
        raise RuntimeError(f"GitLab API Error during linting: {e}") from e

    # Parse and output the results
    if lint_result.valid:
        print("Pipeline YAML is valid!")
    else:
        print("Pipeline YAML is INVALID.\n")

    if hasattr(lint_result, "warnings") and lint_result.warnings:
        print("Warnings:")
        for warning in lint_result.warnings:
            print(f"  - {warning}")

    if hasattr(lint_result, "errors") and lint_result.errors:
        print("Errors:")
        for error in lint_result.errors:
            print(f"  - {error}")

    return lint_result.valid


def run_pipeline(branch: str = None, **pipeline_vars):
    """
    Triggers a GitLab pipeline for the project defined in config.yaml.

    Args:
        branch (str, optional): Target git branch. Defaults to current active branch.
        **pipeline_vars: Arbitrary key-value pairs to pass as GitLab CI/CD variables.
    """
    # Load environment and check for PAT
    dotenv_path = os.path.join(os.getcwd(), ".env")
    load_dotenv(dotenv_path, override=True)

    pat = os.getenv("GITLAB_PAT")
    if not pat:
        raise RuntimeError(
            "Missing 'GITLAB_PAT' in environment or .env file.\n"
            "This is required to trigger GitLab pipelines."
        )

    # Grab the global config
    workspace = get_workspace()

    if workspace.platform != "gitlab":
        raise RuntimeError(
            "Workspace is not configured for GitLab",
            f"(workspace.platform = {workspace.platform})",
        )

    url = workspace.url
    project_path = workspace.project

    if not project_path or not url:
        raise RuntimeError("Missing 'url' or 'project' in workspace configuration")

    # Connect to GitLab
    client = gitlab.Gitlab(url, private_token=pat)
    try:
        project = client.projects.get(project_path)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project_path}' at {url}.\n"
            f"Check workspace configuration."
        ) from e

    # Resolve branch
    branch = branch or get_branch()
    if not branch:
        raise RuntimeError("Git branch required for CI triggering.")

    # Format kwargs into GitLab's expected variable structure
    # GitLab API expects: [{"key": "VAR_NAME", "value": "var_value"}]
    formatted_vars = [
        {"key": str(k), "value": str(v)} for k, v in pipeline_vars.items()
    ]
    if formatted_vars:
        print(f"Injecting {formatted_vars} into pipeline")

    # Trigger the pipeline
    p = project.pipelines.create({"ref": branch, "variables": formatted_vars})

    print(f"Pipeline {p.id} triggered on branch '{branch}'")
    print(f"View here: {p.web_url}")
