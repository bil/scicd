"""
CLI interface for scicd using Cyclopts.
"""

import os
import sys
from typing import Annotated, Optional

import rich
from cyclopts import App, Parameter

import scicd.build
import scicd.gitlab
import scicd.config

# App initialization with clear metadata
app = App(
    name="scicd", help="Scientific CI/CD: Orchestrate Luigi DAGs on GitLab pipelines."
)

# Ensure current project directory is in path for module discovery
sys.path.insert(0, os.getcwd())


@app.command()
def run_luigi(
    module: Annotated[
        str, Parameter(help="The Python module containing the Task class.")
    ],
    family: Annotated[str, Parameter(help="The Luigi task class name (family).")],
    params: Annotated[str, Parameter(help="JSON string of task parameters.")],
):
    """
    Worker entrypoint to execute a single Luigi task.
    Used by CI jobs to run the actual work unit.
    """
    import importlib
    import json
    import luigi

    # 1. Dynamically import the module
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        rich.print(f"[bold red]Error:[/bold red] Could not find module '{module}'")
        sys.exit(1)

    # 2. Get the task class from the module
    try:
        task_cls = getattr(mod, family)
    except AttributeError:
        rich.print(
            f"[bold red]Error:[/bold red] Module '{module}' has no class named '{family}'"
        )
        sys.exit(1)

    # 3. Parse parameters
    try:
        param_dict = json.loads(params)
    except json.JSONDecodeError:
        rich.print(
            f"[bold red]Error:[/bold red] Invalid JSON provided for params: {params}"
        )
        sys.exit(1)

    # 4. Instantiate and Execute via Luigi
    try:
        task_instance = task_cls.from_str_params(param_dict)
    except Exception as e:
        rich.print(
            f"[bold red]Error:[/bold red] Could not instantiate task '{family}' with params {param_dict}"
        )
        print(str(e))
        sys.exit(1)

    rich.print(f"[bold blue]Executing Luigi Task:[/bold blue] {module}.{family}")
    rich.print(f"[bold blue]Parameters:[/bold blue] {param_dict}")

    # 5. Run the task
    success = luigi.build([task_instance], local_scheduler=True)

    if not success:
        rich.print(f"[bold red]Error:[/bold red] Luigi execution failed for {family}.")
        sys.exit(1)


@app.command()
def build(
    module: Annotated[
        str,
        Parameter(help="The Python module containing the target.", group="Required"),
    ],
    target: Annotated[
        str, Parameter(help="The target class/family.", group="Required")
    ],
    frontend: Annotated[
        str, Parameter(help="Frontend to parse the DAG (e.g. luigi)")
    ] = "luigi",
    backend: Annotated[
        str, Parameter(help="Backend to render the DAG (e.g. gitlab, dot)")
    ] = "gitlab",
    filepath: Annotated[
        Optional[str], Parameter(help="Output path for the generated file.")
    ] = None,
    **kwargs: Annotated[str, Parameter(help="Dynamic overrides", group="Overrides")],
):
    """
    Compiles a target into a CI/CD pipeline or visualization.
    """
    scicd.build.build(
        module=module,
        target=target,
        frontend=frontend,
        backend=backend,
        filepath=filepath,
        **kwargs,
    )


@app.command()
def lint_gitlab(
    yml_filepath: Annotated[
        str, Parameter(help="Path to the YAML file to validate.")
    ] = ".gitlab-ci.yml",
):
    """
    Validates the generated YAML against the GitLab Lint API.
    Requires valid CI_SERVER_URL and PRIVATE_TOKEN environment variables.
    """
    if not scicd.gitlab.lint_pipeline(yml_filepath=yml_filepath):
        sys.exit(1)


@app.command()
def run_gitlab_pipeline(
    branch: Annotated[str, Parameter(help="The branch to trigger on.")] = "main",
    **variables: Annotated[
        str,
        Parameter(
            help="CI/CD variables passed to the pipeline trigger.", group="Variables"
        ),
    ],
):
    """
    Triggers a remote GitLab pipeline execution.
    Usage: scicd run-gitlab-pipeline --branch develop --RUNNER internal --DEBUG true
    """
    scicd.gitlab.run_pipeline(branch=branch, **variables)


@app.command()
def config(
    **overrides: Annotated[
        str,
        Parameter(help="Runtime overrides to apply to the config.", group="Overrides"),
    ],
):
    """
    Inspects the global and task-level configuration.
    Prints the loaded config state.
    """
    import dataclasses

    workspace = scicd.config.get_workspace()
    task_cfg = scicd.config.get_task_config(**overrides)

    rich.print("[bold green]Workspace Config:[/bold green]")
    rich.print(dataclasses.asdict(workspace))
    rich.print("\n[bold green]Task Config (with overrides):[/bold green]")
    rich.print(dataclasses.asdict(task_cfg))


@app.command()
def config_key(
    key: Annotated[
        str,
        Parameter(
            help="The dot-notated key to retrieve from workspace or task config (e.g. task.cpu)"
        ),
    ],
    **overrides: Annotated[
        str,
        Parameter(
            help="Runtime overrides to apply before extraction.", group="Overrides"
        ),
    ],
):
    """
    Extracts a specific value from the configuration using a key path.
    Useful for shell scripts and CI/CD variables.
    """
    import dataclasses

    workspace_dict = dataclasses.asdict(scicd.config.get_workspace())
    task_dict = dataclasses.asdict(scicd.config.get_task_config(**overrides))

    # Create a unified dictionary for querying
    data = {"workspace": workspace_dict, "task": task_dict}

    # Traverse the dictionary using the dot-separated key
    try:
        parts = key.split(".")
        for part in parts:
            data = data[part]

        # Print the raw value (or rich print if it's a complex object)
        if isinstance(data, (dict, list)):
            rich.print(data)
        else:
            print(data)

    except (KeyError, TypeError) as e:
        rich.print(
            f"[bold red]Error:[/bold red] Key '{key}' not found in configuration. Start with 'workspace.' or 'task.'."
        )
        raise SystemExit(1) from e


@app.command()
def config_task(
    **overrides: Annotated[
        str,
        Parameter(help="Runtime overrides to apply to the config.", group="Overrides"),
    ],
):
    """
    Inspects the resolved task configuration.
    """
    import dataclasses

    result = scicd.config.get_task_config(**overrides)
    rich.print(dataclasses.asdict(result))


@app.command()
def config_workspace():
    """
    Inspects the resolved configuration for a specific task family.
    Prints the merged result of default, workspace, and family-level configs.
    """
    result = scicd.config.get_workspace()
    rich.print(result)


if __name__ == "__main__":
    app()
