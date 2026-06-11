# Luigi Examples: Multi

This extends "simple" to run across two execution environments.

To do so, we first must register two executors, which we call `pc` and `pc2` in `scicd_executors.py`.
We can then inject an executor-specific output directory.

Next, we have to move task inputs/outputs between the two execution environments.
Right now, SciCD supports `rclone` for this purpose, and requires specification of an `rclone`-compatible remote store in the `remote_root` key of the `scicd.yaml` `workspace` configuration.
Similarly, `data_root` must also be specified; here, we use an escaped environment variable.
SciCD will then generate the necessary `rclone` calls, as shown in the `.gitlab-ci.yml` output.

This also showcases how `scicd.yaml` can be used as a centralized task configuration, complementing the in-code configuration shown in the "simple" example.
Default task configuration can be specified in the `task` key.
Task-specific overrides can be specified in `task.{task_name}`.

To see an example of more expansive task configuration that specifies resource requests for a Kubernetes cluster, see the "kubernetes" example.
