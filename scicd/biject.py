import luigi
import json
import typer
import importlib
from typing import Annotated

# Initialize Typer
app = typer.Typer()


@app.command()
def run(
    module: Annotated[str, typer.Option(help="The Python module where the task lives")],
    family: Annotated[str, typer.Option(help="The Luigi task class name")],
    params_json: Annotated[str, typer.Option(help="JSON string of task parameters")],
):
    """
    Executes a specific Luigi task via dynamic import.
    """
    # Dynamically import the module
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        print(f"Error: Could not find module {module}")
        raise e

    # Get the class from the module
    try:
        task_cls = getattr(mod, family)
    except AttributeError:
        print(f"Error: Module {module} has no class named {family}")
        raise

    # Load params (Guaranteed to be a string by Typer)
    params = json.loads(params_json)

    # Instantiate via Luigi's helper
    task_instance = task_cls.from_str_params(params)

    # Execute
    print(f"--- Running {module}.{family} with params: {params} ---")
    luigi.build([task_instance], local_scheduler=True)


@app.command(hidden=True)
def placeholder():
    """This ensures Typer never 'collapses' the CLI structure."""


if __name__ == "__main__":
    app()
