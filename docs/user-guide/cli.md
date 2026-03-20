# CLI & Overrides

The SciCD CLI is the primary tool for building, linting, and managing pipelines.

## Command Reference

### `scicd build`

Compiles a local target into a CI/CD pipeline or visualization.

```bash
scicd build --module my_module --target MyTask
```

## Argument Namespacing

SciCD uses a strict namespaced argument system to prevent collisions between task parameters and CI/CD configuration.

| Prefix | Target | Example |
| :--- | :--- | :--- |
| `--task-` | `TaskConfig` fields (CPU, RAM, tags, image) | `--task-cpu 8 --task-image "python:3.10"` |
| *(None)* | Frontend (Luigi) Task parameters | `--date 2024-03-20 --TaskName-param val` |

### Security Note

Workspace-level settings (like remote storage URLs or repository credentials) **cannot** be overridden via the CLI. They must be defined in the configuration YAML file.
