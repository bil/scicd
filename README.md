# scicd

`scicd` is an orchestration framework for managing complex analysis pipelines through a self-organizing Directed Acyclic Graph (DAG). It provides a unified interface for executing tasks locally or across distributed CI/CD environments.

## Core Philosophy

### 1. Decentralized Configuration
Pipeline structure is discovered dynamically. Each module defines its own dependencies (`needs`), inputs, and parameters in a local YAML file. There is no central registry; the DAG is reconstructed at runtime via topological sorting.

### 2. Identity vs. Behavior
- **Identity (Inputs):** Arguments that define *what* the task is. These strictly determine the output `path()`.
- **Behavior (Parameters):** Arguments that define *how* the task runs. These modify logic but do not affect the result's location.

### 3. Polymorphic Backends
Tasks can be implemented as either:
- **Python OOP:** Subclasses of `scicd.module.Module` for complex logic.
- **Shell Scripts:** YAML-defined Bash/R/CLI commands for rapid integration of existing tools.

---

## Installation

Install the package directly from source.

**HTTPS:**
```bash
pip install git+https://github.com/your-username/scicd.git
```

**SSH:**
```bash
pip install git+ssh://git@github.com/your-username/scicd.git
```

---

## Dependencies & Requirements

`scicd` uses a modular architecture where specific dependencies are required for advanced features.

### Core Requirements
Required for all local execution and DAG orchestration.
- `fire`, `pyyaml`, `jinja2`, `python-frontmatter`, `python-dotenv`, `joblib`

### Feature-Specific Requirements

| Feature | Requirement | Description |
| :--- | :--- | :--- |
| **Data Sync** | `rclone` (binary) | Must be installed and configured in your environment to use `push_data` and `pull_data`. |
| **GitLab CI** | `python-gitlab` | Required for `scicd run_module ... --executor=gitlab`. |
| **GCP Queue** | `google-cloud-pubsub` | Required for distributed worker pools via Google Cloud Pub/Sub. |

### Configuration & Credentials
Advanced orchestration requires a `.env` file in your project root:

- **GitLab CI:** Requires `GITLAB_PAT` (Personal Access Token) with `api` scope and a `gitlab` section in your `scicd.yaml`.
- **GCP Queue:** Requires active GCP credentials (e.g., `GOOGLE_APPLICATION_CREDENTIALS`) and a `gcp` section in `scicd.yaml` specifying a `project`, `pubsub_topic`, and `pubsub_subscription`.
- **Data Sync:** Requires a valid `rclone` config file (`~/.config/rclone/rclone.conf`) with a remote matching the `remote` key in your `scicd.yaml`.

---

## Project Structure

```text
.
├── scicd.yaml          # Project-level defaults
├── module/             # Module definitions (*.yml.j2)
├── src/                # Python source code
├── script/             # Executable scripts
└── data/               # Local results (isolated by branch)
```

---

## Module Definition

Modules are defined using YAML front-matter for inheritance and Jinja2 for dynamic pathing.

`module/Analysis.yml.j2`:
```yaml
---
merge: base/default  # Inherit common settings
needs: [Preprocess]  # DAG dependency
---
src: src.logic
class: AnalysisTask
root_path: results/analysis

input:
  - { subject: S01, session: 1 }
  - { subject: S01, session: 2 }

param:
  threshold: 0.5

# Input-specific parameter overrides
overwrite:
  - input: { subject: "S01" }
    param: { threshold: 0.8 }
```

---

## Scaling Strategies

`scicd` abstracts execution environments through a unified concurrency schema:

| Strategy | Environment | Implementation |
| :--- | :--- | :--- |
| **Thread** | Local | Parallel execution via `joblib`. |
| **Matrix** | GitLab | 1:1 mapping of tasks to CI jobs. |
| **Slice** | GitLab | Modulo distribution across a fixed worker pool. |
| **Queue** | GitLab/GCP | Distributed worker pool using Google Cloud Pub/Sub. |

---

## CLI Usage

### Local Execution
```bash
# Run the full DAG
scicd run_all

# Run a specific module and its descendants
scicd run_subgraph MyModule --workers=4

# Execute a single task instance
scicd exec_module MyModule --subject=S01 --session=1
```

### CI/CD Orchestration
```bash
# Compile and trigger a GitLab pipeline for specific modules
scicd run_module MyModule --executor=gitlab

# Sync local results to remote storage
scicd push_data --path=results/analysis
```

---

## Example Project

A complete, sanitized template project is provided in the `examples/` directory of this repository. This example demonstrates:
- A multi-module DAG with dependencies.
- Use of both Python and Script backends.
- Dynamic input generation.
- Configuration inheritance.

To get started, review `examples/scicd.yaml` and the corresponding `examples/module/` definitions.
