"""
Module docstring.
"""

from __future__ import annotations  # Put this at the very top of your file
from typing import List
from dataclasses import dataclass
from abc import ABC, abstractmethod

import scicd.yamler
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


class DAG:

    def __init__(self, nodes: List[BaseNode]):
        self.nodes = nodes

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
