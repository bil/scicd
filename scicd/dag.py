"""
Directed Acyclic Graph (DAG) abstractions for SciCD.

This module defines the internal representation of a pipeline as a graph of nodes,
where each node encapsulates one or more units of work (adapters).
"""

from __future__ import annotations
from dataclasses import dataclass
from abc import ABC, abstractmethod

import scicd.yamler
import scicd.adapter


@dataclass
class BaseNode(ABC):
    """
    Abstract base class for a node in the SciCD DAG.
    
    A node represents a logical step in the pipeline. It contains a list of
    adapters (the work to be done) and a set of dependency nodes.
    """
    work: list[scicd.adapter.BaseAdapter]
    rank: int
    node_deps: list[BaseNode]

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        dep_ids = [d.identifier for d in self.node_deps]
        return (
            f"<{cls_name} id='{self.identifier}' "
            f"rank={self.rank} work={len(self.work)} "
            f"needs={dep_ids}>"
        )

    @property
    def identifier(self) -> str:
        """A unique, deterministic string identifying this node."""
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
    def needs(self) -> list[str]:
        """Flattened list of unique identifier dependencies."""
        all_ids = [node.identifier for node in self.node_deps]
        return sorted(list(set(all_ids)))


@dataclass
class BijectNode(BaseNode):
    """
    A 1:1 mapping from a unit of work to a single CI/CD job.
    """

    def __post_init__(self):
        if not self.work or len(self.work) != 1:
            raise ValueError(f"BijectNode expects exactly 1 unit of work, received: {len(self.work)}")

    @property
    def dot_label(self) -> str:
        """Generate a label showing the task name and its parameters."""
        params = self.work[0].params.model_dump()
        param_str = ", ".join([f"{k}={v}" for k, v in params.items()])

        if param_str:
            return f"{self.work[0].name}\\n({param_str})"
        return self.work[0].name


@dataclass
class SliceNode(BaseNode):
    """
    Groups multiple units of work to be executed in a dynamic child pipeline.
    Used for scattering tasks across parallel workers.
    """

    @property
    def identifier(self) -> str:
        """Identifier for the trigger job that launches the child pipeline."""
        return f"{self.name}_rank{self.rank}_slice"

    @property
    def dot_label(self) -> str:
        """Generate a stacked label showing all tasks grouped in this slice."""
        label_lines = [self.name]
        for adapter in self.work:
            params = adapter.params.model_dump()
            param_str = ", ".join([f"{k}={v}" for k, v in params.items()])
            label_lines.append(f"[{param_str}]" if param_str else "[]")
        return "\\n".join(label_lines)


class DAG:
    """
    The complete pipeline representation.
    Provides methods for topological sorting and visualization.
    """

    def __init__(self, nodes: list[BaseNode]):
        self.nodes = nodes

    def export_dot(self, filepath: str):
        """
        Export the DAG to Graphviz DOT format for visualization.
        """
        dot_lines = [
            "digraph G {",
            "    rankdir=LR;",
            "    node [shape=box, style=rounded, fontname=Arial, fontsize=10];",
            "    edge [fontname=Arial, fontsize=9];",
            "",
        ]

        # Use a deterministic sort to ensure stable output
        sorted_nodes = sorted(self.nodes, key=lambda x: x.dot_label)
        node_to_id = {id(node): f"node_{i}" for i, node in enumerate(sorted_nodes)}

        ranks = {}
        for node in self.nodes:
            ranks.setdefault(node.rank, []).append(node)

        for _, nodes in sorted(ranks.items()):
            current_rank_nodes = sorted(nodes, key=lambda x: x.dot_label)
            identifiers = " ".join(
                [f'"{node_to_id[id(n)]}"' for n in current_rank_nodes]
            )
            dot_lines.append(f"    {{rank=same; {identifiers} }}")

            for node in current_rank_nodes:
                color = "lightblue" if isinstance(node, SliceNode) else "lightgrey"
                label = node.dot_label.replace('"', '\\"')
                stable_id = node_to_id[id(node)]
                dot_lines.append(
                    f'    "{stable_id}" [label="{label}", fillcolor={color}, style=filled];'
                )

        for node in self.nodes:
            child_id = node_to_id[id(node)]
            for parent in node.node_deps:
                parent_id = node_to_id[id(parent)]
                dot_lines.append(f'    "{parent_id}" -> "{child_id}";')

        dot_lines.append("}")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(dot_lines))
