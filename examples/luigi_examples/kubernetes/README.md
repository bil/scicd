# Luigi Examples: Kubernetes

This extends the "multi" example to run `CountLetters` on our Kubernetes cluster, showing an example of handling resource requests.

We register a new executor in `scicd_executors.py` that takes our task configuration and populated Kubernetes environment variables.
These are used by the cluster to provision an appropriate computational node.
