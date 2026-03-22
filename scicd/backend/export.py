from scicd.backend.gitlab.decode import write_gitlab_yaml


def export_dag(dag, filepath=None, backend="gitlab", **boilerplate):
    """Functional dispatch to export a DAG using various backends."""
    if backend == "gitlab":
        filepath = filepath or ".gitlab-ci.yml"
        return write_gitlab_yaml(dag, filepath=filepath, **boilerplate)
    if backend == "github":
        raise NotImplementedError("GitHub Actions backend is not yet implemented.")
    if backend == "dot":
        filepath = filepath or "dag.dot"
        return dag.export_dot(filepath)
    raise ValueError(f"Unsupported backend: {backend}")
