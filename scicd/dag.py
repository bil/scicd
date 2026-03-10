"""
DAG orchestration and visualization engine.
Handles module discovery, topological sorting, and dependency mapping.
"""

import pathlib

from scicd import paths


def list_modules():
    """
    Scans the configured module directory for YAML configuration files.

    Returns:
        list: Names of all discovered modules (without extensions).
    """
    module_dir = pathlib.Path(paths.module_dir())
    files = list(module_dir.glob("*.yml.j2")) + list(module_dir.glob("*.yaml.j2"))
    return [f.name.split(".")[0] for f in files]


def get_dag():
    """
    Builds the module dependency graph.

    Returns:
        dict: Mapping of module name to its list of required dependencies.
    """
    dag_graph = {}
    for module_name in list_modules():
        mod_cfg = paths.module_cfg(module_name)
        dag_graph[module_name] = mod_cfg.get("needs", [])
    return dag_graph


def get_topological_ranks():
    """
    Groups modules into execution ranks based on their dependencies.

    Returns:
        list: List of ranks, where each rank is a list of modules that can run in parallel.

    Raises:
        ValueError: If a circular dependency is detected.
    """
    dag_graph = get_dag()
    modules = list(dag_graph.keys())
    in_degree = {m: len(dag_graph[m]) for m in modules}
    dependents = {m: [] for m in modules}
    for m, needs in dag_graph.items():
        for n in needs:
            if n in dependents:
                dependents[n].append(m)

    queue = [m for m in modules if in_degree[m] == 0]
    ranks = []

    while queue:
        queue.sort()
        ranks.append(queue[:])
        next_queue = []
        for m in queue:
            for dep in dependents[m]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    next_queue.append(dep)
        queue = next_queue

    if sum(len(r) for r in ranks) != len(modules):
        unprocessed = [m for m, d in in_degree.items() if d > 0]
        raise ValueError(f"Circular dependency detected: {unprocessed}")

    return ranks


def get_subgraph(module_names, dag_graph=None):
    """
    Resolves the union of all descendants for a given set of modules.

    Args:
        module_names (list|str): One or more starting module names.
        dag_graph (dict): Optional pre-built DAG.

    Returns:
        list: Names of all modules in the resulting subgraph.
    """
    if isinstance(module_names, str):
        module_names = [module_names]

    if dag_graph is None:
        dag_graph = get_dag()

    dependents = {m: [] for m in dag_graph}
    for m, needs in dag_graph.items():
        for n in needs:
            if n in dependents:
                dependents[n].append(m)

    subgraph, stack = set(), list(module_names)
    while stack:
        node = stack.pop()
        if node not in subgraph:
            subgraph.add(node)
            if node in dependents:
                stack.extend(dependents[node])
    return list(subgraph)


def get_category_map():
    """
    Groups modules by their semantic 'category' tag defined in YAML body.

    Returns:
        dict: Mapping of category name to list of associated modules.
    """
    cat_map = {}
    for module_name in list_modules():
        mod_cfg = paths.module_cfg(module_name)
        category = mod_cfg.get("category", "default")
        if category not in cat_map:
            cat_map[category] = []
        cat_map[category].append(module_name)
    return cat_map


def export_dag(output_path="assets/dag.dot"):
    """
    Generates a Graphviz DOT file representing the module dependencies.

    Args:
        output_path (str): Target path for the DOT file.
    """
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    dag_graph = get_dag()

    lines = [
        "digraph G {",
        "  rankdir=LR;",
        '  node [shape=box, style=filled, fillcolor=lightblue, fontname="Arial"];',
        "",
    ]
    for m, needs in dag_graph.items():
        if not needs:
            lines.append(f'  "{m}" [fillcolor=lightgrey];')
        else:
            for dep in needs:
                lines.append(f'  "{dep}" -> "{m}";')
    lines.append("}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Exported: {output_path}")
