"""
Inner-module execution and concurrency management.
"""

import subprocess
import json
import os
import re
import warnings
from abc import ABC, abstractmethod

from joblib import Parallel, delayed

from scicd import config, module, paths, yamler
from scicd.queue import PubSubManager


def specify(default, overwrite=None, **kwargs):
    """
    Merges base parameters with input-specific regex overrides.

    Args:
        default (dict): Base parameter dictionary.
        overwrite (list, optional): List of regex rules to apply.
        **kwargs: Current task inputs used for matching.

    Returns:
        dict: Final merged parameter dictionary.
    """
    out = default.copy()
    if not overwrite:
        return out
    for kws in overwrite[::-1]:
        spec = kws["input"]
        if all(re.match(v, str(kwargs[k])) for k, v in spec.items()):
            out = yamler.deep_update(out, kws["param"])
    return out


def form_cfg(module_name, **kwargs):
    """
    Resolves the final parameter dictionary for a module instance.

    Args:
        module_name (str): Name of the module.
        **kwargs: Context variables for Jinja2 rendering.

    Returns:
        dict: Resolved configuration dictionary.
    """
    cfg = paths.module_cfg(module_name, **kwargs)
    cfg.setdefault("param", {})
    cfg["param_merged"] = specify(cfg["param"], cfg.get("overwrite"), **kwargs)
    return cfg


def exec_module(module_name, verbose=None, **kwargs):
    """
    Atomic execution unit for a single task instance.
    In CI, automatically extracts inputs from $SCICD_INPUT if kwargs are empty.

    Args:
        module_name (str): Name of the module to execute.
        verbose (bool, optional): Whether to print status messages.
        **kwargs: Key-value pairs defining the task identity.

    Returns:
        any: Output from the module instance's run method.
    """
    instance = module.get_module_instance(module_name, **kwargs)
    module_cfg = form_cfg(module_name, **kwargs)

    if verbose is None:
        verbose = config.get("logging.verbose", default=True, module_cfg=module_cfg)

    if verbose:
        print(f"EXEC {module_name} | {kwargs}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = instance.run(**module_cfg["param_merged"])

    if verbose:
        print(f"DONE {module_name} | {kwargs}")
        print(f"Outputs deposited at: {instance.full_path()}")

    return result


def get_inputs(module_name, module_cfg):
    """
    Retrieves task inputs from static YAML list or dynamic generator.

    Args:
        module_name (str): Name of the module.
        module_cfg (dict): The loaded module configuration.

    Returns:
        list: List of dictionaries defining task inputs.
    """
    gen_cfg = module_cfg.get("input_generator")
    if gen_cfg and "script" in gen_cfg:
        # Just running a script
        cmd_template = gen_cfg["script"]
        if isinstance(cmd_template, list):
            cmd_template = " && ".join(cmd_template)
        cmd = yamler.render_string(cmd_template, **gen_cfg.get("param", {}))
        res = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, check=True
        )
        return json.loads(res.stdout)

    # Check if using Module object (OOP fallback)
    module_cls = module.get_module_class(module_name)
    if hasattr(module_cls, "input_generator"):
        gen_cfg = module_cfg.get("input_generator", {})
        return module_cls.input_generator(**gen_cfg.get("param", {}))

    # Fall back to input kwarg
    return module_cfg.get("input", [{}])


class ModuleManager(ABC):
    """
    Abstract base for managing task execution strategies.
    """

    method = None
    supported_executors = ["local", "gitlab"]

    def __init__(self, module_name):
        """
        Initializes the manager.

        Args:
            module_name (str): Name of the module being managed.
        """
        self.module_name = module_name
        self.module_cfg = paths.module_cfg(module_name)

    @property
    def has_prepare(self):
        """
        Checks if the subclass has implemented a custom prepare method.

        Returns:
            bool: True if prepare is overridden.
        """
        return self.prepare.__func__ is not ModuleManager.prepare

    def prepare(self, inputs):
        """
        Optional setup phase for the execution environment.

        Args:
            inputs (list): Full list of task inputs.
        """

    @abstractmethod
    def dispatch(self, **kwargs):
        """
        Mandatory execution phase implementation.

        Args:
            **kwargs: Method-specific parameters.
        """


class ThreadManager(ModuleManager):
    """
    Intra-environment concurrency using joblib.
    """

    method = "thread"

    def dispatch(self, **kwargs):
        """
        Executes the full input list using local threads or processes.

        Args:
            **kwargs: Must contain 'workers' (int).
        """
        workers = kwargs.get("workers") or 1
        inputs = get_inputs(self.module_name, self.module_cfg)

        # Merge joblib settings with module overrides
        joblib_cfg = config.get("joblib", module_cfg=self.module_cfg)

        print(f"Thread | Parallel: {len(inputs)} tasks | {workers} workers")
        Parallel(n_jobs=workers, **joblib_cfg)(
            delayed(exec_module)(self.module_name, **task) for task in inputs
        )


class MatrixManager(ModuleManager):
    """
    1:1 task mapping using GitLab CI Matrix parallelism.
    """

    method = "matrix"
    supported_executors = ["gitlab"]

    def dispatch(self, **kwargs):
        """
        Executes exactly one task from the $INPUT environment variable.
        """
        exec_module(self.module_name)


class SliceManager(ModuleManager):
    """
    Modulo task distribution using GitLab CI Parallel workers.
    """

    method = "slice"
    supported_executors = ["gitlab"]

    def dispatch(self, **kwargs):
        """
        Resolves the full input list and executes its assigned slice.
        """
        inputs = get_inputs(self.module_name, self.module_cfg)

        total = int(os.environ["CI_NODE_TOTAL"])
        index = int(os.environ["CI_NODE_INDEX"]) - 1
        my_tasks = [t for i, t in enumerate(inputs) if (i % total) == index]

        print(f"Slice | Node {index+1}/{total} | {len(my_tasks)} tasks")
        for task in my_tasks:
            exec_module(self.module_name, **task)


class QueueManager(ModuleManager):
    """
    Distributed coordination using a cloud-based message queue.
    """

    method = "queue"
    supported_executors = ["gitlab"]

    def prepare(self, inputs):
        """
        Populates the cloud topic with all task inputs.

        Args:
            inputs (list): Task inputs to publish.
        """
        gcp_cfg = config.get("gcp", module_cfg=self.module_cfg)
        qm = PubSubManager(
            topic_id=gcp_cfg["pubsub_topic"],
            subscription_id=gcp_cfg["pubsub_subscription"],
        )
        qm.drain_subscription()
        print(f"Queue | Publishing {len(inputs)} tasks...")
        qm.publish_messages(inputs)

    def dispatch(self, **kwargs):
        """
        Continuous worker loop pulling and executing tasks from the queue.
        """
        gcp_cfg = config.get("gcp", module_cfg=self.module_cfg)
        qm = PubSubManager(
            topic_id=gcp_cfg["pubsub_topic"],
            subscription_id=gcp_cfg["pubsub_subscription"],
        )

        print("Queue | Worker active.")
        while True:
            ack_id, data = qm.pull_message(timeout=20)
            if data is None:
                break
            print(f"Queue | Task: {data}")
            qm.ack_message(ack_id)
            exec_module(self.module_name, **data)


def get_manager(method, module_name):
    """
    Factory to instantiate the correct ModuleManager.

    Args:
        method (str): Scaling strategy name.
        module_name (str): Name of the target module.

    Returns:
        ModuleManager: Resolved manager instance.
    """
    manager_map = {
        "thread": ThreadManager,
        "matrix": MatrixManager,
        "slice": SliceManager,
        "queue": QueueManager,
    }
    if method not in manager_map:
        raise ValueError(f"Unknown concurrency method: {method}")
    return manager_map[method](module_name)
