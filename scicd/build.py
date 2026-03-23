"""
Universal Build Orchestrator for SciCD.

This module provides the top-level 'build' entrypoint that coordinates frontends
(framework-specific DAG encoders) and backends (platform-specific YAML generators).
"""

from __future__ import annotations
from typing import Optional

import rich
import scicd.config
from scicd.frontend.luigi.encode import luigi2dag
from scicd.backend.export import export_dag


def build(
    module: str,
    target: str,
    frontend: str = "luigi",
    backend: Optional[str] = None,
    filepath: Optional[str] = None,
    **kwargs,
):
    """
    Execute the full SciCD build pipeline.

    1. Intercepts global TaskConfig overrides from kwargs.
    2. Resolves the framework-specific target into an abstract DAG.
    3. Exports the DAG into the requested backend format (e.g., GitLab YAML).

    Args:
        module: Python module containing the target work.
        target: The specific class or rule name to build.
        frontend: Framework to use for DAG resolution (default: 'luigi').
        backend: Target platform format (e.g., 'gitlab'). Defaults to workspace platform.
        filepath: Optional custom output path for the generated file.
        **kwargs: Dynamic task-level overrides and frontend-specific parameters.
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
