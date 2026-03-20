# Roadmap

SciCD is actively evolving to support more scientific workflows and execution platforms.

## Planned Frontends

- **Snakemake**: Support for Snakemake workflows as a frontend, allowing Snakemake rules to be mapped to CI/CD jobs.

## Planned Backends

- **GitHub Actions**: Support for generating GitHub Actions `.github/workflows/` configurations.

## Cross-Job Concurrency

- **Queue-based Execution**: Support for FIFO-style cross-job concurrency. This will allow tasks to be queued and executed as resources become available, providing better control over cluster utilization and handling long-running task queues.

## Data Integrity & Provenance

- **Trusted Timestamping**: Integration of cryptographically secure proof of creation and modification for computation artifacts and code.
  - This will leverage the principles discussed in Paul Nuyujukian's paper: [Leveraging DevOps for Scientific Computing](https://arxiv.org/abs/2310.08247) (arXiv:2310.08247).
  - Implementing RFC 3161 compliant timestamping to ensure long-term verifiability of research data and code provenance.
  - Automated notarization of computation digests within the CI/CD pipeline.
