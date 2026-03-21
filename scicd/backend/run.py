def run_pipeline(
    backend: str = "gitlab",
    branch: str = "main",
    url: str = None,
    project: str = None,
    **variables,
):
    """Functional dispatch to trigger a remote CI/CD pipeline."""
    if backend == "gitlab":
        from scicd.backend.gitlab.pipeline import run_pipeline as run_gitlab_pipeline

        run_gitlab_pipeline(branch=branch, url=url, project=project, **variables)
    elif backend == "github":
        raise NotImplementedError("GitHub Actions backend is not yet implemented.")
    else:
        raise ValueError(f"Unsupported backend for triggering pipelines: {backend}")


def lint_pipeline(
    backend: str = "gitlab",
    yml_filepath: str = ".gitlab-ci.yml",
    url: str = None,
    project: str = None,
):
    """Functional dispatch to validate a generated CI/CD YAML file."""
    if backend == "gitlab":
        from scicd.backend.gitlab.pipeline import lint_pipeline as lint_gitlab_pipeline

        return lint_gitlab_pipeline(yml_filepath=yml_filepath, url=url, project=project)
    elif backend == "github":
        raise NotImplementedError("GitHub Actions backend is not yet implemented.")
    else:
        raise ValueError(f"Unsupported backend for linting: {backend}")
