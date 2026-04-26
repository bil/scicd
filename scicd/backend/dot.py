"""
Conversion tools from DAG to DOT.
"""

from typing import TYPE_CHECKING
from scicd.node import Node

if TYPE_CHECKING:
    from scicd.dag import DAG


def export_dag(dag: "DAG", file_path: str = "dag.dot"):
    """
    Export DAG to Graphviz DOT format for visualization.
    """
    dot_lines = [
        "digraph G {",
        "    rankdir=LR;",
        "    node [shape=box, style=rounded, fontname=Arial, fontsize=10];",
        "    edge [fontname=Arial, fontsize=9];",
        "",
    ]

    # Use a deterministic sort to ensure stable output
    sorted_nodes = sorted(dag.nodes, key=lambda x: x.dot_label)
    node_to_id = {id(node): f"node_{i}" for i, node in enumerate(sorted_nodes)}

    ranks: dict[int, list[Node]] = {}
    for node in dag.nodes:
        ranks.setdefault(node.rank, []).append(node)

    for _, nodes in sorted(ranks.items()):
        current_rank_nodes = sorted(nodes, key=lambda x: x.dot_label)
        identifiers = " ".join(
            [f'"{node_to_id[id(n)]}"' for n in current_rank_nodes]
        )
        dot_lines.append(f"    {{rank=same; {identifiers} }}")

        for node in current_rank_nodes:
            color = "lightblue" if node.cfg.concurrency.method == "slice" else "lightgrey"
            label = node.dot_label.replace('"', '\\"')
            stable_id = node_to_id[id(node)]
            dot_lines.append(
                f'    "{stable_id}" [label="{label}", fillcolor={color}, style=filled];'
            )

    for node in dag.nodes:
        child_id = node_to_id[id(node)]
        for parent in node.deps:
            parent_id = node_to_id[id(parent)]
            dot_lines.append(f'    "{parent_id}" -> "{child_id}";')

    dot_lines.append("}")
    out = "\n".join(dot_lines)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(out)
    return out
