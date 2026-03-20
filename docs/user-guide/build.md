# Building Pipelines

The build process is the bridge between your local Python workflow and the remote CI/CD environment. SciCD takes your task dependency graph and compiles it into a platform-native configuration.

## The `scicd build` Command

The core command for generating pipelines is `scicd build`.

```bash
scicd build --module <python_module> --target <task_class> [OVERRIDES]
```

### Key Arguments

- `--module`: The Python module containing your root task (e.g., `my_project.workflow`).
- `--target`: The class name of the Luigi task you want to run (e.g., `ProcessAllData`).
- `--filepath`: (Optional) The output path for the generated file. Defaults to `.gitlab-ci.yml`.
- `--backend`: (Optional) The target format. Options: `gitlab` (default), `dot`.

## Frontends and Backends

SciCD is built on a modular architecture that separates the source of your workflow (Frontend) from the target execution platform (Backend).

### Frontends

A **Frontend** is responsible for parsing a workflow definition and converting it into SciCD's abstract Directed Acyclic Graph (DAG). 

Currently, **Luigi** is the primary supported frontend.

| Frontend | CLI Flag | Status |
| :--- | :--- | :--- |
| **Luigi** | `--frontend luigi` | Production Ready |
| **Snakemake** | `--frontend snakemake` | *Planned* |

#### Luigi Frontend Details
When using the Luigi frontend, SciCD:
1.  Imports your Python module.
2.  Instantiates your target task class.
3.  Recursively discovers all dependencies.
4.  Maps each Luigi task instance into an abstract `BijectNode` or `SliceNode`.

### Backends

A **Backend** takes the abstract DAG and renders it into a specific output format.

| Backend | CLI Flag | Status |
| :--- | :--- | :--- |
| **GitLab** | `--backend gitlab` | Production Ready |
| **Graphviz** | `--backend dot` | Visual Debugging |
| **GitHub Actions**| `--backend github` | *Planned* |

## Turning a Workflow into GitLab CI/CD

To convert your Python workflow into a GitLab pipeline, follow these steps:

1. **Define your Root Task**: Ensure your workflow has a clear entry-point task that requires all other necessary work.
2. **Verify Locally**: It's often helpful to run a small subset of your data locally using standard Luigi commands to ensure dependencies are correct.
3. **Run the Build**:

    ```bash
    scicd build --module my_workflow --family RootTask
    ```

4. **Review the YAML**: Open the generated `.gitlab-ci.yml` to verify that stages and jobs are mapped as expected.
5. **Commit and Push**:

    ```bash
    git add .gitlab-ci.yml
    git commit -m "Update CI/CD pipeline"
    git push origin main
    ```

Once pushed, GitLab will detect the `.gitlab-ci.yml` and start executing the jobs based on the `rules` defined in your `scicd.yaml`.

## Visualizing the DAG

Before deploying, you can visualize the execution plan by exporting it to Graphviz DOT format:

```bash
scicd build --module my_workflow --family RootTask --backend dot --filepath dag.dot
```

You can then render this using `dot`:

```bash
dot -Tpng dag.dot -o dag.png
```
