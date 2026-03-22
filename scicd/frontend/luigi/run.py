"""Worker entrypoint for executing Luigi tasks."""

import importlib
import json
import sys

import luigi
import rich


def run_task(module: str, target: str, params: str):
    """Instantiate and execute a single Luigi task."""
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        rich.print(f"[bold red]Error:[/bold red] Could not find module '{module}'")
        raise e

    try:
        task_cls = getattr(mod, target)
    except AttributeError as e:
        rich.print(
            f"[bold red]Error:[/bold red] Module '{module}' has no class named '{target}'"
        )
        raise e

    try:
        param_dict = json.loads(params)
    except json.JSONDecodeError as e:
        rich.print(
            f"[bold red]Error:[/bold red] Invalid JSON provided for params: {params}"
        )
        raise e

    try:
        task_instance = task_cls(**param_dict)
    except Exception as e:
        rich.print(
            f"[bold red]Error:[/bold red] Could not instantiate task '{target}' with params {param_dict}"
        )
        raise e

    rich.print(f"[bold blue]Executing Luigi Task:[/bold blue] {module}.{target}")
    rich.print(f"[bold blue]Parameters:[/bold blue] {param_dict}")

    success = luigi.build([task_instance], local_scheduler=True)

    if not success:
        rich.print(f"[bold red]Error:[/bold red] Luigi execution failed for {target}.")
        sys.exit(1)
