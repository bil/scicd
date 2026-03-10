"""
Core analysis modules for the Boilerplate framework.
Consolidated into a single file to reduce file bloat.
"""

import os
import time
import random
import pathlib
from scicd.module import Module
from scicd.paths import local_path


class Independent(Module):
    """
    A simple module that runs independently of others.
    """

    def __init__(self, root_path, task_id, path=None):
        self.task_id = task_id
        super().__init__(root_path, path=path)

    def path(self):
        """
        Returns the instance-specific output path suffix.
        """
        return pathlib.Path(f"task_{self.task_id}")

    def run(self):
        """
        Simulates some work.
        """
        print(f"Running independent task {self.task_id}...")
        time.sleep(2)
        output_file = self.full_path() / "result.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Independent task {self.task_id} completed.\n")
        return f"Independent task {self.task_id} done."


class PubsubExample(Module):
    """
    A module that simulates work, suitable for parallel execution.
    """

    def __init__(self, root_path, task_id, sleep_time, path=None):
        self.task_id = task_id
        self.sleep_time = sleep_time
        super().__init__(root_path, path=path)

    def path(self):
        """
        Determines the output path suffix.
        Returns current directory so all tasks write to the same folder.
        """
        return pathlib.Path(".")

    def run(self):
        """
        Simulates a task processed by a worker.
        """
        print(f"Processing task {self.task_id}...")
        print(f"Sleeping for {self.sleep_time} seconds...")
        time.sleep(self.sleep_time)

        output_path = self.full_path()
        # Ensure unique filenames for collision avoidance in the same directory
        output_file = output_path / f"{self.task_id}_result.txt"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Task {self.task_id} completed after {self.sleep_time} seconds.\n")

        return f"Task {self.task_id} done."

    @classmethod
    def post(cls, root_path, filename="final.txt"):
        """
        Concatenates all text files in the output directory.
        """

        print("HOOK PubsubExample.post")
        print("Running post-processing concatenation...")
        target_dir = local_path(root_path)
        output_file = target_dir / filename

        # Ensure directory exists before globbing or writing
        target_dir.mkdir(parents=True, exist_ok=True)

        txt_files = list(target_dir.glob("*_result.txt"))
        print(f"Found {len(txt_files)} files to concatenate.")

        # Always create the output file to avoid downstream FileNotFoundError
        with open(output_file, "w", encoding="utf-8") as outfile:
            for fname in sorted(txt_files):
                with open(fname, "r", encoding="utf-8") as infile:
                    outfile.write(infile.read())
                os.remove(fname)
        print(f"Concatenated content written to {output_file}")
        return str(output_file)

    @classmethod
    def input_generator(cls, num_tasks=20):
        """
        Generates a list of inputs for the queue.
        """
        inputs = []
        for i in range(num_tasks):
            inputs.append({"task_id": i, "sleep_time": random.randint(1, 3)})
        return inputs


class Hello(Module):
    """
    A simple module that greets a user and reads from PubsubExample.
    """

    def __init__(self, root_path, name, path=None):
        self.name = name
        super().__init__(root_path, path=path)

    def path(self):
        """
        Returns the instance-specific output path suffix.
        """
        return pathlib.Path(self.name)

    def run(self, capitalized=True):
        """
        Prints a greeting and writes it to a file in the module's path.
        Also reads output from PubsubExample if available.
        """
        print(f"Hello, {self.name}!")

        # Dependency check: try to read from PubsubExample
        pubsub_path = local_path("queue_demo") / "final.txt"

        if pubsub_path.exists():
            print(f"Found PubsubExample output at {pubsub_path}")
            with open(pubsub_path, "r", encoding="utf-8") as f:
                content = f.read()
                print(f"Content length from PubsubExample: {len(content)}")
        else:
            print("PubsubExample output not found. Skipping dependency logic.")

        greeting = f"Hello, {self.name}!"
        if capitalized:
            greeting = greeting.upper()

        output_file = self.full_path() / "greeting.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(greeting + "\n")

        print(f"Output path: {self.full_path()}")
        return greeting
