"""
CLI interface for SciCD.
"""

import os
import sys
from typing import Annotated, Optional


import rich
from cyclopts import App, Parameter
from dotenv import load_dotenv
from pydantic import BaseModel

import scicd.config
import scicd.executor

sys.path.insert(0, os.getcwd())
load_dotenv(".env")
app = App(name="scicd", help="CI/CD execution for computational DAGs.")
app.command("scicd.frontend.luigi:app", name="luigi")
app.command("scicd.frontend.make:app", name="make")
app.command("scicd.backend.gitlab:app", name="gitlab")


@app.command()
def config(
    config_path: Annotated[
        Optional[str],
        Parameter(alias="-c"),
    ] = None,
    key: Annotated[Optional[str], Parameter(alias="-k")] = None,
):
    """
    Show configuration before inline overrides
    """
    workspace = scicd.config.get_workspace_config(config_path)
    task = scicd.config.get_task_config(config_path)
    if key is not None:
        parts = key.split(sep=".")
        if parts[0] in workspace.model_fields:
            config = workspace
        else:
            if parts[0] not in task.model_fields:
                raise ValueError(
                    f"For key {key}, could not find {parts[0]} in workspace or task configuration"
                )
            config = task
        while parts:
            if isinstance(config, BaseModel):
                config = config.model_dump()
            config = config[parts[0]]
            parts = parts[1:]
        if config is not None:
            print(config)
        return

    rich.print("[bold]Workspace:[/bold]")
    rich.print(workspace)
    rich.print("[bold]Default Task:[/bold]")
    rich.print(task)


@app.command()
def executors():
    """
    Show executor registry.
    """
    registry = scicd.executor.get_registry()
    rich.print(registry)


if __name__ == "__main__":
    app()
