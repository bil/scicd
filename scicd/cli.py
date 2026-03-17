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
def build_gitlab(
    module: Annotated[
        str,
        Parameter(
            help="The Python module containing the Task target.", group="Required"
        ),
    ],
    family: Annotated[str, Parameter(help="The Luigi Task family.", group="Required")],
    yml_filepath: Annotated[
        str, Parameter(help="Output path for the YAML generated file.")
    ] = ".gitlab-ci.yml",
    **overrides: Annotated[
        str,  # Annotated as str so Cyclopts parses --key val pairs correctly
        Parameter(
            help="Dynamic overrides for Luigi params, SciCD config, or GitLab boilerplate (e.g., --cpu 4 --project $CI_PROJECT_PATH)",
            group="Overrides",
        ),
    ],
):
    """
    Compiles a Luigi DAG into a valid .gitlab-ci.yml file.

    This command resolves dependencies, calculates ranks, and maps tasks to GitLab stages.
    Any extra flags are passed as top-level boilerplate to the CI configuration.
    """
    scicd.build.build_gitlab(
        module=module, family=family, yml_filepath=yml_filepath, **overrides
    )


@app.command()
def export_dag(
    module: Annotated[
        str, Parameter(help="The Python module containing the DAG.", group="Required")
    ],
    family: Annotated[
        str, Parameter(help="The base Luigi task family.", group="Required")
    ],
    filepath: Annotated[
        str, Parameter(help="Output path for the Graphviz .dot file.")
    ] = "dag.dot",
    **overrides: Annotated[
        str,
        Parameter(
            help="Config overrides used during DAG generation.", group="Overrides"
        ),
    ],
):
    """
    Exports the task dependency graph to a DOT file for visualization.
    Useful for verifying 'needs' logic before committing to GitLab.
    """
    scicd.build.export_dag(module=module, family=family, filepath=filepath, **overrides)


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
    Inspects the resolved configuration for a specific task family.
    Prints the merged result of default, workspace, and family-level configs.
    """
    result = scicd.config.SciCDConfig(**overrides)
    rich.print(result.config_dict)


@app.command()
def config_key(
    key: Annotated[
        str, Parameter(help="The dot-notated key to retrieve (e.g. All.samples)")
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
    cfg = scicd.config.SciCDConfig(**overrides)
    data = cfg.config_dict

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

    except (KeyError, TypeError):
        rich.print(
            f"[bold red]Error:[/bold red] Key '{key}' not found in configuration."
        )
        raise SystemExit(1)


@app.command()
def config_task(
    family: Annotated[Optional[str], Parameter(help="Task family to inspect.")] = None,
    **overrides: Annotated[
        str,
        Parameter(help="Runtime overrides to apply to the config.", group="Overrides"),
    ],
):
    """
    Inspects the resolved configuration for a specific task family.
    Prints the merged result of default, workspace, and family-level configs.
    """
    result = scicd.config.get_family(family=family, **overrides)
    rich.print(result)


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
