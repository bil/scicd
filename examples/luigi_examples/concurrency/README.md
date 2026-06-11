# Luigi Examples: Concurrency

If a large number of a single Luigi task are generated at once in a workflow, it is undesirable to pay the overhead of provisioning an execution environment for each task instance in CI/CD.
SciCD provides a `concurrency` configuration as one solution to this.
By default, `concurrency.method=biject` so that each task instance generates a single CI/CD job.
Instead, one can set `concurrency.method=slice` and `concurrency.workers=4` to evenly split a family's task instances across 4 worker jobs.
