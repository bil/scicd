"""
CLI interface for scicd using Typer.
"""

import os
import sys
from typing import Optional, Annotated, List

import typer
from typer import Option, Argument

import scicd.build
import scicd.gitlab
import scicd.config

app = typer.Typer(help="CLI interface for scicd.", add_completion=False)

# Ensure current project directory is in path
sys.path.insert(0, os.getcwd())


def _parse_kv_list(kv_list: Optional[List[str]]) -> dict:
    """Helper to convert ['KEY=VAL', '--FLAG=VAL'] into {'KEY': 'VAL', 'FLAG': 'VAL'}"""
    if not kv_list:
        return {}
    return {
        item.lstrip("-").split("=", 1)[0]: item.split("=", 1)[1]
        for item in kv_list
        if "=" in item
    }


@app.command()
def build_gitlab(
    module: Annotated[str, Option(help="The Python module containing the DAG.")],
    family: Annotated[str, Option(help="The base Luigi task family.")],
    yml_filepath: Annotated[
        str, Option(help="Output path for the YAML.")
    ] = ".gitlab-ci.yml",
):
    """Compiles the Luigi DAG into a GitLab CI/CD YAML file."""
    scicd.build.build_gitlab(module=module, family=family, yml_filepath=yml_filepath)


@app.command()
def lint_gitlab(
    yml_filepath: Annotated[
        str, Option(help="Path to the YAML file to validate.")
    ] = ".gitlab-ci.yml",
):
    """Validates the generated YAML against the GitLab API."""
    if not scicd.gitlab.lint_pipeline(yml_filepath=yml_filepath):
        raise typer.Exit(code=1)


@app.command()
def run_gitlab_pipeline(
    branch: Annotated[str, Option(help="The branch to trigger on.")] = "main",
    variables: Annotated[
        Optional[List[str]], Argument(help="Extra variables (KEY=VALUE).")
    ] = None,
):
    """Usage: scicd run-gitlab-pipeline --branch main RUNNER=worm ENV=prod"""
    vars_dict = _parse_kv_list(variables)
    scicd.gitlab.run_pipeline(branch=branch, **vars_dict)


@app.command()
def config(
    family: Annotated[Optional[str], Option(help="Task family to inspect.")] = None,
    overrides: Annotated[
        Optional[List[str]], Argument(help="Config overrides (key=value).")
    ] = None,
):
    """Usage: scicd config --family TaskA cpu=4 memory=8Gi"""
    kv_overrides = _parse_kv_list(overrides)
    result = scicd.config.get_config(family=family, **kv_overrides)
    typer.echo(result)


if __name__ == "__main__":
    app()
