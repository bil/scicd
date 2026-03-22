"""
CLI interface for scicd using Cyclopts.
"""

import os
import dataclasses
import sys
from typing import Annotated, Optional


import rich
from cyclopts import App, Parameter
import luigi

import scicd.build
import scicd.frontend.luigi.run
import scicd.backend.run
import scicd.config
from scicd.frontend.luigi.encode import load_luigi_task

# App initialization with clear metadata
app = App(
    name="scicd", help="Scientific CI/CD: Orchestrate Luigi DAGs on GitLab pipelines."
)

# Ensure current project directory is in path for module discovery
sys.path.insert(0, os.getcwd())


@app.command()
def run(
    module: Annotated[
        str, Parameter(help="The Python module containing the Task class.")
    ],
    target: Annotated[str, Parameter(help="The task class name (target).")],
    params: Annotated[str, Parameter(help="JSON string of task parameters.")],
    frontend: Annotated[str, Parameter(help="Frontend framework to use.")] = "luigi",
):
    """
    Worker entrypoint to execute a single task.
    Used by CI jobs to run the actual work unit.
    """
    if frontend != "luigi":
        raise ValueError(f"Unsupported frontend: {frontend}")

    scicd.frontend.luigi.run.run_task(module, target, params)


@app.command()
def local(
    module: Annotated[
        str, Parameter(help="The Python module containing the target.", group="Required")
    ],
    target: Annotated[
        str, Parameter(help="The target class.", group="Required")
    ],
    frontend: Annotated[
        str, Parameter(help="Frontend to parse the DAG (e.g. luigi)")
    ] = "luigi",
    **kwargs: Annotated[str, Parameter(help="Dynamic overrides", group="Overrides")],
):
    """Run a task locally for development."""
    frontend_params = scicd.config.intercept_cli_overrides(kwargs)
    
    if frontend == "luigi":
        task = load_luigi_task(module, target, **frontend_params)
        luigi.build([task], local_scheduler=True)
    else:
        raise ValueError(f"Unsupported frontend: {frontend}")


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
        Optional[str], Parameter(help="Backend to render the DAG (e.g. gitlab, dot)")
    ] = None,
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
def lint_cicd(
    yml_filepath: Annotated[
        str, Parameter(help="Path to the YAML file to validate.")
    ] = ".gitlab-ci.yml",
    backend: Annotated[
        Optional[str], Parameter(help="Backend platform (e.g., gitlab).")
    ] = None,
    url: Annotated[
        Optional[str], Parameter(help="Platform URL (e.g., https://gitlab.com).")
    ] = None,
    project: Annotated[
        Optional[str], Parameter(help="Project path (e.g., org/repo).")
    ] = None,
):
    """
    Validates the generated YAML against the specified CI/CD Lint API.
    """
    if backend is None:
        backend = scicd.config.get_workspace().platform

    if not scicd.backend.run.lint_pipeline(
        backend=backend, yml_filepath=yml_filepath, url=url, project=project
    ):
        sys.exit(1)


@app.command()
def run_pipeline(
    branch: Annotated[str, Parameter(help="The branch to trigger on.")] = "main",
    backend: Annotated[
        Optional[str], Parameter(help="Backend platform (e.g., gitlab).")
    ] = None,
    url: Annotated[
        Optional[str], Parameter(help="Platform URL (e.g., https://gitlab.com).")
    ] = None,
    project: Annotated[
        Optional[str], Parameter(help="Project path (e.g., org/repo).")
    ] = None,
    **variables: Annotated[
        str,
        Parameter(
            help="CI/CD variables passed to the pipeline trigger.", group="Variables"
        ),
    ],
):
    """
    Triggers a remote CI/CD pipeline execution.
    """
    if backend is None:
        backend = scicd.config.get_workspace().platform

    scicd.backend.run.run_pipeline(
        backend=backend, branch=branch, url=url, project=project, **variables
    )


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
    scicd.config.intercept_cli_overrides(overrides)

    workspace = scicd.config.get_workspace()
    task_cfg = scicd.config.get_task_config()

    rich.print("[bold green]Workspace Config:[/bold green]")
    rich.print(dataclasses.asdict(workspace))
    rich.print("\n[bold green]Task Config (with overrides):[/bold green]")
    rich.print(dataclasses.asdict(task_cfg))


@app.command()
def config_key(
    key: Annotated[
        str,
        Parameter(
            help="The dot-notated key to retrieve from config (e.g. workspace.url, remote.pull_inputs, cpu)"
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
    scicd.config.intercept_cli_overrides(overrides)

    workspace_dict = dataclasses.asdict(scicd.config.get_workspace())
    task_dict = dataclasses.asdict(scicd.config.get_task_config())

    # Create a unified dictionary for querying (flat structure matching scicd.yaml)
    data = {"workspace": workspace_dict, **task_dict}

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
            f"[bold red]Error:[/bold red] Key '{key}' not found in configuration. "
            "Top-level namespaces include: workspace, remote, concurrency, queue, cpu, etc."
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
    scicd.config.intercept_cli_overrides(overrides)
    result = scicd.config.get_task_config()
    rich.print(dataclasses.asdict(result))


@app.command()
def config_workspace():
    """
    Inspects the resolved workspace configuration.
    """
    result = scicd.config.get_workspace()
    rich.print(result)


if __name__ == "__main__":
    app()
