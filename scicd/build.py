"""
Universal Build Entrypoint for SciCD.
"""

from __future__ import annotations

import rich

import scicd.config

from scicd.frontend.luigi.encode import luigi2dag
from scicd.backend.export import export_dag

# =============================================================================
# UNIVERSAL BUILD ENTRYPOINT
# =============================================================================


def build(
    module: str,
    target: str,
    frontend: str = "luigi",
    backend: str = None,
    filepath: str = None,
    **kwargs,
):
    """
    Universal build function.
    Frontends encode a framework target into an abstract DAG.
    Backends export the abstract DAG into a target format.

    CLI Argument Namespacing:
    --------------------------
    - TaskConfig fields (cpu, memory, image): Override task defaults directly (e.g., --cpu 8).
    - workspace_<key>: Blocked. Workspace settings must be set in config files.
    - <other>:      Passed directly to the frontend (e.g., Luigi task params).
                    For Luigi, use --TaskName-param val for task-specific params.
    """

    wspace = scicd.config.get_workspace()
    if backend is None:
        backend = wspace.platform

    frontend_params = scicd.config.intercept_cli_overrides(kwargs)

    # FRONTEND
    if frontend == "luigi":
        rich.print(
            f"[bold blue]SciCD:[/bold blue] Initializing Luigi frontend for {module}.{target}"
        )
        if frontend_params:
            rich.print(f"  -> Passing params to Luigi: {frontend_params}")
        dag = luigi2dag(module, target, **frontend_params)
    else:
        raise ValueError(f"Unsupported frontend: {frontend}")

    # BACKEND
    boilerplate = wspace.cicd
    export_dag(dag, filepath=filepath, backend=backend, **boilerplate)
    rich.print(f"[bold green]SciCD:[/bold green] Generated {backend} output")
