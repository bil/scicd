import importlib
import json
import sys

import luigi
import rich


def run_task(module: str, family: str, params: str):
    """
    Worker entrypoint to execute a single Luigi task.
    Used by CI jobs to run the actual work unit.
    """
    # Dynamically import the module
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        rich.print(f"[bold red]Error:[/bold red] Could not find module '{module}'")
        raise e

    # Get the task class from the module
    try:
        task_cls = getattr(mod, family)
    except AttributeError as e:
        rich.print(
            f"[bold red]Error:[/bold red] Module '{module}' has no class named '{family}'"
        )
        raise e

    # Parse parameters
    try:
        param_dict = json.loads(params)
    except json.JSONDecodeError as e:
        rich.print(
            f"[bold red]Error:[/bold red] Invalid JSON provided for params: {params}"
        )
        raise e

    # Instantiate and Execute via Luigi
    try:
        print(param_dict)
        task_instance = task_cls(**param_dict)  # .from_str_params(param_dict)
    except Exception as e:
        rich.print(
            f"[bold red]Error:[/bold red] Could not instantiate task '{family}' with params {param_dict}"
        )
        raise e

    rich.print(f"[bold blue]Executing Luigi Task:[/bold blue] {module}.{family}")
    rich.print(f"[bold blue]Parameters:[/bold blue] {param_dict}")

    # Run the task
    success = luigi.build([task_instance], local_scheduler=True)

    if not success:
        rich.print(f"[bold red]Error:[/bold red] Luigi execution failed for {family}.")
        sys.exit(1)
