"""
CLI interface for scicd using Typer.
"""

import os
import sys
from typing import Optional

import typer

import scicd.build
import scicd.gitlab
import scicd.config

# Create the main app object
app = typer.Typer(help="CLI interface for scicd.")

# Ensure current project directory is in path
sys.path.insert(0, os.getcwd())


@app.command()
def build_gitlab(module: str, family: str, yml_filepath: str = ".gitlab-ci.yml"):
    """Compiles the Luigi DAG into a GitLab CI/CD YAML file."""
    scicd.build.build_gitlab(module=module, family=family, yml_filepath=yml_filepath)


@app.command()
def lint_gitlab(yml_filepath: str = ".gitlab-ci.yml"):
    """Validates the generated YAML against the GitLab API."""
    if not scicd.gitlab.lint_pipeline(yml_filepath=yml_filepath):
        raise typer.Exit(code=1)


@app.command()
def run_gitlab_pipeline(branch: str = "main"):
    """Triggers the pipeline on GitLab."""
    scicd.gitlab.run_pipeline(branch=branch)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def config(ctx: typer.Context, family: Optional[str] = None):
    """Inspects the resolved CI/CD configuration."""
    overrides = {}
    for extra in ctx.args:
        if "=" in extra:
            key, val = extra.lstrip("-").split("=", 1)
            overrides[key] = val

    result = scicd.config.get_config(family=family, **overrides)
    print(result)


if __name__ == "__main__":
    app()
