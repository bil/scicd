# SciCD

WARNING: this package is in alpha and is unstable, breaking changes are to be expected

## What is it?

SciCD executes scientific workflows as CI/CD pipelines.

To do so, the package transpiles locally executable workflows to CI/CD pipelines

Supported workfow languages:

- [Luigi](https://github.com/spotify/luigi)
- [GNU Make](https://www.gnu.org/software/make/)

Supported CI/CD platforms:

- [Gitlab](https://about.gitlab.com/)

## Installation

Give the following a shot:

```bash
pip install scicd
```

## Why would I want that?

**Scalability**

- CI/CD schedulers can distribute jobs across computing environments, letting you preprocess on a Slurm cluster, analyze on a cloud Kubernetes cluster, and visualize on your laptop.
  Just deploy the open-source `gitlab-runner` in your computing environments of choice.
  SciCD syncs workflow outputs across environments by using an `rclone`-compatible remote store.

**Reproducibility**

- CI/CD execution is containerized and tied to version control.
  Every exeucution is reproducible.

**Portability**

- By abstracting at-scale execution to CI/CD, workflow repositories remain lightweight and locally executable.

## How does it work?

Let's see a simple example.

To get started, you'll have to register your laptop as a Docker executor in your Gitlab instance. For instructions on how to do this, check out the [Gitlab documentation](https://docs.gitlab.com/ci/runners/runners_scope/#group-runners).

Now consider the following Luigi workflow in a file called `workflow.py`.
We've added some in-place configuration, but importantly **this is still just Luigi** and you can run it in all the ways Luigi is capable of.

However, taking advantage of CI/CD, we've indicated we want to run both tasks on a runner with the tag `my-laptop` in the `python:3.12` container image.

```python
import os
import luigi

# Modified from: https://luigi.readthedocs.io/en/stable/tasks.html
PATH_OUTPUT = os.environ["PATH_OUTPUT"]


class GenerateWords(luigi.Task):
    # We added this
    scicd = {"image": "python:3.12", "tags": ["my-laptop"]}

    words = luigi.ListParameter(default=("apple", "banana", "grapefruit"))

    def output(self):
        return luigi.LocalTarget(f"{PATH_OUTPUT}/tmp/words.txt")

    def run(self):
        # write a dummy list of words to output file
        self.output().makedirs()
        with self.output().open("w") as f:
            for word in self.words:
                f.write(f"{word}\n")


class CountLetters(luigi.Task):
    # We added this
    scicd = {"image": "python:3.12", "tags": ["my-laptop"]}

    def requires(self):
        return GenerateWords()

    def output(self):
        return luigi.LocalTarget(f"{PATH_OUTPUT}/tmp/letter_counts.txt")

    def run(self):

        # read in file as list
        with self.input().open("r") as infile:
            words = infile.read().splitlines()

        # write each word to output file with its corresponding letter count
        self.output().makedirs()
        with self.output().open("w") as outfile:
            for word in words:
                outfile.write(
                    "{word} | {letter_count}\n".format(
                        word=word, letter_count=len(word)
                    )
                )
```

You'll also notice we use an environment variable as the base directory for our outputs.
This is a desirable pattern so you can set different outputs paths depending on where the code is executing.
We can set executor-specific environment variables with SciCD by adding a root file called `scicd_executors.py`.

```python
from typing import Dict

from scicd.config import TaskConfig
from scicd.executor import register_executor


@register_executor(tags=["my-laptop"])
def my_laptop(cfg: TaskConfig) -> Dict[str, str]:
    return {"PATH_OUTPUT": "/path/to/local/output"}
```

We also want to ensure that `luigi` is installed in the `python:3.12` container.
We can do that by configuring SciCD with a root `scicd.yaml` file.

```yaml
workspace:
  cicd:
    # This is Gitlab syntax
    default:
      before_script:
        - pip install luigi
```

Now we're ready to convert this workflow to a `.gitlab-ci.yml` file!

```bash
scicd luigi build --module workflow --task CountLetters --backend gitlab
```

Out comes the following:

```yaml
default:
  before_script:
  - pip install luigi
stages:
- stage_0
- stage_1
GenerateWords:words=["apple","banana","grapefruit"]:
  image: python:3.12
  tags:
  - my-laptop
  stage: stage_0
  variables:
    PATH_OUTPUT: /scratch/tmp/worm
  needs: []
  script:
  - PYTHONPATH=. luigi --module luigi_examples.simple.simple GenerateWords --GenerateWords-words='["apple", "banana", "grapefruit"]' --local-scheduler
CountLetters:
  image: python:3.12
  tags:
  - my-laptop
  stage: stage_1
  variables:
    PATH_OUTPUT: /scratch/tmp/worm
  needs:
  - GenerateWords:words=["apple","banana","grapefruit"]
  script:
  - PYTHONPATH=. luigi --module luigi_examples.simple.simple CountLetters --local-scheduler
```
