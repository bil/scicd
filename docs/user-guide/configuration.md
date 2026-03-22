# Configuration

SciCD uses a YAML-based configuration system to manage workspace settings and task defaults.

## Configuration Discovery

SciCD automatically searches for its configuration in the following order:

1. **`SCICD_CONFIG_PATH`** (Environment Variable)
2. **`scicd.yaml`** (Project Root)
3. **`.scicd/config.yaml`**
4. **`.scicd/scicd.yaml`**

## Workspace Configuration

The `workspace` section defines your source control platform, and any CI/CD boilerplate for your desired backend

```yaml
workspace:
  platform: gitlab
  url: https://gitlab.com
  project: org/repo
  cicd:
    default:
      image: python:3.10

remote:
  protocol: rclone
  url: s3://my-bucket
  root: /data
```

## Task Defaults (`task`)

The `task` key provides global defaults for every task instance in your DAG. These are automatically merged into each task's `TaskConfig`.

```yaml
task:
  cpu: 1
  memory: 4Gi
  retry: 3
  tags: ["standard"]
```

## Configuration Precedence

SciCD resolves task configurations using a strict precedence order. This ensures that explicit commands always override general defaults. The order of precedence (from highest to lowest) is:

1. **CLI Overrides:** Arguments passed via the CLI (e.g., `scicd build --cpu 8`). These win against everything.
2. **Task-Specific Code:** Hardcoded settings within the task class (e.g., the `scicd = {'cpu': 4}` dictionary or Luigi's `resources()` method).
3. **YAML Task Defaults:** The `task` block in your `scicd.yaml` configuration file.
4. **SciCD Base Defaults:** The internal baseline defaults (e.g., `cpu=1`, `memory='8Gi'`).

## Environment Variable Interpolation

SciCD differentiates between variables that should be evaluated at **build-time** (when `scicd build` is run) and **run-time** (when the generated pipeline executes).

### Build-Time (Jinja2)

All configuration files are rendered as Jinja2 templates before parsing. You can explicitly access your local environment variables during `scicd build` via the `env` object:

```yaml
workspace:
  project: "org/my-repo-{{ env.USER }}"
```

Additionally, SciCD automatically expands environment variables in specific structural fields like `workspace.url`, `workspace.project`, `remote.root`, `remote.url`, and `task.image`.

### Run-Time (Native CI)

For values that need to be evaluated by the CI/CD runner (e.g., GitLab CI variables), use standard shell variable syntax. These will be passed into the generated YAML literally.

```yaml
task:
  variables:
    MY_RUNTIME_VAR: "$CI_JOB_ID"
    DB_PASSWORD: "$SECRET_PASSWORD"
```

## Cascading Configuration

SciCD supports powerful, dynamic configuration via the `scicd.yamler.cascade` feature. This allows you to define a base set of parameters and apply overrides based on runtime context (like Luigi task parameters).

To use this, configure a `path_cascade` in your `scicd.yaml`:

```yaml
user:
  path_cascade: "config/params.yml.j2"
```

Then, in `config/params.yml.j2`, you can use the `config` and `override` blocks:

```yaml
MyAnalysisTask:
  config:
    learning_rate: 0.01
    batch_size: 32
  override:
    - match: { dataset: "large_.*" } # Regex matching against task parameters!
      config:
        batch_size: 128
        cpu: 16
    - match: { env: "prod" }
      config:
        learning_rate: 0.001
```

If a task named `MyAnalysisTask` is run with the parameter `--dataset large_images`, the cascading system will evaluate the `override` rules top-to-bottom. The `batch_size` will be updated to `128` because the regex `large_.*` matches `large_images`.
