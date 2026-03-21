import importlib
import json
import sys
from typing import Annotated

import luigi
import rich
from cyclopts import App, Parameter

app = App(help="Luigi Worker Entrypoint for SciCD.")

@app.command()
def run_task(
    module: Annotated[
        str, Parameter(help="The Python module containing the Task class.")
    ],
    family: Annotated[str, Parameter(help="The task class name (family).")],
    params: Annotated[str, Parameter(help="JSON string of task parameters.")],
):
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
        # Strip single quotes if they were added for shell escaping
        if params.startswith("'") and params.endswith("'"):
            params = params[1:-1]
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

if __name__ == "__main__":
    app()
