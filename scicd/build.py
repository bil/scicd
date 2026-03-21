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

from scicd.config import (
    get_workspace,
    TaskConfig,
    WorkspaceConfig,
    _ConfigManager,
)
from scicd.dag import DAG, BaseNode, SliceNode, BijectNode
from scicd.adapter import LuigiAdapter

# =============================================================================
# FRONTENDS (Target -> DAG)
# =============================================================================


def luigi2dag(module: str, target: str, **kwargs) -> DAG:
    """
    Orchestrates the conversion of a Luigi task tree into a SciCD DAG.
    """
    target_task = load_luigi_task(module, target, **kwargs)

    # Discover tasks and compute rank (0 is a leaf, N is the target)
    all_tasks, task_ranks = _discover_and_rank_luigi(target_task)

    # Group tasks into Node objects (Slice vs Biject) using Adapters
    task_id_to_node = _group_tasks_into_nodes_luigi(all_tasks, task_ranks)

    # Connect the Node objects
    unique_nodes = list({id(n): n for n in task_id_to_node.values()}.values())
    _build_dag_edges_luigi(unique_nodes, task_id_to_node)

    # Wrap in a DAG container
    return DAG(nodes=unique_nodes)


def load_luigi_task(module: str, target: str, **kwargs) -> luigi.Task:
    """Programmatically loads a task, injecting parameters."""
    cmdline_args = ["--module", module, target]

    for key, val in kwargs.items():
        # Luigi parser expects dashes
        formatted_key = key.replace("_", "-")
        cmdline_args.extend([f"--{formatted_key}", str(val)])

    # Ensure the module is imported so Luigi knows the Task exists
    importlib.import_module(module)

    # Sets CmdlineParser._instance so Task constructors can find it.
    with CmdlineParser.global_instance(cmdline_args) as cp:
        task = cp.get_task_obj()

    return task


def _discover_and_rank_luigi(
    target_task: luigi.Task,
) -> Tuple[Dict[str, luigi.Task], Dict[str, int]]:
    """Walks the task tree to discover nodes and rank them topologically."""
    all_tasks: Dict[str, luigi.Task] = {}

    def find_all(task: luigi.Task):
        if task.task_id not in all_tasks:
            all_tasks[task.task_id] = task
            for dep in luigi.task.flatten(task.requires()):
                find_all(dep)

    find_all(target_task)

    task_ranks: Dict[str, int] = {}

    def get_rank(task: luigi.Task) -> int:
        if task.task_id in task_ranks:
            return task_ranks[task.task_id]

        deps = luigi.task.flatten(task.requires())
        if not deps:
            rank = 0
        else:
            rank = max(get_rank(d) for d in deps) + 1

        task_ranks[task.task_id] = rank
        return rank

    for task_instance in all_tasks.values():
        get_rank(task_instance)

    return all_tasks, task_ranks


def _group_tasks_into_nodes_luigi(
    all_tasks: Dict[str, luigi.Task], task_ranks: Dict[str, int]
) -> Dict[str, BaseNode]:
    """Wraps tasks in Adapters and groups them into Nodes based on ConcurrencyConfig."""
    task_id_to_node: Dict[str, BaseNode] = {}
    temp_slices: Dict[Tuple[str, int], SliceNode] = {}

    for tid, task in all_tasks.items():
        rank = task_ranks[tid]
        adapter = LuigiAdapter(task)

        # Use the adapter's resolved configuration to determine node type
        if adapter.cfg.concurrency.method == "slice":
            key = (adapter.name, rank)
            if key not in temp_slices:
                temp_slices[key] = SliceNode(work=[], rank=rank, node_deps=[])

            node = temp_slices[key]
            node.work.append(adapter)
            task_id_to_node[tid] = node
        else:
            # Biject: 1 Node per Adapter
            node = BijectNode(work=[adapter], rank=rank, node_deps=[])
            task_id_to_node[tid] = node

    return task_id_to_node


def _build_dag_edges_luigi(
    unique_nodes: List[BaseNode], task_id_to_node: Dict[str, BaseNode]
):
    """Translates adapter dependencies into Node dependencies."""
    for node in unique_nodes:
        for adapter in node.work:
            for dep_task in luigi.task.flatten(adapter.work.requires()):
                parent_node = task_id_to_node.get(dep_task.task_id)

                if parent_node and parent_node is not node:
                    if parent_node not in node.node_deps:
                        node.node_deps.append(parent_node)


# =============================================================================
# BACKENDS (DAG -> Output)
# =============================================================================


def export_gitlab(dag: DAG, filepath: str = ".gitlab-ci.yml"):
    """Renders the abstract DAG into a GitLab CI/CD pipeline."""
    wspace = get_workspace()

    # Extract workspace boilerplate (default/workflow blocks from scicd.yaml)
    boilerplate = {}
    if wspace.cicd:
        if wspace.cicd:
            boilerplate.update(wspace.cicd)

    dag.write_gitlab_yaml(filepath=filepath, **boilerplate)


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
    import dataclasses
    import scicd.config
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
        scicd.config._ConfigManager._base_task = merged_task

    # 2. FRONTEND
    if frontend == "luigi":
        rich.print(
            f"[bold blue]SciCD:[/bold blue] Initializing Luigi frontend for {module}.{target}"
        )
        if frontend_params:
            rich.print(f"  -> Passing params to Luigi: {frontend_params}")
        dag = luigi2dag(module, target, **frontend_params)
    else:
        raise ValueError(f"Unsupported frontend: {frontend}")

    # 3. BACKEND
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
