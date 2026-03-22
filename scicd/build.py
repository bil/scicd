"""
Universal Build Entrypoint for SciCD.
"""

from __future__ import annotations
import dataclasses

import rich

import scicd.config

from scicd.frontend.luigi.encode import luigi2dag
from scicd.backend.export import export_dag
from scicd.yamler import nest_dict

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

    task_overrides_flat = {}
    frontend_params = {}

    # Valid keys for TaskConfig
    valid_task_keys = {f.name for f in dataclasses.fields(scicd.config.TaskConfig)}

    for k, v in kwargs.items():
        # Normalize key to use underscores for comparison (Cyclopts provides dashes)
        norm_k = k.replace("-", "_")
        root_key = norm_k.split(".")[0]

        if root_key in valid_task_keys:
            # Simple type casting for CLI values
            if isinstance(v, str):
                vl = v.lower()
                if vl in ("true", "yes", "1"):
                    v = True
                elif vl in ("false", "no", "0"):
                    v = False
                elif vl.isdigit():
                    v = int(v)

            task_overrides_flat[norm_k] = v
        else:
            frontend_params[k] = v

    # Nest the overrides
    task_overrides = nest_dict(task_overrides_flat)

    # 1. APPLY RUNTIME DEFAULTS
    if task_overrides:

        rich.print(
            f"[bold blue]SciCD:[/bold blue] Applying global TaskConfig overrides: {task_overrides}"
        )
        base_task = scicd.config.get_base_task()
        merged_task = base_task.merge(task_overrides)
        # Update the base task singleton
        scicd.config.set_base_task(merged_task)

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
