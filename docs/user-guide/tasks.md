# Task Development

SciCD supports any standard [Luigi](https://luigi.readthedocs.io/) task. When running within a SciCD-managed pipeline, tasks automatically inherit platform-level capabilities like remote data syncing.

## Core Feature: Remote State Syncing

A primary benefit of SciCD is that **all Luigi tasks** automatically handle data persistence across ephemeral CI/CD workers.

Through global event handlers, SciCD intercepts the task lifecycle:

- **On Start**: Automatically pulls required inputs from remote storage (S3, GCP, etc.) to the local worker.
- **On Success**: Automatically pushes generated outputs back to remote storage.

This feature is "transparent" and applies to any task inheriting from `luigi.Task`, provided remote syncing is enabled in your configuration.

## Utility: `SciTask`

While you can use standard tasks, SciCD provides an augmented task factory in `scicd.frontend.luigi.task` that solves common scientific computing challenges: standardized pathing, remote pulling/pushing, and content-based completion.

The module exports three pre-configured classes:

1. **`AutoTask`**: Remote syncing enabled. No fingerprinting.
2. **`SciTask`**: Remote syncing + config/param fingerprinting.
3. **`DevTask`**: Remote syncing + config/param fingerprinting + Git commit hash fingerprinting.

### 1. Hash-Based Completion (`SciTask` & `DevTask`)

Standard Luigi tasks are considered "complete" if their output file exists. The hashed variants augment this by checking a **fingerprint**. A task is only complete if the output exists *and* its `.luigi_fingerprints/` hash matches the current:

- **Task Parameters**
- **Cascading Configuration** (Insignificant parameters from YAML)
- **Code Version** (Git commit hash - `DevTask` only)

### 2. Standardized Pathing

These classes provide an `output_path` helper that automatically anchors your task's data within the workspace's remote root.

```python
from scicd.frontend.luigi.task import SciTask
import luigi

class ProcessData(SciTask):
    @property
    def path(self):
        # Resulting path: <remote_root>/my_experiment/results
        return "my_experiment/results"

    def output(self):
        return luigi.LocalTarget(str(self.output_path / "data.csv"))

    def run(self):
        # Standard Luigi logic
        with self.output().open("w") as f:
            f.write("result")
```

## Centralized Parameter Management

For large pipelines, managing individual YAML files for every task can be cumbersome. `SciTask` supports a centralized parameter model via your `scicd.yaml` configuration.

### Configuration

Add the following to your `user` section:

```yaml
# scicd.yaml
user:
  path_cascade: "config/params.yml.j2" # Central file for all task parameters
```

### Centralized File Structure

Your centralized file (e.g., `params.yml.j2`) should be structured with task family names as keys:

```yaml
# params.yml.j2
pipelines:
  v1:
    ProcessData:
      config:
        threshold: 0.5
      override:
        - match: { env: "prod" }
          config: { threshold: 0.8 }

    OtherTask:
      config:
        window: 10
```

When `path_cascade` is defined, `SciTask` will automatically look for its configuration within that file, namespaced by its class name (and optionally prefixed by `cascade_root`).

## Summary: Standard vs. SciCD Tasks

| Feature | `luigi.Task` | `AutoTask` | `SciTask` | `DevTask` |
| :--- | :---: | :---: | :---: | :---: |
| **Remote Syncing** | ✅ (Global) | ✅ | ✅ | ✅ |
| **File-based Completion** | ✅ | ✅ | ✅ | ✅ |
| **Workspace-anchored Pathing** | ❌ | ✅ | ✅ | ✅ |
| **Code Config Fingerprinting** | ❌ | ❌ | ✅ | ✅ |
| **Git Commit Fingerprinting** | ❌ | ❌ | ❌ | ✅ |
