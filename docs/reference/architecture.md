# Architecture

SciCD is designed around three core layers: Adapters, the abstract DAG, and Backends.

## 1. Adapters (`scicd.adapter`)

The bridge between a pipeline framework (like Luigi) and SciCD. Adapters handle framework-specific logic, extracting parameters and execution commands. They ensure that the core engine doesn't need to know the details of the underlying workflow tool.

## 2. DAG & Nodes (`scicd.dag`)

The abstract DAG is the heart of SciCD. It represents the execution plan as a series of connected Nodes. Each node represents one or more units of work.

### `BijectNode` (1:1 Mapping)

A `BijectNode` represents a direct 1:1 mapping from a single unit of work (e.g., one Luigi task instance) to a single job in the backend CI/CD system. This is used for standard sequential or parallel tasks where the number of jobs is known at build time.

### `SliceNode` (Dynamic Fan-out)

A `SliceNode` represents a dynamic fan-out execution. It groups multiple units of work together and uses a "generator" job to scatter them across a set of parallel workers. This is ideal for large-scale data processing where you might have thousands of small tasks that you want to execute concurrently across a fixed number of CI/CD runners.

## 3. Backends (`scicd.build`)

Backends render the abstract DAG into platform-specific configurations.

- **GitLab CI/CD**: Renders nodes into jobs, stages, and child pipelines (for `SliceNode`).
- **Graphviz DOT**: Renders the DAG into a visual graph format.
