"""
Directed Acyclic Graph (DAG) abstractions for SciCD.

This module defines the internal representation of a pipeline as a graph of nodes,
where each node encapsulates one or more units of work (adapters).
"""

from typing import Optional

import scicd.backend.gitlab
import scicd.backend.dot
from scicd.node import Node
from scicd.adapter import BaseAdapter


class DAG:
    """
    The complete pipeline representation.
    Provides methods for topological sorting and visualization.
    """

    def __init__(self, nodes: list[Node], config_path: Optional[str] = None):
        self.nodes = nodes
        self.config_path = config_path

    def export(
        self,
        backend: str = "gitlab",
        file_path: Optional[str] = None,
    ):
        if backend == "gitlab":
            if file_path is None:
                file_path = ".gitlab-ci.yml"
            scicd.backend.gitlab.export_dag(self, file_path)
        elif backend == "dot":
            if file_path is None:
                file_path = "dag.dot"
            scicd.backend.dot.export_dag(self, file_path)
        else:
            raise NotImplementedError(f"DAG export not implemented for {backend}")


def _get_rank_dicts(
    target_adapter: BaseAdapter,
) -> tuple[dict[str, BaseAdapter], dict[int, list[str]]]:
    """Topological sorting"""

    id_to_adapter: dict[str, BaseAdapter] = {}
    id_to_rank: dict[str, int] = {}
    rank_to_ids: dict[int, list[str]] = {}

    def _populate(adapter: BaseAdapter) -> int:
        if adapter.identifier in id_to_rank:
            return id_to_rank[adapter.identifier]

        deps = adapter.deps
        if not deps:
            rank = 0
        else:
            rank = max(_populate(d) for d in deps) + 1

        id_to_rank[adapter.identifier] = rank
        id_to_adapter[adapter.identifier] = adapter
        rank_to_ids.setdefault(rank, []).append(adapter.identifier)
        return rank

    _populate(target_adapter)

    return id_to_adapter, rank_to_ids


def _group_into_nodes(
    id_to_adapter: dict[str, BaseAdapter],
    rank_to_ids: dict[int, list[str]],
) -> list[Node]:
    """Group tasks into DAG nodes according to concurrency settings."""

    nodes: list[Node] = []
    id_to_node: dict[str, Node] = {}

    # In increasing rank so dependencies have already been made into a node
    for rank, ids in sorted(rank_to_ids.items()):
        # Process each adapter
        for identity in ids:
            # Already processed!
            if identity in id_to_node:
                continue

            adapter = id_to_adapter[identity]
            cfg = adapter.cfg

            # Biject maps an adapter directly to a node
            if cfg.concurrency.method == "biject":
                deps = {id_to_node[adpt.identifier] for adpt in adapter.deps}
                node = Node(
                    adapters=[adapter],
                    rank=rank,
                    deps=list(deps),
                )
                nodes.append(node)
                id_to_node[identity] = node

            # Here, we collect nodes of same name with same dependency string
            elif cfg.concurrency.method == "slice":
                merge_ids = [
                    i
                    for i in rank_to_ids[rank]
                    if (id_to_adapter[i].name == adapter.name)
                    and (id_to_adapter[i].deps_str == adapter.deps_str)
                ]
                adapters = [id_to_adapter[i] for i in merge_ids]

                # Use node identifier as key to ensure it only appears once as value
                deps = {
                    id_to_node[dep.identifier] for adpt in adapters for dep in adpt.deps
                }
                node = Node(adapters=adapters, rank=rank, deps=list(deps))
                nodes.append(node)
                for adpt in adapters:
                    id_to_node[adpt.identifier] = node
    #             else:
    #                 raise NotImplementedError
    # Ensure we have processed all adapters
    assert set(id_to_node) == set(id_to_adapter)

    return nodes


def build(adapter: BaseAdapter) -> DAG:
    """
    Convert adapters into nodes (based on configuration) and return DAG.

    Args:
        adapters: A list of adapters to process in computation.
    """
    config_path = adapter.config_path
    id_to_adapter, rank_to_ids = _get_rank_dicts(adapter)
    nodes = _group_into_nodes(id_to_adapter, rank_to_ids)
    return DAG(nodes, config_path)
