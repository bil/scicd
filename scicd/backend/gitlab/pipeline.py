import os
from pathlib import Path
import gitlab
from dotenv import load_dotenv
from scicd.config import get_workspace
from scicd.git import get_branch


def lint_pipeline(
    yml_filepath: str = ".gitlab-ci.yml", url: str = None, project: str = None
) -> bool:
    """
    Validates the generated GitLab CI/CD YAML file using the GitLab API.

    Args:
        yml_filepath (str): Path to the YAML file to lint. Defaults to ".gitlab-ci.yml".
        url (str, optional): GitLab instance URL.
        project (str, optional): GitLab project path (e.g. org/repo).

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

    url = url or workspace.url
    project = project or workspace.project

    if not url or not project:
        raise RuntimeError(
            "Missing 'url' or 'project' for GitLab API.\n"
            "Please provide them as CLI arguments (--url, --project) "
            "or define them in your workspace configuration."
        )

    # Connect to GitLab and get the project context
    client = gitlab.Gitlab(url, private_token=pat)
    try:
        gl_project = client.projects.get(project)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project}' at {url}.\n"
            f"Check workspace configuration or provided arguments!"
        ) from e

    # Send the content to the project-level CI Linter
    print(f"Linting '{yml_filepath}' against {url}/{project}...")
    try:
        lint_result = gl_project.ci_lint.create({"content": yaml_content})
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


def run_pipeline(
    branch: str = None, url: str = None, project: str = None, **pipeline_vars
):
    """
    Triggers a GitLab pipeline for the project defined in config.yaml.

    Args:
        branch (str, optional): Target git branch. Defaults to current active branch.
        url (str, optional): GitLab instance URL.
        project (str, optional): GitLab project path.
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

    url = url or workspace.url
    project = project or workspace.project

    if not url or not project:
        raise RuntimeError(
            "Missing 'url' or 'project' for GitLab API.\n"
            "Please provide them as CLI arguments (--url, --project) "
            "or define them in your workspace configuration."
        )

    # Connect to GitLab
    client = gitlab.Gitlab(url, private_token=pat)
    try:
        gl_project = client.projects.get(project)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project}' at {url}.\n"
            f"Check workspace configuration or provided arguments."
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
    p = gl_project.pipelines.create({"ref": branch, "variables": formatted_vars})

    print(f"Pipeline {p.id} triggered on branch '{branch}'")
    print(f"View here: {p.web_url}")
