# """
# DAG orchestration and visualization engine.
# Handles module discovery, topological sorting, and dependency mapping.
# """

# import pathlib

# from scicd import paths


# def list_modules():
#     """
#     Scans the configured module directory for YAML configuration files.

#     Returns:
#         list: Names of all discovered modules (without extensions).
#     """
#     module_dir = pathlib.Path(paths.module_dir())
#     files = list(module_dir.glob("*.yml.j2")) + list(module_dir.glob("*.yaml.j2"))
#     return [f.name.split(".")[0] for f in files]


# def get_dag():
#     """
#     Builds the module dependency graph.

#     Returns:
#         dict: Mapping of module name to its list of required dependencies.
#     """
#     dag_graph = {}
#     for module_name in list_modules():
#         mod_cfg = paths.module_cfg(module_name)
#         dag_graph[module_name] = mod_cfg.get("needs", [])
#     return dag_graph


# def get_topological_ranks():
#     """
#     Groups modules into execution ranks based on their dependencies.

#     Returns:
#         list: List of ranks, where each rank is a list of modules that can run in parallel.

#     Raises:
#         ValueError: If a circular dependency is detected.
#     """
#     dag_graph = get_dag()
#     modules = list(dag_graph.keys())
#     in_degree = {m: len(dag_graph[m]) for m in modules}
#     dependents = {m: [] for m in modules}
#     for m, needs in dag_graph.items():
#         for n in needs:
#             if n in dependents:
#                 dependents[n].append(m)

#     queue = [m for m in modules if in_degree[m] == 0]
#     ranks = []

#     while queue:
#         queue.sort()
#         ranks.append(queue[:])
#         next_queue = []
#         for m in queue:
#             for dep in dependents[m]:
#                 in_degree[dep] -= 1
#                 if in_degree[dep] == 0:
#                     next_queue.append(dep)
#         queue = next_queue

#     if sum(len(r) for r in ranks) != len(modules):
#         unprocessed = [m for m, d in in_degree.items() if d > 0]
#         raise ValueError(f"Circular dependency detected: {unprocessed}")

#     return ranks


# def get_subgraph(module_names, dag_graph=None):
#     """
#     Resolves the union of all descendants for a given set of modules.

#     Args:
#         module_names (list|str): One or more starting module names.
#         dag_graph (dict): Optional pre-built DAG.

#     Returns:
#         list: Names of all modules in the resulting subgraph.
#     """
#     if isinstance(module_names, str):
#         module_names = [module_names]

#     if dag_graph is None:
#         dag_graph = get_dag()

#     dependents = {m: [] for m in dag_graph}
#     for m, needs in dag_graph.items():
#         for n in needs:
#             if n in dependents:
#                 dependents[n].append(m)

#     subgraph, stack = set(), list(module_names)
#     while stack:
#         node = stack.pop()
#         if node not in subgraph:
#             subgraph.add(node)
#             if node in dependents:
#                 stack.extend(dependents[node])
#     return list(subgraph)


# def get_category_map():
#     """
#     Groups modules by their semantic 'category' tag defined in YAML body.

#     Returns:
#         dict: Mapping of category name to list of associated modules.
#     """
#     cat_map = {}
#     for module_name in list_modules():
#         mod_cfg = paths.module_cfg(module_name)
#         category = mod_cfg.get("category", "default")
#         if category not in cat_map:
#             cat_map[category] = []
#         cat_map[category].append(module_name)
#     return cat_map


# def export_dag(output_path="assets/dag.dot"):
#     """
#     Generates a Graphviz DOT file representing the module dependencies.

#     Args:
#         output_path (str): Target path for the DOT file.
#     """
#     pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
#     dag_graph = get_dag()

#     lines = [
#         "digraph G {",
#         "  rankdir=LR;",
#         '  node [shape=box, style=filled, fillcolor=lightblue, fontname="Arial"];',
#         "",
#     ]
#     for m, needs in dag_graph.items():
#         if not needs:
#             lines.append(f'  "{m}" [fillcolor=lightgrey];')
#         else:
#             for dep in needs:
#                 lines.append(f'  "{dep}" -> "{m}";')
#     lines.append("}")

#     with open(output_path, "w", encoding="utf-8") as f:
#         f.write("\n".join(lines))
#     print(f"Exported: {output_path}")


import luigi
import json
import re
from copy import deepcopy
from typing import List
from dataclasses import dataclass
import yaml
from scicd.config import SciCDConfig
from abc import ABC, abstractmethod
from functools import cached_property
import scicd.config


def _slugify(text: str) -> str:
    # Replace anything that isn't a letter, number, or underscore with '_'
    # This handles periods, dashes, spaces, and weird symbols in one pass.
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", text)
    # Collapse multiple underscores (e.g., 'a...b' -> 'a___b' -> 'a_b')
    return re.sub(r"_+", "_", clean).strip("_")


@dataclass
class BaseNode(ABC):
    family: str
    tasks: List[luigi.Task]
    rank: int
    task_deps: list[scicd.dag.BaseNode]

    @property
    @abstractmethod
    def node_id(self) -> str:
        """Unique identifier for the GitLab Job."""

    @abstractmethod
    def to_gitlab(self) -> List[dict]:
        """generate job dict(s)"""

    @cached_property
    def cfg(self):
        """Standardized config lookup for all nodes."""
        return deepcopy(SciCDConfig(family=self.family))

    @property
    def needs(self) -> List[str]:
        """
        Flattened list of all node_id dependencies.
        """
        # We take all values from the task_deps dict and flatten them
        all_ids = [node.node_id for node in self.task_deps]
        return sorted(list(set(all_ids)))

    def gitlab_info(self) -> dict:

        info = {
            "image": str(self.cfg.image),
            "variables": dict(self.cfg.variables),
        }
        for key in self.cfg.memory_request_vars:
            info["variables"][key] = str(self.cfg.memory)
        for key in self.cfg.cpu_request_vars:
            info["variables"][key] = str(self.cfg.cpu)

        if self.cfg.tags:
            info["tags"] = list(self.cfg.tags)

        if self.cfg.retries > 0:
            info["retry"] = int(self.cfg.retries)

        info = scicd.config.deep_update(info, dict(self.cfg.gitlab_extras))
        return info


@dataclass
class SliceNode(BaseNode):
    @property
    def node_id(self) -> str:
        return f"{self.family}_rank{self.rank}_trigger"

    def to_gitlab(self) -> List[dict]:
        # Extract parameters from all tasks
        all_task_params = [
            task.to_str_params(only_significant=True) for task in self.tasks
        ]
        params_json = json.dumps(all_task_params)

        gen_id = f"{self.family}_rank{self.rank}_gen"

        # Generator
        gen_job = self.gitlab_info()
        gen_job["stage"] = f"stage_{self.rank}"
        gen_job["script"] = [
            f"python -m scicd.slice generate "
            f"--module {self.tasks[0].__module__} "
            f"--family {self.family} "
            f"--all_params_json '{params_json}' "
            f"--num_workers {self.cfg.parallel_count} "
            f"--image {self.cfg.image}"
        ]
        gen_job["artifacts"] = {"paths": ["manifest.yml", "child_pipeline.yml"]}
        if self.needs:
            gen_job["needs"] = self.needs

        # --- JOB 2: The Trigger ---
        trigger_job = {
            "stage": f"stage_{self.rank}",
            "trigger": {
                "include": [{"artifact": "child_pipeline.yml", "job": gen_id}],
                "strategy": "depend",
            },
            "needs": [gen_id],
        }

        return [{gen_id: gen_job}, {self.node_id: trigger_job}]


@dataclass
class BijectNode(BaseNode):
    @property
    def node_id(self) -> str:
        task = self.tasks[0]
        params = task.to_str_params(only_significant=True)
        params_str = "_".join([f"{k}_{v}" for k, v in params.items()])
        return _slugify(f"{self.family}_{params_str}")[:64]

    def get_command(self) -> str:
        task = self.tasks[0]
        # Example: 'my_lab.analysis.ProcessData'
        module = task.__module__
        family = task.family

        params_json = json.dumps(task.to_str_params(only_significant=True))

        return (
            f"python -m scicd.biject run "
            f"--module {module} "
            f"--family {family} "
            f"--params_json '{params_json}'"
        )

    def to_gitlab(self) -> List[dict]:
        # I changed return type to dict because 1 node = 1 job usually
        job = self.gitlab_info()
        job["stage"] = f"stage_{self.rank}"
        job["script"] = [self.get_command()]

        if self.needs:
            job["needs"] = self.needs

        return [{self.node_id: job}]


class DAG:
    def __init__(self, nodes: List[BaseNode]):
        self.nodes = nodes

    def render(self) -> dict:
        """
        Gathers all jobs from all nodes and builds the final GitLab CI dict.
        """
        # 1. Collect all stages
        # We extract the stage string from the job bodies
        all_job_definitions = []
        for node in self.nodes:
            all_job_definitions.extend(node.to_gitlab())

        unique_stages = set()
        for job_dict in all_job_definitions:
            for job_body in job_dict.values():
                unique_stages.add(job_body["stage"])

        # Sort stages by rank (e.g., stage_0, stage_1, stage_10)
        # We sort by the integer suffix to avoid 'stage_10' coming before 'stage_2'
        sorted_stages = sorted(list(unique_stages), key=lambda x: int(x.split("_")[1]))

        # 2. Build the final manifest
        pipeline = {"stages": sorted_stages}
        for job_dict in all_job_definitions:
            pipeline.update(job_dict)

        return pipeline

    def write_yaml(self, filepath: str = ".gitlab-ci.yml"):
        """Writes the rendered dict to a file."""
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(self.render(), f, sort_keys=False, default_flow_style=False)
