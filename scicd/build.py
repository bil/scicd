"""
Universal Build Entrypoint for SciCD.
"""

from __future__ import annotations
import importlib
import dataclasses
from typing import Dict, List, Tuple

import luigi
import rich
from luigi.cmdline_parser import CmdlineParser

import scicd.config

from scicd.config import get_workspace
from scicd.dag import DAG, BaseNode, SliceNode, BijectNode
from scicd.frontend.luigi import luigi2dag
from scicd.backend.gitlab import export_gitlab

# =============================================================================
# BACKENDS (DAG -> Output)
# =============================================================================


def export_dot(dag: DAG, filepath: str = "dag.dot"):
    """Exports the DAG to Graphviz for visualization."""
    dag.export_dot(filepath)


# =============================================================================
# UNIVERSAL BUILD ENTRYPOINT
# =============================================================================


def build(
    module: str,
    target: str,
    frontend: str = "luigi",
    backend: str = "gitlab",
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

    task_overrides = {}
    frontend_params = {}

    # Valid keys for TaskConfig
    valid_task_keys = {f.name for f in dataclasses.fields(scicd.config.TaskConfig)}
    # Keys that belong to WorkspaceConfig (we want to block these from direct CLI overrides)
    protected_keys = {f.name for f in dataclasses.fields(scicd.config.WorkspaceConfig)}

    for k, v in kwargs.items():
        # Normalize key to use underscores for comparison (Cyclopts provides dashes)
        norm_k = k.replace("-", "_")
        root_key = norm_k.split(".")[0]

        if root_key in valid_task_keys:
            parts = norm_k.split(".")
            current = task_overrides
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Simple type casting for CLI values
            if isinstance(v, str):
                vl = v.lower()
                if vl in ("true", "yes", "1"):
                    v = True
                elif vl in ("false", "no", "0"):
                    v = False
                elif vl.isdigit():
                    v = int(v)

            current[parts[-1]] = v
        elif root_key in protected_keys or root_key.startswith("workspace_"):
            rich.print(
                f"[bold red]Security Warning:[/bold red] Workspace override '{norm_k}' is not permitted via CLI. Ignoring."
            )
        else:
            frontend_params[k] = v

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
    if backend == "gitlab":
        out_path = filepath or ".gitlab-ci.yml"
        export_gitlab(dag, out_path)
        rich.print(
            f"[bold green]SciCD:[/bold green] Generated GitLab CI pipeline at {out_path}"
        )
    elif backend == "dot":
        out_path = filepath or "dag.dot"
        export_dot(dag, out_path)
        rich.print(
            f"[bold green]SciCD:[/bold green] Generated Graphviz DOT file at {out_path}"
        )
    else:
        raise ValueError(f"Unsupported backend: {backend}")
