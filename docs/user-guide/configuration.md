# Configuration

SciCD uses a Pydantic-based configuration system to manage workspace settings and task defaults with automatic validation and normalization.

## Configuration Discovery

SciCD automatically searches for its configuration in the following order:

1. **`SCICD_CONFIG_PATH`** (Environment Variable)
2. **`scicd.yaml`** (Project Root)
3. **`.scicd/config.yaml`**
4. **`.scicd/scicd.yaml`**

## Workspace Configuration

The `workspace` section defines your source control platform and CI/CD boilerplate.

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

Global defaults for every task instance. These are automatically merged into each task's `TaskConfig`.

```yaml
task:
  cpu: 1
  memory: 4Gi
  retry: 3
  tags: ["standard"]
```

### Data Normalization

SciCD automatically normalizes specific string formats:

- **Memory/Disk:** Supports both **SI (Decimal)** and **IEC (Binary)** units.
    - `1G`, `1GB` (SI): Uses $1000^3$ bytes.
    - `1Gi`, `1GiB` (IEC): Uses $1024^3$ bytes.
    - Integers are assumed to be megabytes (MiB).
- **Time/Timeout:** '1h30m' is stored as '1h 30m'. Integers are assumed to be minutes.

## Configuration Precedence

SciCD resolves task configurations using a strict precedence order:

1. **CLI Overrides:** Arguments passed via the CLI (e.g., `scicd build --cpu 8`).
2. **Task-Specific Code:** Hardcoded settings within the task class (e.g., the `scicd` dictionary).
3. **YAML Configuration:** Values defined in your configuration file.
4. **SciCD Base Defaults:** Internal baseline defaults.

## Environment Variable Interpolation

SciCD provides multiple ways to interpolate environment variables into your configuration.

### Build-Time Expansion (`$VAR`)

By default, any string containing `$VAR` or `${VAR}` in your configuration files will be expanded at build-time (when you run `scicd build` or `scicd local`). This is useful for anchoring paths to your local environment.

```yaml
user:
  data_path: "$HOME/my_data"
```

### Run-Time Escaping (`$$VAR`)

If you want a variable to be passed through literally to the generated CI/CD YAML (to be evaluated by the GitLab/GitHub runner), use the `$$` escape sequence.

```yaml
task:
  variables:
    JOB_ID: "$$CI_JOB_ID"  # Becomes "$CI_JOB_ID" in the generated YAML
```

### Jinja2 Templating

In addition to standard expansion, all configuration files are rendered as Jinja2 templates before parsing. This allows for complex logic, includes, and explicit environment access via the `env` object:

```yaml
workspace:
  project: "org/my-repo-{{ env.USER }}"
```

## Cascading Configuration

Configured via `path_cascade` in the `user` section:

```yaml
user:
  path_cascade: "config/params.yml.j2"
```

The `user` section is a **Dynamic Model**, allowing arbitrary nested keys that can be accessed via dot-notation in your code (e.g., `task.task_config.user.my_custom_setting`).
