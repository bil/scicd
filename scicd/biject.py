"""
Execution entrypoint for BijectNodes in SciCD.
"""

import json
import importlib
import sys
import os
from typing import Annotated

import luigi
from cyclopts import App, Parameter

# Initialize Cyclopts
app = App(help="Biject execution engine for SciCD.")

# Ensure current directory is in path for module discovery
sys.path.insert(0, os.getcwd())


@app.command()
def run(
    module: Annotated[str, Parameter(help="The Python module where the task lives")],
    family: Annotated[str, Parameter(help="The Luigi task class name (family)")],
    params_json: Annotated[str, Parameter(help="JSON string of task parameters")],
):
    """
    Dynamically imports and executes a single Luigi task instance.
    Used primarily by BijectNodes within a GitLab CI job.
    """
    # Dynamically import the module
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        print(f"Error: Could not find module {module}")
        raise e

    # Get the task class from the module
    try:
        task_cls = getattr(mod, family)
    except AttributeError:
        print(f"Error: Module {module} has no class named {family}")
        raise

    # Parse parameters
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON provided for params: {params_json}")
        raise e

    # Instantiate and Execute via Luigi
    # from_str_params is the standard Luigi way to inject dict values
    task_instance = task_cls.from_str_params(params)

    print(f"Running {module}.{family}")
    print(f"Parameters: {params}")

    # local_scheduler=True is typical for containerized workers
    success = luigi.build([task_instance], local_scheduler=True)

    if not success:
        print("Luigi execution failed.")
        sys.exit(1)


if __name__ == "__main__":
    app()
