import os
import gitlab
from dotenv import load_dotenv
from .config import SciCDConfig

# Assuming you still have a helper to get the current git branch
from scicd.paths import get_branch


def run_pipeline(branch: str = None, **pipeline_vars):
    """
    Triggers a GitLab pipeline for the project defined in pyproject.toml.

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

    # Grab the global config from pyproject.toml
    # Passing an empty string or None gets the pure global state without task overrides
    config = SciCDConfig().workspace_config()

    url = config.gitlab_url
    project_path = config.gitlab_project

    if not project_path:
        raise RuntimeError(
            "Missing 'gitlab_project' in [tool.scicd] of pyproject.toml."
        )

    # Connect to GitLab
    client = gitlab.Gitlab(url, private_token=pat)
    try:
        project = client.projects.get(project_path)
    except gitlab.exceptions.GitlabGetError as e:
        raise RuntimeError(
            f"Could not find GitLab project: '{project_path}' at {url}.\n"
            f"Check 'gitlab_project' in pyproject.toml."
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

    # Trigger the pipeline
    p = project.pipelines.create({"ref": branch, "variables": formatted_vars})

    print(f"🚀 SciCD: Pipeline {p.id} triggered on branch '{branch}'")
    print(f"🔗 View here: {p.web_url}")

    if formatted_vars:
        print(f" injected {len(formatted_vars)} pipeline variables.")
