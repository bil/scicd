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
    # 1. Dynamically import the module
    try:
        mod = importlib.import_module(module)
    except ImportError:
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
    except Exception:  # pylint: disable=broad-exception-caught
        rich.print(
            f"[bold red]Error:[/bold red] Could not instantiate task '{family}' with params {param_dict}"
        )
        sys.exit(1)

    rich.print(f"[bold blue]Executing Luigi Task:[/bold blue] {module}.{family}")
    rich.print(f"[bold blue]Parameters:[/bold blue] {param_dict}")

    # 5. Run the task
    success = luigi.build([task_instance], local_scheduler=True)

    if not success:
        rich.print(f"[bold red]Error:[/bold red] Luigi execution failed for {family}.")
        sys.exit(1)
