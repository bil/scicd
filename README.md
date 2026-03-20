# SciCD

SciCD is a robust execution engine and pipeline orchestrator designed to run scientific data pipelines seamlessly on CI/CD platforms like GitLab.

By separating the **Frontend** (task dependency frameworks like Luigi) from the **Backend** (CI/CD platforms like GitLab), SciCD allows you to write complex workflows natively in Python while automatically mapping and deploying them onto highly concurrent remote workers.

## Key Features

* **Abstract DAG Architecture:** Tasks are wrapped into `Adapters` (like `LuigiAdapter`) to decouple specific framework knowledge from the core SciCD engine. The DAG consists of abstract Nodes (`BijectNode` for 1:1 mapping, `SliceNode` for dynamic fan-out execution) which render out to standard backend definitions.
* **Intelligent Caching with `HashTask`:** SciCD provides `HashTask` (a powerful augmented `luigi.Task`), which hashes code versions, parameters, and configurations. It determines completions empirically via fingerprints to avoid redundant remote work.
* **Remote State Syncing:** Tasks gracefully and automatically pull required inputs and push calculated outputs to remote storages (using `rclone` or `https`) thanks to built-in, global event-hook integration.
* **Universal Build CLI:** Easily translate a local target task into a `.gitlab-ci.yml` pipeline or an exportable `.dot` graph via `scicd build --module my_module --target MyTask`.

## CLI Overrides

SciCD uses a namespaced argument system to prevent collisions between task parameters and CI/CD configuration.

| Prefix | Target | Example |
| :--- | :--- | :--- |
| `--task-` | `TaskConfig` fields (CPU, RAM, tags, image) | `--task-cpu 8 --task-image "python:3.10"` |
| *(None)* | Frontend (Luigi) Task parameters | `--date 2024-03-20 --MyTask-param 1` |

### Security Note

Workspace-level settings (like remote storage URLs or repository credentials) **cannot** be overridden via the CLI. They must be defined in `.scicd/config.yaml`.

## How it works

1. **Write your pipeline:** Build out your tasks using `HashTask`.
2. **Configure Workspace:** Define executors, resources (CPU, Memory), and storage backends (GCP, S3) in your workspace configuration.
3. **Build:** Run `scicd build` to convert your tree into an optimized, concurrent pipeline.
4. **Deploy:** Commit the generated CI/CD YAML and let your cluster churn through the data!
