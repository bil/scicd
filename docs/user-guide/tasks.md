# Task Development

SciCD supports any standard [Luigi](https://luigi.readthedocs.io/) task. When running within a SciCD-managed pipeline, tasks automatically inherit platform-level capabilities like remote data syncing.

## Core Feature: Remote State Syncing

A primary benefit of SciCD is that **all Luigi tasks** automatically handle data persistence across ephemeral CI/CD workers.

Through global event handlers, SciCD intercepts the task lifecycle:

- **On Start**: Automatically pulls required inputs from remote storage (S3, GCP, etc.) to the local worker.
- **On Success**: Automatically pushes generated outputs back to remote storage.

This feature is "transparent" and applies to any task inheriting from `luigi.Task`, provided remote syncing is enabled in your configuration.

## Utility: `HashTask`

While you can use standard tasks, SciCD provides the `HashTask` utility to solve common scientific computing challenges: standardized pathing and content-based completion.

### 1. Hash-Based Completion

Standard Luigi tasks are considered "complete" if their output file exists. `HashTask` augments this by checking a **fingerprint**. A task is only complete if the output exists *and* the fingerprint matches the current:

- **Code Version** (Git commit hash)
- **Task Parameters**
- **Cascading Configuration** (Insignificant parameters from YAML)

### 2. Standardized Pathing

`HashTask` provides an `output_path` helper that automatically anchors your task's data within the workspace's remote root.

```python
from scicd.task import HashTask
import luigi

class ProcessData(HashTask):
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

## Summary: Standard vs. HashTask

| Feature | `luigi.Task` | `HashTask` |
| :--- | :---: | :---: |
| **Remote Syncing** | ✅ (Global) | ✅ (Global) |
| **File-based Completion** | ✅ | ✅ |
| **Content-based Fingerprinting** | ❌ | ✅ |
| **Workspace-anchored Pathing** | ❌ | ✅ |
