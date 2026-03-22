# CLI & Overrides

The SciCD CLI is the primary tool for building, linting, and managing pipelines.

## Command Reference

### `scicd build`

Compiles a local target into a CI/CD pipeline or visualization.

```bash
scicd build --module my_module --target MyTask
```

### `scicd local`

Executes a target piece of work locally using the underlying framework (like Luigi), without generating a pipeline. Very useful for testing logic during development.

```bash
scicd local --module my_module --target MyTask --my_param 123
```

## Argument Namespacing

SciCD uses a smart interception system to apply configurations and pass parameters properly.

| Field Type | Target | Example |
| :--- | :--- | :--- |
| `TaskConfig` fields | Task defaults (CPU, memory, image, remote) | `--cpu 8 --image "python:3.10" --remote.pull-inputs false` |
| *(Other)* | Frontend (Luigi) Task parameters | `--date 2024-03-20 --window-size 10` |

### Security Note

Workspace-level settings (like `workspace.url` or `workspace.project`) **cannot** be overridden via the CLI. They must be defined in the configuration YAML file.
