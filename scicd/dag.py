"""
Module docstring.
"""
from __future__ import annotations  # Put this at the very top of your file
from copy import deepcopy
import json
import re
from typing import List, Dict, Any
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod
from functools import cached_property

import yaml
import luigi

import scicd.yamler
import scicd.gitlab
import scicd.adapter


@dataclass
class BaseNode(ABC):
    work: List[scicd.adapter.BaseAdapter]
    rank: int
    node_deps: list[BaseNode]

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        # Just show the IDs of dependencies to avoid infinite recursion
        dep_ids = [d.identifier for d in self.node_deps]
        return (
            f"<{cls_name} id='{self.identifier}' "
            f"rank={self.rank} work={len(self.work)} "
            f"needs={dep_ids}>"
        )

    @property
    def identifier(self) -> str:
        return self.work[0].identifier if self.work else "unknown"

    @property
    def name(self) -> str:
        """The logical name of the task family represented by this node."""
        return self.work[0].name if self.work else "unknown"

    @property
    @abstractmethod
    def dot_label(self) -> str:
        """Return the Graphviz label string for the node."""

    @property
    def needs(self) -> List[str]:
        """
        Flattened list of all identifier dependencies.
        """
        # We take all values from the node_deps dict and flatten them
        all_ids = [node.identifier for node in self.node_deps]
        return sorted(list(set(all_ids)))

    @abstractmethod
    def to_gitlab(self) -> List[Dict[str, Any]]:
        """
        Render computation into Gitlab CI/CD jobs
        """


@dataclass
class BijectNode(BaseNode):
    """
    A 1:1 mapping from a unit of work to a CI/CD job
    """

    def __post_init__(self):
        if not self.work or len(self.work) != 1:
            raise ValueError(f"BijectNode expecs 1 unit of work, received: {self.work}")

    @property
    def dot_label(self) -> str:
        # Biject: Family (param1=val1, param2=val2)
        params = self.work[0].params
        param_str = ", ".join([f"{k}={v}" for k, v in params.items()])

        if param_str:
            return f"{self.work[0].name}\\n({param_str})"
        else:
            return self.work[0].name

    def to_gitlab(self) -> List[dict]:
        # I changed return type to dict because 1 node = 1 job usually
        job = scicd.gitlab.gitlab_info(self.work[0].cfg)
        job["stage"] = f"stage_{self.rank}"
        job["script"] = [" ".join(self.work[0].command)]

        if self.needs:
            job["needs"] = self.needs

        return [{self.identifier: job}]


@dataclass
class SliceNode(BaseNode):
    """
    Groups multiple units of work to be executed in a dynamic child pipeline.
    """

    @property
    def identifier(self) -> str:
        return f"{self.name}_rank{self.rank}_slice"

    @property
    def dot_label(self) -> str:
        # Slice: Family
        # [param1=val1]
        # [param2=val2]
        label_lines = [self.name]
        for adapter in self.work:
            params = adapter.params
            param_str = ", ".join([f"{k}={v}" for k, v in params.items()])
            label_lines.append(f"[{param_str}]" if param_str else "[]")
        return "\\n".join(label_lines)

    def to_gitlab(self) -> List[Dict[str, Any]]:
        # Extract commands from all work units
        all_commands = [adapter.command for adapter in self.work]
        commands_json = json.dumps(all_commands)

        # Use the configuration from the first work unit as the basis
        cfg = self.work[0].cfg
        cfg_json = json.dumps(asdict(cfg))

        # Serialize platform-specific boilerplate
        gitlab_info = scicd.gitlab.gitlab_info(cfg)
        gitlab_info_json = json.dumps(gitlab_info)

        gen_id = f"{self.name}_rank{self.rank}_gen"

        # Generator Job: Dynamically creates the child pipeline YAML
        gen_job = deepcopy(gitlab_info)
        gen_job["stage"] = f"stage_{self.rank}"

        gen_job["script"] = [
            f"python3 -m scicd.slice generate "
            f"--family {self.name} "
            f"--commands-json '{commands_json}' "
            f"--cfg-json '{cfg_json}' "
            f"--gitlab-info-json '{gitlab_info_json}' "
            f"--gen-id '{gen_id}'"
        ]
        gen_job["artifacts"] = {"paths": ["manifest.yml", "child_pipeline.yml"]}

        if self.needs:
            gen_job["needs"] = self.needs

        # Trigger Job: Launches the child pipeline generated above
        trigger_job = {
            "stage": f"stage_{self.rank}",
            "variables": {"PARENT_PIPELINE_ID": "$CI_PIPELINE_ID"},
            "trigger": {
                "include": [{"artifact": "child_pipeline.yml", "job": gen_id}],
                "strategy": "depend",
                "forward": {
                    "pipeline_variables": True,
                    "yaml_variables": True,
                },
            },
            "needs": [gen_id],
        }

        return [{gen_id: gen_job}, {self.identifier: trigger_job}]


class DAG:

    def __init__(self, nodes: List[BaseNode]):
        self.nodes = nodes

    def render_gitlab(self, **boilerplate) -> dict:
        "Generate .gitlab-ci.yml file"
        pipeline = deepcopy(boilerplate)
        all_jobs = {}

        # Actual work
        for node in self.nodes:
            for job_dict in node.to_gitlab():
                all_jobs.update(job_dict)

        # Identify functional stages
        unique_stages = sorted(
            {body["stage"] for body in all_jobs.values() if "stage" in body},
            key=lambda x: int(x.split("_")[1]) if "_" in x else 0,
        )

        pipeline["stages"] = unique_stages
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
        """Generate .dot file of DAG"""
        dot_lines = [
            "digraph G {",
            "    rankdir=LR;",
            "    node [shape=box, style=rounded, fontname=Arial, fontsize=10];",
            "    edge [fontname=Arial, fontsize=9];",
            "",
        ]

        # Use a deterministic sort to ensure node_0 is always the same node across runs
        # We sort by the dot label string to ensure stable ordering in Git
        sorted_nodes = sorted(self.nodes, key=lambda x: x.dot_label)

        # Use the Python object's memory ID for the dictionary ONLY during this
        # specific loop to map objects to stable strings like "node_0"
        node_to_id = {id(node): f"node_{i}" for i, node in enumerate(sorted_nodes)}

        ranks = {}
        for node in self.nodes:
            ranks.setdefault(node.rank, []).append(node)

        for _, nodes in sorted(ranks.items()):
            # Sort within rank for deterministic {rank=same} blocks
            current_rank_nodes = sorted(nodes, key=lambda x: x.dot_label)

            identifiers = " ".join(
                [f'"{node_to_id[id(n)]}"' for n in current_rank_nodes]
            )
            dot_lines.append(f"    {{rank=same; {identifiers} }}")

            for node in current_rank_nodes:
                color = "lightblue" if isinstance(node, SliceNode) else "lightgrey"

                # Clean up the label to prevent DOT syntax errors
                label = node.dot_label.replace('"', '\\"')

                # Use the stable node_i name
                stable_id = node_to_id[id(node)]
                dot_lines.append(
                    f'    "{stable_id}" [label="{label}", fillcolor={color}, style=filled];'
                )

        # Edges using stable IDs
        for node in self.nodes:
            child_id = node_to_id[id(node)]
            for parent in node.node_deps:
                parent_id = node_to_id[id(parent)]
                dot_lines.append(f'    "{parent_id}" -> "{child_id}";')

        dot_lines.append("}")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(dot_lines))
