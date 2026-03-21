"""
Luigi frontend for SciCD.
"""

from __future__ import annotations
import importlib
import json
from typing import Any, Dict, List, Tuple

import luigi
from luigi.cmdline_parser import CmdlineParser

import scicd.config
from scicd.frontend.luigi import task as luigi_task
from scicd.yamler import slugify
from scicd.adapter import BaseAdapter
from scicd.dag import DAG, BaseNode, SliceNode, BijectNode


class LuigiAdapter(BaseAdapter):
    """
    Adapter for Luigi task instances.

    Configuration cascade (priority order):
    1. Default from .scicd/config.yaml task: section (lowest)
    2. task.resources() with integer assumptions (medium-high)
    3. task.scicd dict (highest)

    Integer assumptions for task.resources():
    - memory: megabytes (e.g., 8192 = 8GB)
    - disk: gigabytes (e.g. 2 = 2GB)
    - cpu: number of cores
    - gpu: number of gpus
    - time/timeout: minutes
    """

    def __init__(self, work: luigi.Task) -> None:
        """
        Args:
            work: A Luigi Task instance
        """
        super().__init__(work)
        self.work: luigi.Task

    @property
    def name(self) -> str:
        """
        Return the Luigi task family name.

        Returns:
            Task family
        """
        return self.work.task_family

    @property
    def params(self) -> Dict[str, Any]:
        """
        Return task parameters as a serializable dict.

        Returns:
            Dictionary of significant parameter values (all converted to strings)
        """
        params = self.work.to_str_params()
        insignificant = set(params.keys()) - set(self.work.get_param_names())
        for key in insignificant:
            params.pop(key)

        return params

    @property
    def cfg(self) -> scicd.config.TaskConfig:
        """
        Extract task-specific configuration for SciCD.

        Returns:
            Dict with resource configuration compatible with TaskConfig

        Examples:
            >>> class MyTask(luigi.Task):
            ...     def resources(self):
            ...         return {'cpu': 16, 'memory': 65536}  # MB
            ...     scicd = {'memory': '64Gi', 'tags': ['slurm']}
            >>> adapter = LuigiAdapter(MyTask())
            >>> config = adapter.cfg
            >>> config.cpu
            16
            >>> config.memory
            '64Gi'  # scicd dict overrides resources()
        """
        if hasattr(self.work, "task_config"):
            return self.work.task_config

        return luigi_task.get_task_config(self.work)

    @property
    def command(self) -> List[str]:
        """
        Generate the command to run this Luigi task in CI/CD.

        Returns:
            Command array for subprocess execution

        Example:
            ['scicd', 'run',
             '--module', 'workflow',
             '--family', 'MyTask',
             '--params', '{"date": "2024-01-01"}',
             '--frontend', 'luigi']
        """

        return [
            "scicd",
            "run",
            "--module",
            self.work.__class__.__module__,
            "--family",
            self.name,
            "--params",
            json.dumps(self.params),
            "--frontend",
            "luigi",
        ]

    @property
    def identifier(self) -> str:
        """
        Return Luigi's task_id (deterministic hash of family + params).

        Returns:
            Unique identifier (e.g., 'MyTask_2024_01_01_abc123')
        """
        params = self.work.to_str_params(only_significant=True)
        params_str = "_".join([f"{k}_{v}" for k, v in params.items()])
        return slugify(f"{self.name}_{params_str}")[:64]


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
