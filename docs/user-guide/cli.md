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

### Dot-Notation Overrides

SciCD supports deep namespacing via dot-notation. This is particularly useful for overriding nested configuration blocks like `remote`, `concurrency`, or custom `user` settings.

```bash
scicd build --remote.pull_inputs true --user.project.id 123 --user.settings.debug true
```

The CLI automatically reconstructs these into nested dictionaries, which are then validated against the `TaskConfig` schema.

### Automatic Type Coercion

Thanks to Pydantic integration, the CLI automatically coerces strings into the correct types:

- **Integers:** `--cpu 4` becomes `int(4)`.
- **Booleans:** `--remote.pull_inputs true`, `yes`, or `1` all become `True`.
- **Lists:** `--remote.flags "['--test', '--fast']"` is parsed into a Python list.
- **Complex Strings:** `--memory 16Gi` or `--timeout 1h30m` are normalized into their canonical formats.

## Internal Data Passing

To ensure robustness against shell escaping and command-line length limits, SciCD passes large JSON payloads (like task parameters and full configurations) via `SCICD_` prefixed environment variables instead of CLI arguments.
