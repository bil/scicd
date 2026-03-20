import subprocess
import luigi


class RunTests(luigi.Task):
    """
    A simple Luigi task that executes the pytest suite.

    This task is configured to always run (complete returns False) and
    defines no outputs, ensuring that no files are synced to remote storage.
    """

    def complete(self):
        # Always return False so this task runs every time the CI pipeline executes.
        return False

    def run(self):
        # Execute pytest. subprocess.run with check=True will raise
        # an exception if pytest fails, causing the Luigi task to fail.
        print("SciCD CI: Running pytest suite...")
        subprocess.run(["pytest"], check=True)
        print("SciCD CI: Pytest suite completed successfully.")
