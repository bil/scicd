"""
Module docstring.
"""

import os
from pathlib import Path

import gitlab
from dotenv import load_dotenv

import scicd.yamler
from scicd.config import TaskConfig, get_workspace
from scicd.git import get_branch
from scicd.executor import get_executor


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
    if cfg.cicd_config:
        info = scicd.yamler.deep_update(info, dict(cfg.cicd_config))

    return info


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

    if not workspace.repository or workspace.repository.platform != "gitlab":
        raise RuntimeError("Workspace repository is not configured for GitLab.")

    url = workspace.repository.url
    project_path = workspace.repository.project

    if not project_path or not url:
        raise RuntimeError(
            "Missing repository 'url' or 'project' in .scicd/config.yaml"
        )

    # Connect to GitLab and get the project context
    client = gitlab.Gitlab(url, private_token=pat)
    try:
        project = client.projects.get(project_path)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project_path}' at {url}.\n"
            f"Check repository configuration in .scicd/config.yaml."
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

    if not workspace.repository or workspace.repository.platform != "gitlab":
        raise RuntimeError("Workspace repository is not configured for GitLab.")

    url = workspace.repository.url
    project_path = workspace.repository.project

    if not project_path or not url:
        raise RuntimeError(
            "Missing repository 'url' or 'project' in .scicd/config.yaml"
        )

    # Connect to GitLab
    client = gitlab.Gitlab(url, private_token=pat)
    try:
        project = client.projects.get(project_path)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project_path}' at {url}.\n"
            f"Check repository configuration in .scicd/config.yaml."
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
