"""GitLab API integration for pipeline linting and triggering."""

import os
from pathlib import Path
import gitlab
from dotenv import load_dotenv
from scicd.config import get_workspace
from scicd.git import get_branch


def lint_pipeline(
    yml_filepath: str = ".gitlab-ci.yml", url: str = None, project: str = None
) -> bool:
    """Validate GitLab CI/CD YAML syntax using the GitLab Lint API."""
    yaml_path = Path(yml_filepath)
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"SciCD Error: Cannot find pipeline file at '{yaml_path.resolve()}'"
        )

    with open(yaml_path, "r", encoding="utf-8") as f:
        yaml_content = f.read()

    dotenv_path = os.path.join(os.getcwd(), ".env")
    load_dotenv(dotenv_path, override=True)

    pat = os.getenv("GITLAB_PAT")
    if not pat:
        raise RuntimeError("Missing 'GITLAB_PAT' in environment or .env file.")

    workspace = get_workspace()
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

    print(f"Linting '{yml_filepath}' against {url}/{project}...")
    try:
        lint_result = gl_project.ci_lint.create({"content": yaml_content})
    except gitlab.exceptions.GitlabCreateError as e:
        raise RuntimeError(f"GitLab API Error during linting: {e}") from e

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


def run_pipeline(
    branch: str = None, url: str = None, project: str = None, **pipeline_vars
):
    """Trigger a remote pipeline run on GitLab."""
    dotenv_path = os.path.join(os.getcwd(), ".env")
    load_dotenv(dotenv_path, override=True)

    pat = os.getenv("GITLAB_PAT")
    if not pat:
        raise RuntimeError("Missing 'GITLAB_PAT' in environment or .env file.")

    workspace = get_workspace()
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

    p = gl_project.pipelines.create({"ref": branch, "variables": formatted_vars})

    print(f"Pipeline {p.id} triggered on branch '{branch}'")
    print(f"View here: {p.web_url}")
