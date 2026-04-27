"""
CLI interface for scicd using Cyclopts.

This module defines all user-facing commands for building pipelines, running tasks
locally, and inspecting configuration state.
"""

import os
import sys
from typing import Annotated, Optional, Literal


import rich
from cyclopts import App, Parameter


import scicd.config
import scicd.executor

sys.path.insert(0, os.getcwd())

# App initialization with clear metadata
app = App(name="scicd", help="CI/CD execution for computational DAGs.")
# app.command(luigi_app)
# app.command(make_app)
# app.command(gitlab_app)

# Ensure current project directory is in path for module discovery


@app.command(name="luigi")
def luigi_cmd(*args, **kwargs):
    """
    Luigi sub-application. (Requires 'luigi' installation)
    """
    try:
        from scicd.frontend.luigi import app as luigi_app

        return luigi_app(sys.argv[2:])
    except ImportError:
        rich.print(
            "[red]Error:[/red] Luigi dependencies missing. Install via `pip install scicd[luigi]`"
        )
        sys.exit(1)


@app.command(name="make")
def make_cmd(*args, **kwargs):
    """
    GNU Make sub-application.
    """
    try:
        from scicd.frontend.make import app as make_app

        return make_app(sys.argv[2:])
    except ImportError:
        rich.print("[red]Error:[/red] Make dependencies missing.")
        sys.exit(1)


@app.command(name="gitlab")
def gitlab_cmd(*args, **kwargs):
    """
    Gitlab sub-application.
    """
    try:
        from scicd.backend.gitlab import app as gitlab_app

        return gitlab_app(sys.argv[2:])
    except ImportError:
        rich.print("[red]Error:[/red] Gitlab dependencies missing.")
        sys.exit(1)


@app.command()
def config(config_path: Annotated[Optional[str], Parameter(alias="-c")] = None):
    """
    Show static configuration (before inline overrides)
    """
    rich.print(scicd.config.get_workspace_config(config_path))
    rich.print("[bold]Default Task:[/bold]")
    rich.print(scicd.config.get_task_config(config_path))


@app.command()
def executors():
    """
    Show executor registry.
    """
    registry = scicd.executor.get_registry()
    rich.print(registry)


if __name__ == "__main__":
    app()
