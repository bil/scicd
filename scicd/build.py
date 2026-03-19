from __future__ import annotations
from typing import Dict, List, Tuple
import importlib

import luigi
from luigi.cmdline_parser import CmdlineParser

from scicd.config import SciCDConfig
from scicd.dag import DAG, BaseNode, SliceNode, BijectNode


def luigi2dag(target_task: luigi.Task) -> DAG:
    """
    Orchestrates the conversion of a Luigi task tree into a SciCD DAG.
    """
    # Discover tasks and compute rank (0 is a leaf, N is the target)
    all_tasks, task_ranks = _discover_and_rank(target_task)

    # Group into Node objects (Slice vs Biject)
    # Returns a map of {luigi_task_id: NodeInstance}
    task_id_to_node = _group_tasks_into_nodes(all_tasks, task_ranks)

    # Connect the Node objects using the instances themselves
    # unique_nodes avoids re-processing nodes that contain multiple tasks (Slices)
    unique_nodes = list({id(n): n for n in task_id_to_node.values()}.values())
    _build_dag_edges(unique_nodes, task_id_to_node)

    # Wrap in a DAG container
    return DAG(nodes=unique_nodes)


def _discover_and_rank(
    target_task: luigi.Task,
) -> Tuple[Dict[str, luigi.Task], Dict[str, int]]:
    """
    Walks the task tree. Returns:
    - all_tasks: dict[task_id, task_instance]
    - task_ranks: dict[task_id, int] (topological depth)
    """
    all_tasks: Dict[str, luigi.Task] = {}

    # Pass 1: Recursive discovery of all tasks in the tree
    def find_all(task: luigi.Task):
        if task.task_id not in all_tasks:
            all_tasks[task.task_id] = task
            for dep in luigi.task.flatten(task.requires()):
                find_all(dep)

    find_all(target_task)

    # Pass 2: Calculate Rank (Topological Depth)
    task_ranks: Dict[str, int] = {}

    def get_rank(task: luigi.Task) -> int:
        if task.task_id in task_ranks:
            return task_ranks[task.task_id]

        deps = luigi.task.flatten(task.requires())
        if not deps:
            # Base case: No dependencies means Stage 0
            rank = 0
        else:
            # Recursive case: 1 + max rank of all dependencies
            rank = max(get_rank(d) for d in deps) + 1

        task_ranks[task.task_id] = rank
        return rank

    # Trigger the ranking for every discovered task
    for task_instance in all_tasks.values():
        get_rank(task_instance)

    return all_tasks, task_ranks


def _group_tasks_into_nodes(
    all_tasks: Dict[str, luigi.Task], task_ranks: Dict[str, int]
) -> Dict[str, BaseNode]:
    """
    Applies SciCDConfig strategies to group tasks into executable Nodes.
    """
    task_id_to_node: Dict[str, BaseNode] = {}
    temp_slices: Dict[Tuple[str, int], SliceNode] = {}

    for tid, task in all_tasks.items():
        rank = task_ranks[tid]
        family = task.task_family
        cfg = SciCDConfig().family_config(family)

        if cfg.concurrency_method == "slice":
            # Group by family AND rank so tasks from the same family
            # in different stages don't get mashed together
            key = (family, rank)
            if key not in temp_slices:
                temp_slices[key] = SliceNode(
                    family=family, tasks=[], rank=rank, task_deps=[]
                )

            node = temp_slices[key]
            node.tasks.append(task)
            task_id_to_node[tid] = node
        else:
            # Biject: 1 Node per 1 Task instance
            node = BijectNode(family=family, tasks=[task], rank=rank, task_deps=[])
            task_id_to_node[tid] = node

    return task_id_to_node


def _build_dag_edges(
    unique_nodes: List[BaseNode], task_id_to_node: Dict[str, BaseNode]
):
    """
    Translates task-to-task requirements into node-to-node object references.
    """
    for node in unique_nodes:
        # Check every task inside this node
        for task in node.tasks:
            # Look at what those tasks require
            for dep_task in luigi.task.flatten(task.requires()):
                parent_node = task_id_to_node.get(dep_task.task_id)

                # Ensure the parent is a different node (prevents self-needs in GitLab)
                if parent_node and parent_node is not node:
                    if parent_node not in node.task_deps:
                        node.task_deps.append(parent_node)


def build_gitlab(
    module: str, family: str, yml_filepath: str = ".gitlab-ci.yml", **kwargs
):
    """
    Build a Luigi workflow into CI/CD
    """
    task_kwargs = {}
    scicd_kwargs = {}

    for key, val in kwargs.items():
        if key.startswith("scicd"):
            scicd_kwargs[key] = val
        else:
            task_kwargs[key] = str(val)

    SciCDConfig().override(**scicd_kwargs) # overrides singleton
    dag = build_dag(module, family, **task_kwargs)

    # this accesses overrided singleton
    workspace_config = SciCDConfig().workspace_config()
    dag.write_gitlab_yaml(
        filepath=yml_filepath,
        default=workspace_config.gitlab_default,
        workflow=workspace_config.gitlab_workflow,
    )

    print(f"✨ SciCD: DAG generated for {family} with {len(kwargs)} overrides.")


def build_dag(module: str, family: str, **kwargs):
    """
    Build a Luigi task into its DAG
    """

    task = load_task(module, family, **kwargs)

    # Now that we have the 'target' task fully loaded with CLI params:
    dag = luigi2dag(task)
    return dag


def export_dag(module: str, family: str, filepath: str = "dag.dot", **kwargs):
    """
    Build a DAG that targets a Luigi task, and generate graphviz dot file.
    """
    dag = build_dag(module, family, **kwargs)
    dag.export_dot(filepath)


def load_task(module: str, family: str, **kwargs):
    """
    Programmatically loads a task, injecting parameters from luigi.toml.
    """
    cmdline_args = ["--module", module, family]

    for key, val in kwargs.items():
        # Luigi parser expects dashes
        formatted_key = key.replace("_", "-")
        cmdline_args.extend([f"--{formatted_key}", str(val)])

    # Ensure the module is imported so Luigi knows the Task exists
    importlib.import_module(module)

    # This sets CmdlineParser._instance so Task constructors can find it.
    with CmdlineParser.global_instance(cmdline_args) as cp:
        task = cp.get_task_obj()

    return task
