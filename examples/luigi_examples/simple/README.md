# Luigi Example: Simple

This is the example shown in the README!
We are running a simple Luigi workflow on a runner tagged `pc` (which could be a Docker executor running on a personal computer).

This example shows how to register your executor with SciCD (`scicd_executors.py`).
This just means providing a function to inject necessary environmnent variables, based on a task's configuration.
These variables might be necessary for resource requests in Slurm/Kubernetes environments.

Our `scicd.yaml` configuration file just injects some Gitlab CI/CD configuration (that appears at the top of the generated `.gitlab-ci.yml`) which installs Luigi.

Here, we design our Luigi workflow to deposit outputs relative to some environment variable.
As such, we just use `scicd_executors.py` to inject this path.
For an example of Kubernetes resource requests, see the `kubernetes` example.

To generate the .gitlab-ci.yml file, run the following from this directory:

```bash
scicd luigi build -m workflow -t CountLetters
```

To get the `dot` file:

```bash
scicd luigi build -m workflow -t CountLetters -b dot
```

This example is extended to run across two execution environments in `multi`.
