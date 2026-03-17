from __future__ import annotations  # Put this at the very top of your file
from copy import deepcopy
import json
import re
from typing import List
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod
from functools import cached_property

import yaml
import luigi

from scicd.config import SciCDConfig
import scicd.yamler


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
    task_deps: list[BaseNode]

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        # Just show the IDs of dependencies to avoid infinite recursion
        dep_ids = [d.node_id for d in self.task_deps]
        return (
            f"<{cls_name} id='{self.node_id}' "
            f"rank={self.rank} tasks={len(self.tasks)} "
            f"needs={dep_ids}>"
        )

    @property
    @abstractmethod
    def node_id(self) -> str:
        """Unique identifier for the GitLab Job."""

    @abstractmethod
    def get_dot_label(self) -> str:
        """Return the Graphviz label string for the node."""

    @abstractmethod
    def to_gitlab(self) -> List[dict]:
        """generate job dict(s)"""

    @cached_property
    def cfg(self):
        """Standardized config lookup for all nodes."""
        return SciCDConfig().family_config(self.family)

    @cached_property
    def workspace_cfg(self):
        return SciCDConfig().workspace_config()

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

        info = scicd.yamler.deep_update(info, dict(self.cfg.gitlab_extras))
        return info


@dataclass
class SliceNode(BaseNode):
    @property
    def node_id(self) -> str:
        return f"{self.family}_rank{self.rank}_trigger"

    def get_dot_label(self) -> str:
        # Slice: Family
        # [param1=val1]
        # [param1=val2]
        label_lines = [self.family]
        for task in self.tasks:
            params = task.to_str_params(only_significant=True)
            param_str = ", ".join([f"{k}={v}" for k, v in params.items()])
            label_lines.append(f"[{param_str}]" if param_str else "[]")
        return "\\n".join(label_lines)

    def to_gitlab(self) -> List[dict]:
        # Extract parameters from all tasks
        all_task_params = [
            task.to_str_params(only_significant=True) for task in self.tasks
        ]
        params_json = json.dumps(all_task_params)

        # Serialize Resolved Configuration (The Source of Truth)
        cfg_json = json.dumps(asdict(self.cfg))

        # Serialize GitLab boilerplate
        gitlab_info_json = json.dumps(self.gitlab_info())

        gen_id = f"{self.family}_rank{self.rank}_gen"

        # Generator
        gen_job = self.gitlab_info()
        gen_job["stage"] = f"stage_{self.rank}"
        gen_job["script"] = [
            f"{self.cfg.python_executable} -m scicd.slice generate "
            f"--module {self.tasks[0].__module__} "
            f"--family {self.family} "
            f"--all-params-json '{params_json}' "
            f"--cfg-json '{cfg_json}' "
            f"--gitlab-info-json '{gitlab_info_json}' "
            f"--gen-id '{gen_id}'"
        ]
        gen_job["artifacts"] = {"paths": ["manifest.yml", "child_pipeline.yml"]}
        if self.needs:
            gen_job["needs"] = self.needs

        # Trigger
        # These can have limited keys
        trigger_job = {
            "stage": f"stage_{self.rank}",
            "variables": {"PARENT_PIPELINE_ID": "$CI_PIPELINE_ID"},
            "trigger": {
                "include": [
                    {"artifact": "child_pipeline.yml", "job": gen_id},
                ],
                "strategy": "depend",
                "forward": {
                    "pipeline_variables": True,
                    "yaml_variables": True,
                },
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

    def get_dot_label(self) -> str:
        # Biject: Family (param1=val1, param2=val2)
        task = self.tasks[0]
        params = task.to_str_params(only_significant=True)
        param_str = ", ".join([f"{k}={v}" for k, v in params.items()])
        return f"{self.family}\\n({param_str})" if param_str else self.family

    def get_command(self) -> str:
        task = self.tasks[0]
        module = task.__module__
        family = task.task_family

        params_json = json.dumps(task.to_str_params(only_significant=True))

        return (
            f"{self.cfg.python_executable} -m scicd.biject run "
            f"--module {module} "
            f"--family {family} "
            f"--params-json '{params_json}'"
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

    def render_gitlab(self, **boilerplate) -> dict:
        cfg = SciCDConfig()
        paths = cfg.paths_config()
        pull_cmd = cfg.get_sync_command(direction="pull")
        push_cmd = cfg.get_sync_command(direction="push")

        pipeline = deepcopy(boilerplate)
        all_jobs = {}

        # Functional Jobs: pure execution
        for node in self.nodes:
            for job_dict in node.to_gitlab():
                for name, body in job_dict.items():
                    # Add needs for pull
                    existing_needs = body.get("needs", [])
                    if pull_cmd:
                        body["needs"] = ["scicd_pull_init"] + existing_needs
                    all_jobs[name] = body

        # Identify functional stages
        unique_stages = sorted(
            {body["stage"] for body in all_jobs.values() if "stage" in body},
            key=lambda x: int(x.split("_")[1]) if "_" in x else 0,
        )

        # Pull
        if pull_cmd:
            all_jobs["scicd_pull_init"] = {
                "stage": "stage_00_pull",
                "image": cfg.family_config(None).image,
                "script": [f"mkdir -p {paths.output}", pull_cmd],
            }

        # Push: Checkpoint after each stage
        if push_cmd:
            for stage_name in unique_stages:
                if stage_name == "stage_00_pull":
                    continue

                # Wait for functional jobs in this stage
                deps = [
                    name
                    for name, body in all_jobs.items()
                    if body.get("stage") == stage_name and "scicd" not in name
                ]

                all_jobs[f"checkpoint_{stage_name}"] = {
                    "stage": stage_name,
                    "image": cfg.family_config(None).image,
                    "needs": deps,
                    "script": [push_cmd],
                    "when": "always",  # checkpoint failures too
                }

        pipeline["stages"] = ["stage_00_pull"] + unique_stages
        pipeline.update(all_jobs)
        return pipeline

    def write_gitlab_yaml(self, filepath: str = ".gitlab-ci.yml", **boilerplate):
        """Writes the rendered dict to a file."""
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(
                self.render_gitlab(**boilerplate),
                f,
                sort_keys=False,
                default_flow_style=False,
            )

    def export_dot(self, filepath: str):
        dot_lines = [
            "digraph G {",
            "    rankdir=LR;",
            "    node [shape=box, style=rounded, fontname=Arial, fontsize=10];",
            "    edge [fontname=Arial, fontsize=9];",
            "",
        ]

        # Group nodes by rank to ensure they stay in vertical columns
        ranks = {}
        for node in self.nodes:
            ranks.setdefault(node.rank, []).append(node)

        for _, nodes in sorted(ranks.items()):
            # Optional: Force nodes of the same rank into the same vertical column
            dot_lines.append(
                "{rank=same; " + " ".join([f'"{id(n)}"' for n in nodes]) + " }"
            )

            for node in nodes:
                # Color logic: Slice is lightblue, Biject is lightgrey
                color = "lightblue" if isinstance(node, SliceNode) else "lightgrey"
                label = node.get_dot_label()
                dot_lines.append(
                    f'    "{id(node)}" [label="{label}", fillcolor={color}, style=filled];'
                )

        # Simple node-to-node edges
        for node in self.nodes:
            for parent in node.task_deps:
                dot_lines.append(f'    "{id(parent)}" -> "{id(node)}";')

        dot_lines.append("}")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(dot_lines))
