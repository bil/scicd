# SciCD Documentation

Welcome to the SciCD (Scientific CI/CD) documentation. SciCD is a robust execution engine and pipeline orchestrator designed to run scientific data pipelines seamlessly on CI/CD platforms like GitLab.

## What is SciCD?

SciCD bridges the gap between local Python-based workflow development and high-scale remote execution. By separating the **Frontend** (like Luigi) from the **Backend** (like GitLab CI/CD), it allows researchers to write native Python code while leveraging the full power of modern CI/CD clusters.

## Navigation

- [Getting Started](getting-started.md): Installation and your first pipeline.
- **Project Structure**:
  - `scicd/`: Core engine, configuration, and abstract DAG nodes.
  - `scicd/frontend/`: Framework integrations (e.g., Luigi).
  - `scicd/backend/`: CI/CD platform generators (e.g., GitLab).
  - `tests/`: Comprehensive test suite.
  - `docs/`: Extensive documentation.
  - `.scicd/`: Workspace-specific extensions.
- **User Guide**:
  - [Configuration](user-guide/configuration.md): Workspace and Task settings.
  - [Build Process](user-guide/build.md): Turning workflows into CI/CD.
  - [CLI & Overrides](user-guide/cli.md): Command line power usage.
  - [Task Development](user-guide/tasks.md): Writing robust tasks with SciTask.
  - **Reference**:
  - [Architecture](reference/architecture.md): How SciCD works under the hood.
  - **Project Info**:
  - [Roadmap](roadmap.md): Future directions and planned features.

- **Developer Guide**:
  - [Testing](developer/testing.md): Maintaining quality in SciCD.
