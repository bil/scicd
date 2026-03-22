# CLI & Overrides

The SciCD CLI is the primary tool for building, testing, and managing pipelines.

## Command Reference

### `scicd build`

Compiles a target into a CI/CD pipeline configuration (e.g., `.gitlab-ci.yml`).

```bash
scicd build --module my_module --target MyTask
```

### `scicd local`

Executes a target locally using the underlying framework (like Luigi). Useful for testing logic during development.

```bash
scicd local --module my_module --target MyTask --my_param 123
```

### `scicd run`

Internal entrypoint used by CI/CD runners. It expects task parameters to be provided via the `SCICD_PARAMS` environment variable.

## Argument Namespacing

SciCD intercepts specific arguments to override configuration while passing others to the underlying framework.

| Field Type | Target | Example |
| :--- | :--- | :--- |
| `TaskConfig` fields | Task defaults (CPU, memory, image, remote) | `--cpu 8 --image "python:3.10" --remote.pull_inputs false` |
| *(Other)* | Frontend (Luigi) Task parameters | `--date 2024-03-20 --window_size 10` |

### Security Note

Workspace-level settings (like `workspace.url` or `workspace.project`) **cannot** be overridden via the CLI. They must be defined in the configuration file.

## Internal Data Passing

To ensure robustness against shell escaping and command-line length limits, SciCD passes large JSON payloads (like task parameters and full configurations) via `SCICD_` prefixed environment variables instead of CLI arguments.
