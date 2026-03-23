"""Luigi tasks for SciCD internal CI/CD."""

import subprocess
import luigi
from scicd.frontend.luigi.task import SciTask


class RunTests(SciTask):
    """Run the pytest suite on a specific Python version."""

    python_version = luigi.Parameter(default="3.10")

    @property
    def scicd(self):
        """Dynamic configuration to override the container image."""
        return {
            "image": f"python:{self.python_version}",
            "tags": ["bilkube"],
        }

    def run(self):
        """Execute pytest."""
        print(f"SciCD CI: Running pytest suite on Python {self.python_version}...")
        subprocess.run(["pytest"], check=True)
        print("SciCD CI: Pytest suite completed successfully.")
        print(self.output())
        with open(self.output().path, "w", encoding="utf-8") as f:
            f.write("Done!")
    
    @property
    def path(self):
        return self.python_version

    def output(self):
        return luigi.LocalTarget(self.output_path / "tested.txt")


class Pipeline(luigi.WrapperTask):
    """Entry point to trigger tests across all supported Python versions."""

    def requires(self):
        """Require RunTests for Python 3.9 through 3.14."""
        for version in ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]:
            yield RunTests(python_version=version)
