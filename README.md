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
- **Floating Scripts:** A sequence of Bash/R/CLI commands defined directly in YAML.

---

## Installation

Install the package directly from source:

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

Required for all local execution and DAG orchestration:

- `fire`, `pyyaml`, `jinja2`, `python-frontmatter`, `python-dotenv`, `joblib`

### Feature-Specific Requirements

| Feature       | Requirement           | Description                                        |
| :------------ | :-------------------- | :------------------------------------------------- |
| **Data Sync** | `rclone` (binary)     | Required for `push_data` and `pull_data` sync.     |
| **GitLab CI** | `python-gitlab`       | Required for `scicd run_module --executor=gitlab`. |
| **GCP Queue** | `google-cloud-pubsub` | Required for distributed worker pools via GCP.     |

### Configuration & Credentials

Advanced orchestration requires a `.env` file in your project root:

- **GitLab CI:** Requires `GITLAB_PAT` with `api` scope. Configure the `gitlab` section in `scicd.yaml`.
- **GCP Queue:** Requires active GCP credentials and a `gcp` section in `scicd.yaml` (project, topic, subscription).
- **Data Sync:** Requires a valid `rclone` config matching the `storage.remote` key in `scicd.yaml`.

## Module Configuration Reference

Each module in `module/*.yml.j2` supports the following keys.

### Core Keys

| Key | Type | Description |
| :--- | :--- | :--- |
| **`root_path`** | `str` | **Mandatory.** The base directory for all instance results. |
| **`src`** | `str` | Path to the Python module (e.g., `src.analysis`). **Mandatory** if `script` is not used. |
| **`script`** | `str/list` | Shell/CLI commands. **Mandatory** if `src` is not used. |
| **`path`** | `str` | **Mandatory for Scripts.** Jinja2 template for instance-specific subdirectories. |
| **`class`** | `str` | Name of the Python class. Defaults to the module filename. |

### Logic & Orchestration

| Key | Type | Description |
| :--- | :--- | :--- |
| **`needs`** | `list` | List of module dependencies for the DAG. |
| **`category`** | `str` | Semantic tag for grouping (e.g., `preprocessing`, `figure`). |
| **`input`** | `list[dict]` | Static list of task identities (Input List). |
| **`input_generator`** | `dict` | Dynamic generator (script or src) to produce the input list. |
| **`param`** | `dict` | Default behavioral parameters passed to `run()`. |
| **`overwrite`** | `list[dict]` | Regex-based parameter overrides for specific inputs. |

### Execution Overrides

These keys allow a module to tune its environment, overriding the global `scicd.yaml` defaults.

- **`logging`**: Set `verbose: false` to silence execution logs for this module.
- **`joblib`**: Override the local parallel `backend`.
- **`gcp`**: Specify a custom Pub/Sub `topic` or `subscription`.
- **`ci`**: Custom GitLab CI `tags`, `rules`, or `variables`.
- **`concurrency`**: Override the scaling `method` or `workers` count.

### Lifecycle Hooks (`pre` / `post` / `input_generator`)

Hooks allow executing logic before, after, or to define the input list of the main task. These are **deterministic** and executed without instantiating the module class. They do not have access to task-specific inputs or regex overrides.

- **`pre` / `post`**: Standard setup and cleanup hooks.
- **`input_generator`**: Specialized hook to dynamically produce the module's `input` list.

#### Hook Configuration

Each hook is a dictionary containing:

- **`script`**: (Optional) Shell/CLI commands. **Mandatory** for Script-based modules.
- **`param`**: (Optional) Parameters passed to the script or class method.

#### OOP Fallback (Python Modules Only)

For Python modules (`src`), if a hook dictionary is provided without a `script` key, the framework automatically calls the corresponding **static/class method** on the task class: `MyClass.pre()`, `MyClass.post()`, or `MyClass.input_generator()`. These methods must be implemented to accept the hook's `param` dictionary.

#### Constraints

- **Script Modules**: MUST provide a `script` key for every hook used. They cannot use OOP fallbacks.
- **Script Modules**: Prohibited from defining a `class` key.
- **JSON Output**: `input_generator` scripts must print a JSON list of dictionaries to `stdout`.

---

### Script Environment Reference

Modules using the `script` backend (and all script-based hooks) receive a rich set of environment variables for easy integration with existing CLI tools.

#### Standard Variables

| Variable | Description |
| :--- | :--- |
| **`SCICD_ROOT_DIR`** | Absolute path to the module's root results directory. |
| **`SCICD_OUT_DIR`** | Absolute path to the instance-specific results folder (for hooks, this matches `ROOT_DIR`). |
| **`SCICD_INPUT`** | JSON-encoded string containing all task identity inputs. |
| **`SCICD_PARAM`** | JSON-encoded string containing all behavioral parameters. |

#### Individual Context Variables

The framework also injects every key from `input` and `param` as individual uppercase variables:

- **`SCICD_INPUT_<KEY>`**: e.g., `SCICD_INPUT_SUBJECT`
- **`SCICD_PARAM_<KEY>`**: e.g., `SCICD_PARAM_THRESHOLD`

*Note: For nested structures, individual variables contain the string representation. Use `jq` with the JSON blobs for robust parsing of complex data.*

#### Bash Integration Example

```bash
# Simple usage (Top-level parameters)
echo "Processing $SCICD_INPUT_SUBJECT with threshold $SCICD_PARAM_THRESHOLD"

# Complex usage (Nested data via jq)
METADATA=$(echo $SCICD_PARAM | jq -r '.analysis.metadata')
```

---

## Configuration Hierarchy

`scicd` uses a multi-layered configuration merge strategy. Settings are resolved in the following order (bottom takes precedence):

1. **Framework Defaults:** Baseline settings bundled with the package (`scicd/resources/defaults.yaml`).
2. **Workspace Config (`scicd.yaml`):** Project-wide infrastructure settings.
3. **Module Config (`module/*.yml.j2`):** Task-specific execution overrides.
4. **CLI Arguments:** Immediate runtime overrides (e.g., `--workers=8`).

### Merge Diagram

```text
[ Framework Defaults ]
          ↓
[ Workspace Config (scicd.yaml) ]  <-- Infrastructure Layer (Global)
          ↓
[ Module Config (MyModule.yaml) ]  <-- Execution Layer (Scoped)
          ↓
[ CLI Arguments (--workers=8)   ]  <-- Runtime Layer (Immediate)
```

### Infrastructure vs. Execution Settings

| Layer              | Sections                                        | Capability                                           |
| :----------------- | :---------------------------------------------- | :--------------------------------------------------- |
| **Infrastructure** | `internal`, `storage`, `gitlab`                 | **Global Only.** Defines *where* the project lives.  |
| **Execution**      | `logging`, `joblib`, `gcp`, `ci`, `concurrency` | **Overridable.** Defines *how* a specific task runs. |

### Configuration Key Details

#### Infrastructure (Global)

- **`internal`**: Framework paths (`module_dir`, `ci_dir`).
- **`storage`**: Data persistence (`output`, `remote`, `use_branch`, `deposition_url`).
- **`gitlab`**: GitLab API integration (`url`, `project`).

#### Execution (Scoped)

- **`logging`**: Verbosity settings.
- **`gcp`**: Pub/Sub settings for the `queue` strategy.
- **`joblib`**: Local parallelism backend and verbosity.
- **`ci`**: GitLab CI job defaults and variables.
- **`concurrency`**: Defines the scaling strategy for each environment.
  - `method`: The execution strategy (`thread`, `matrix`, `slice`, or `queue`).
  - `workers`: The degree of parallelism (e.g., number of threads or CI nodes).

---

## Concurrency & Scaling

The `concurrency` block defines how tasks are distributed. By default, the framework uses:

- **Local:** `method: thread`, `workers: 1`
- **GitLab:** `method: matrix`

### Concurrency Managers

| Method | Environment | Description | Workers Behavior |
| :--- | :--- | :--- | :--- |
| **`thread`** | Local/CI | Parallel execution via `joblib`. | Sets the size of the local thread/process pool. |
| **`matrix`** | GitLab | 1:1 mapping of tasks to CI jobs. | **Ignored.** Scaled automatically by the number of inputs. |
| **`slice`** | GitLab | Modulo distribution across a fixed pool. | Sets the number of parallel GitLab runner nodes. |
| **`queue`** | GitLab | Distributed pool via GCP Pub/Sub. | Sets the number of concurrent workers pulling from the queue. |

### Overriding Workers

The `workers` value in the configuration defines the default parallelism. You can override this at runtime using the `--workers` flag:

```bash
# Override local threads (e.g., from 2 to 8)
scicd run_all --workers=8

# Override GitLab parallel nodes (for 'slice' or 'queue' methods)
scicd run_module MyModule --executor=gitlab --workers=10
```

*Note: The `--workers` flag is ignored when using the `matrix` method.*

### CLI Orchestration Parameters

The `run` commands (e.g., `run_module`, `run_all`) support the following arguments for fine-grained control:

- **`--executor`**: Defines where the orchestration is initiated.
  - `local` (default): Executes tasks on your current machine.
  - `gitlab`: Triggers a remote pipeline via the GitLab API.
- **`--workers`**: Overrides the default degree of parallelism.
  - For `local`: Number of Joblib threads.
  - For `gitlab`: Number of parallel CI nodes (for `slice` or `queue` methods).
- **`--method`**: Overrides the default scaling strategy for the chosen environment.
  - Options: `thread`, `matrix`, `slice`, `queue`.

Example:

```bash
# Trigger a GitLab pipeline with 10 parallel worker nodes
scicd run_all --executor=gitlab --method=queue --workers=10
```

---

## Project Structure

```text
.
├── scicd.yaml          # Project-level defaults (storage, gitlab, etc.)
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
path: "{{ subject }}/{{ session }}"

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

| Strategy   | Environment | Implementation                                  |
| :--------- | :---------- | :---------------------------------------------- |
| **Thread** | Local/CI    | Parallel execution via `joblib`.                |
| **Matrix** | CI          | 1:1 mapping of tasks to CI jobs.                |
| **Slice**  | CI          | Modulo distribution across a fixed worker pool. |
| **Queue**  | CI          | Distributed worker pool using GCP Pub/Sub.      |

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
# Trigger a GitLab pipeline for specific modules
scicd run_module MyModule --executor=gitlab

# Sync local results to remote storage
scicd push_data --path=results/analysis
```

---

## Example Project

A complete, sanitized template project is provided in the `examples/` directory.
To get started, review `examples/scicd.yaml` and the corresponding `examples/module/` definitions.
