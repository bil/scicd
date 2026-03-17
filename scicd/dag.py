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
            "trigger": {
                "include": [
                    # Only include the file that contains "stages:", "jobs:", etc.
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

    def get_command(self) -> str:
        task = self.tasks[0]
        # Example: 'my_lab.analysis.ProcessData'
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
        """
        Gathers all jobs from all nodes and builds the final GitLab CI dict.
        """

        pipeline = deepcopy(boilerplate)
        # Collect all stages
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

        # Build the final manifest
        pipeline["stages"] = sorted_stages
        for job_dict in all_job_definitions:
            pipeline.update(job_dict)

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
