import subprocess
import luigi
from scicd.frontend.luigi.task import SciTask


class RunTests(SciTask):
    """
    A SciTask that executes the pytest suite across different Python versions.
    """

    python_version = luigi.Parameter(default="3.10")

    @property
    def scicd(self):
        return {
            "image": f"python:{self.python_version}",
            "tags": ["docker"],
        }

    def complete(self):
        # Always return False so this task runs every time the CI pipeline executes.
        return False

    def run(self):
        # Execute pytest. subprocess.run with check=True will raise
        # an exception if pytest fails, causing the Luigi task to fail.
        print(f"SciCD CI: Running pytest suite on Python {self.python_version}...")
        subprocess.run(["pytest"], check=True)
        print("SciCD CI: Pytest suite completed successfully.")
