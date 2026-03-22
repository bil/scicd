"""Luigi frontend for SciCD DAG encoding."""

from __future__ import annotations
import importlib
from typing import Any, Tuple

import luigi
from luigi.cmdline_parser import CmdlineParser

import scicd.config
from scicd.frontend.luigi import task as luigi_task
from scicd.yamler import slugify
from scicd.adapter import BaseAdapter
from scicd.config import DynamicModel
from scicd.dag import DAG, BaseNode, SliceNode, BijectNode


class LuigiAdapter(BaseAdapter):
    """Adapter for mapping Luigi tasks to SciCD work units."""

    def __init__(self, work: luigi.Task) -> None:
        super().__init__(work)
        self.work: luigi.Task

    @property
    def name(self) -> str:
        """Return Luigi task family name."""
        return self.work.task_family

    @property
    def params(self) -> DynamicModel:
        """Return significant task parameters as a DynamicModel."""
        params = self.work.to_str_params()
        insignificant = set(params.keys()) - set(self.work.get_param_names())
        for key in insignificant:
            params.pop(key)

        return DynamicModel.model_validate(params)

    @property
    def cfg(self) -> scicd.config.TaskConfig:
        """Return resolved TaskConfig for the Luigi task."""
        if hasattr(self.work, "task_config"):
            return self.work.task_config

        return luigi_task.get_task_config(self.work)

    @property
    def command(self) -> list[str]:
        """Generate 'scicd run' command for CI/CD execution."""
        return [
            "scicd",
            "run",
            "--module",
            self.work.__class__.__module__,
            "--target",
            self.name,
            "--frontend",
            "luigi",
        ]

    @property
    def identifier(self) -> str:
        """Generate deterministic unique identifier from task family and params."""
        params = self.work.to_str_params(only_significant=True)
        params_str = "_".join([f"{k}_{v}" for k, v in params.items()])
        return slugify(f"{self.name}_{params_str}")[:64]


def luigi2dag(module: str, target: str, **kwargs) -> DAG:
    """Resolve Luigi task tree into a SciCD DAG."""
    target_task = load_luigi_task(module, target, **kwargs)

    # Topologically rank all tasks in the dependency tree
    all_tasks, task_ranks = _discover_and_rank_luigi(target_task)

    # Convert tasks to nodes based on concurrency strategy
    task_id_to_node = _group_tasks_into_nodes_luigi(all_tasks, task_ranks)

    # Establish edges between nodes based on task requirements
    unique_nodes = list({id(n): n for n in task_id_to_node.values()}.values())
    _build_dag_edges_luigi(unique_nodes, task_id_to_node)

    return DAG(nodes=unique_nodes)


def load_luigi_task(module: str, target: str, **kwargs) -> luigi.Task:
    """Programmatically instantiate a Luigi task with parameters."""
    cmdline_args = ["--module", module, target]

    for key, val in kwargs.items():
        formatted_key = key.replace("_", "-")
        cmdline_args.extend([f"--{formatted_key}", str(val)])

    importlib.import_module(module)

    with CmdlineParser.global_instance(cmdline_args) as cp:
        task = cp.get_task_obj()

    return task


def _discover_and_rank_luigi(
    target_task: luigi.Task,
) -> Tuple[dict[str, luigi.Task], dict[str, int]]:
    """Walk task tree to discover all instances and their topological ranks."""
    all_tasks: dict[str, luigi.Task] = {}

    def find_all(task: luigi.Task):
        if task.task_id not in all_tasks:
            all_tasks[task.task_id] = task
            for dep in luigi.task.flatten(task.requires()):
                find_all(dep)

    find_all(target_task)

    task_ranks: dict[str, int] = {}

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
    all_tasks: dict[str, luigi.Task], task_ranks: dict[str, int]
) -> dict[str, BaseNode]:
    """Group tasks into DAG nodes according to concurrency settings."""
    task_id_to_node: dict[str, BaseNode] = {}
    temp_slices: dict[Tuple[str, int], SliceNode] = {}

    for tid, task in all_tasks.items():
        rank = task_ranks[tid]
        adapter = LuigiAdapter(task)

        if adapter.cfg.concurrency.method == "slice":
            key = (adapter.name, rank)
            if key not in temp_slices:
                temp_slices[key] = SliceNode(work=[], rank=rank, node_deps=[])

            node = temp_slices[key]
            node.work.append(adapter)
            task_id_to_node[tid] = node
        else:
            node = BijectNode(work=[adapter], rank=rank, node_deps=[])
            task_id_to_node[tid] = node

    return task_id_to_node


def _build_dag_edges_luigi(
    unique_nodes: list[BaseNode], task_id_to_node: dict[str, BaseNode]
):
    """Establish dependencies between nodes based on underlying task requirements."""
    for node in unique_nodes:
        for adapter in node.work:
            for dep_task in luigi.task.flatten(adapter.work.requires()):
                parent_node = task_id_to_node.get(dep_task.task_id)

                if parent_node and parent_node is not node:
                    if parent_node not in node.node_deps:
                        node.node_deps.append(parent_node)
