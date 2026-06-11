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

Let's see a simple example. This is `examples/luigi_examples/simple`.

To get started, you'll have to register your computer as a Docker executor in your Gitlab instance. For instructions on how to do this, check out the [Gitlab documentation](https://docs.gitlab.com/ci/runners/runners_scope/#group-runners).

Now consider the following Luigi workflow in a file called `workflow.py`.
We've added some in-place configuration, but importantly **this is still just Luigi** and you can run it in all the ways Luigi is capable of.

However, taking advantage of CI/CD, we've indicated we want to run both tasks on a runner with the tag `pc` in the `python:3.12` container image.

```python
import os
import luigi

# Modified from: https://luigi.readthedocs.io/en/stable/tasks.html
PATH_OUTPUT = os.environ["PATH_OUTPUT"]


class GenerateWords(luigi.Task):
    # We added this
    scicd = {"image": "python:3.12", "tags": ["pc"]}

    words = luigi.ListParameter(default=("apple", "banana", "grapefruit"))

    def output(self):
        return luigi.LocalTarget(f"{PATH_OUTPUT}/words.txt")

    def run(self):
        # write a dummy list of words to output file
        self.output().makedirs()
        with self.output().open("w") as f:
            for word in self.words:
                f.write(f"{word}\n")


class CountLetters(luigi.Task):
    # We added this
    scicd = {"image": "python:3.12", "tags": ["pc"]}

    def requires(self):
        return GenerateWords()

    def output(self):
        return luigi.LocalTarget(f"{PATH_OUTPUT}/letter_counts.txt")

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
This file will be automatically detected by `scicd`, and gives you a chance to inject environment variables relevant for a specific execution environment.
The method receives a `TaskConfig` object which stores information like the `image`, `tags` and resource requests (e.g. `cpu`).
In Kubernetes or Slurm execution environments, you might want to translate these resources into relevant environment variables.
See `examples/luigi_examples/kubernetes` for more.
For now, we keep it simple and just inject our `PATH_OUTPUT` variable.

```python
from typing import Dict

from scicd.config import TaskConfig
from scicd.executor import register_executor


@register_executor(tags=["pc"])
def pc(cfg: TaskConfig) -> Dict[str, str]:
    return {"PATH_OUTPUT": "/path/to/local/output"}
```

We also want to ensure that `luigi` is installed in the `python:3.12` container.
We can do that by configuring SciCD with a root `scicd.yaml` file.
There's a lot you can do with this file.
Here, we're using the `workspace.cicd` key to just inject arbtrary Gitlab CI/CD boilerplate, but you can also specify task configuration, remote syncing, and more with this file.
See the examples!

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
  - pc
  stage: stage_0
  variables:
    PATH_OUTPUT: /path/to/local/output
  needs: []
  script:
  - PYTHONPATH=. luigi --module luigi_examples.simple.simple GenerateWords --GenerateWords-words='["apple", "banana", "grapefruit"]' --local-scheduler
CountLetters:
  image: python:3.12
  tags:
  - pc
  stage: stage_1
  variables:
    PATH_OUTPUT: /path/to/local/output
  needs:
  - GenerateWords:words=["apple","banana","grapefruit"]
  script:
  - PYTHONPATH=. luigi --module luigi_examples.simple.simple CountLetters --local-scheduler
```

For more guidance, please look at the examples!

## Limitations

While we plan on supporting Github Actions compilation, this has not yet been implemented.

In addition, the transpiler is static and cannot detect dynamic aspects of workflows (like a Luigi task generating additional tasks at runtime).
This means dynamic tasks will run in the same job as the discoverable static parent task, and that highly dynamic workflows will be less amenable to the sort of distributed computation unlocked by Ci/CD.
