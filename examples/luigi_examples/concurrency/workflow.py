import os
import json
from pathlib import Path

import luigi
import numpy as np


class NumberID:
    n = luigi.IntParameter()


def get_path(path: str) -> str:
    path = os.path.join(os.environ["PATH_OUTPUT"], path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


class RandomNumbers(luigi.Task, NumberID):
    def run(self):
        numbers = [np.random.random() for _ in range(self.n)]
        with open(self.output().path, "w", encoding="utf-8") as f:
            json.dump(numbers, f)

    def output(self):
        return luigi.LocalTarget(get_path(f"concurrency/{self.n}_numbers.json"))


class ReportNumber(luigi.Task, NumberID):
    scicd = {"concurrency.method": "slice", "concurrency.workers": 3}

    index = luigi.IntParameter()

    def requires(self):
        return self.clone(RandomNumbers)

    def run(self):
        with open(self.input().path, "r", encoding="utf-8") as f:
            numbers = json.load(f)

        selected_number = numbers[self.index]
        with open(self.output().path, "w", encoding="utf-8") as f:
            f.write(f"Selected: {selected_number}")

    def output(self):
        return luigi.LocalTarget(get_path(f"concurrency/num_{self.index}.txt"))


class All(luigi.WrapperTask, NumberID):
    n = luigi.IntParameter(default=10)

    def requires(self):
        # We want to fit 10 'ReportNumber' tasks into our queue
        for i in range(self.n):
            yield self.clone(ReportNumber, index=i)
