"""Luigi tasks for SciCD internal CI/CD."""

import subprocess
from pathlib import Path
import luigi


class RunTests(luigi.Task):
    """Run the pytest suite on a specific Python version."""

    python_version = luigi.Parameter(default="3.10")

    @property
    def scicd(self):
        """Dynamic configuration to override the container image."""
        # This can only be done using biject concurrency!
        # Otherwise, a task family must share a single set of resources
        return {
            "image": f"python:{self.python_version}",
            "tags": ["bilkube"],
        }

    def run(self):
        """Execute pytest."""
        print(f"Running pytest suite on Python {self.python_version}...")
        out = subprocess.run(["pytest"], check=True, capture_output=True)
        print("Pytest suite completed successfully.")
        self.output().makedirs()
        with open(self.output().path, "w", encoding="utf-8") as f:
            f.write(out.stdout.decode("utf-8"))

    def output(self):
        return luigi.LocalTarget(Path(self.python_version) / "tested.txt")


class Pipeline(luigi.WrapperTask):
    """Entry point to trigger tests across all supported Python versions."""

    def requires(self):
        """Require RunTests for Python 3.9 through 3.14."""
        for version in ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]:
            yield RunTests(python_version=version)
