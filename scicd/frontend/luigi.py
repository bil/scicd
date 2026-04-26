"""Luigi frontend implementation."""

from __future__ import annotations
import importlib
import shlex


from typing import Any, Optional, Annotated

import luigi
from luigi.cmdline_parser import CmdlineParser
from cyclopts import App, Parameter


import scicd.config

# from scicd.frontend.luigi import task as luigi_task
from scicd.yamler import nest_dict, deep_update
from scicd.adapter import BaseAdapter
from scicd.config import DynamicModel, get_task_config
import scicd.remote
import scicd.dag

app = App(name="luigi", help="Luigi sub-command")


def _normalize_luigi_resources(resources: dict[str, int]) -> dict[str, Any]:
    """Luigi resources are integers."""
    normalized: dict[str, Any] = {}

    # CPU: direct pass-through (integer = cores)
    if "cpu" in resources:
        normalized["cpu"] = resources["cpu"]

    # Memory: assume MB
    for mem_key in ["memory", "disk"]:
        if mem_key in resources:
            mem = resources[mem_key]
            normalized[mem_key] = f"{mem}M"

    # Time/Timeout: assume minutes
    for time_key in ["time", "timeout"]:
        if time_key in resources:
            time_val = resources[time_key]
            # Assume minutes
            normalized["max_duration"] = f"{time_val}m"

    # GPU: direct pass-through if present
    if "gpu" in resources:
        normalized["gpu"] = resources["gpu"]

    if "retry" in resources:
        normalized["retry"] = resources["retry"]

    return normalized


def get_task_overrides(task: luigi.Task) -> scicd.config.TaskConfig:
    """Extract and resolve TaskConfig for a Luigi task instance."""
    overrides: dict[str, Any] = {}

    # Luigi native resources() (dict of integers)
    resources = getattr(task, "resources", {})
    if isinstance(resources, dict):
        overrides = deep_update(
            overrides, _normalize_luigi_resources(resources)
        )

    if task.retry_count:
        overrides["retry"] = int(task.retry_count)
    if task.worker_timeout:  # in seconds
        overrides["max_duration"] = scicd.config.TaskConfig.validate_time(
            int(task.worker_timeout / 60)
        )

    # `scicd` dict attribute (highest priority)
    if hasattr(task, "scicd"):
        scicd_attr = getattr(task, "scicd")
        if not isinstance(scicd_attr, dict):
            raise ValueError(
                "`scicd` attribute on luigi tasks should be a dict!"
            )
        scicd_attr = nest_dict(scicd_attr)
        overrides = deep_update(overrides, scicd_attr)

    return overrides


class LuigiAdapter(BaseAdapter):
    """Adapter for transforming Luigi tasks into DAG nodes."""

    def __init__(
        self, work: luigi.Task, config_path: Optional[str] = None
    ) -> None:
        super().__init__(work)

    @property
    def name(self) -> str:
        """Return Luigi task family name."""
        return self.work.task_family

    @property
    def identifier(self) -> str:
        """Unique identifier from task family and params."""
        out = self.name
        params = self.work.to_str_params(only_significant=True)
        if params:
            params_str = ":".join([f"{k}={v}" for k, v in params.items()])
            out = f"{out}:{params_str}"  # [:64]
        out = out.replace(" ", "")
        return out

    @property
    def params(self) -> DynamicModel:
        """Return raw task parameters as a serializable Pydantic model."""
        # param_kwargs contains the actual Python types (int, bool, etc.)
        # whereas to_str_params() forces everything to a string.
        all_params = self.work.param_kwargs

        # Filter for only significant parameters
        sig_names = set(self.work.get_param_names())
        params = {k: v for k, v in all_params.items() if k in sig_names}

        return DynamicModel.model_validate(params)

    @property
    def cfg(self) -> scicd.config.TaskConfig:
        """Return resolved TaskConfig for the Luigi task."""
        overrides = get_task_overrides(self.work)
        return get_task_config(self.name, self.config_path, **overrides)

    @property
    def module(self) -> str:
        """Name of task module"""
        return self.work.__class__.__module__

    @property
    def commands(self) -> list[str]:
        """Generate safe shell commands with properly escaped arguments."""
        # Build CLI parameters with proper escaping
        cli_params = []
        for k, v in self.work.to_str_params().items():
            # Use shlex.quote to safely escape each value
            param_name = f"--{self.name}-{k}"
            param_value = shlex.quote(str(v))
            cli_params.append(f"{param_name}={param_value}")

        # Escape module name as well (in case it comes from user input)
        safe_module = shlex.quote(self.module)
        safe_task_name = shlex.quote(self.name)

        # Build command with escaped components
        cmd_parts = [
            "PYTHONPATH=.",
            "luigi",
            "--module",
            safe_module,
            safe_task_name,
            *cli_params,
            "--local-scheduler",
        ]

        # Join with spaces (already quoted, so safe)
        cmd = " ".join(cmd_parts)
        return [cmd]

    # @property
    # def commands(self) -> list[str]:
    #     # out = ["export PYTHONPATH=."]
    #     out = []
    #     cli_prms = [f"--{self.name}-{k}={v}" for k, v in self.work.to_str_params().items()]
    #     cmd = f"PYTHONPATH=. luigi --module {self.module} {self.name} {' '.join(cli_prms)} --local-scheduler"
    #     out.append(cmd)
    #     return out

    # def command_biject(self, backend: str) -> list[str]:
    #     """Command to run luigi task in biject node environment"""
    #     cmd = (
    #         f"scicd-luigi run --backend {backend} --module {self.module} "
    #         f"--task {self.name}"
    #     )
    #     cli_prms = [f"--{self.name}-{k}={v}" for k, v in self.work.to_str_params()]

    #     cmd = (
    #         f"luigi run --module {self.module} {self.name}"
    #     return [cmd]

    # def command_slice(self, backend: str) -> list[str]:
    #     """Command to run luigi task in Slice node environment"""
    #     cmd = (
    #         f"scicd-luigi run-slice --backend {backend} --module {self.module} "
    #         f"--task {self.name}"
    #     )
    #     return [cmd]

    @property
    def inputs(self) -> list[str]:
        """Input file strings"""
        out = []
        for dep in luigi.task.flatten(self.work.requires()):
            for ot in luigi.task.flatten(dep.output()):
                if hasattr(ot, "path"):
                    path = scicd.remote.get_relpath(ot.path, self.config_path)
                    out.append(path)
        return out

    @property
    def outputs(self) -> list[str]:
        """Output file strings"""
        out = []
        for ot in luigi.task.flatten(self.work.output()):
            if hasattr(ot, "path"):
                path = scicd.remote.get_relpath(ot.path, self.config_path)
                out.append(path)
        return out

    # def run(self) -> None:
    #     """Direct local build of task"""
    #     _run([self.work])

    @property
    def deps(self) -> list[LuigiAdapter]:
        """Return task deps as adapters"""
        task_deps = luigi.task.flatten(self.work.requires())
        return [LuigiAdapter(task) for task in task_deps]


def load_luigi_task(module: str, task: str, **kwargs) -> luigi.Task:
    """
    Get Luigi task instance using CLI parser.

    This can take kwargs of the form `param=val` or `task-param=val'.
    """
    cmdline_args = ["--module", module, task]
    for key, val in kwargs.items():
        cmdline_args.extend([f"--{key}", str(val)])

    importlib.import_module(module)
    with CmdlineParser.global_instance(cmdline_args) as cp:
        task = cp.get_task_obj()

    return task


@app.command()
def build(
    module: Annotated[str, Parameter(alias="-m")],
    task: Annotated[str, Parameter(alias="-t")],
    config_path: Annotated[Optional[str], Parameter(alias="-c")] = None,
    backend: Annotated[str, Parameter(alias="-b")] = "gitlab",
    file_path: Annotated[Optional[str], Parameter(alias="-o")] = None,
    **kwargs,
) -> None:
    target_task = load_luigi_task(module, task, **kwargs)
    target_adapter = LuigiAdapter(target_task, config_path)
    dag = scicd.dag.build(target_adapter)
    dag.export(backend, file_path)
    return


# def _run(tasks: list[luigi.Task]):
#     luigi.build(tasks, local_scheduler=True)


# @app.command()
# def run_slice(module: str, task: str):
#     my_params = get_my_params()
#     tasks = [load_luigi_task(module, task, **p) for p in my_params]
#     _run(tasks)


# @app.command()
# def run(
#     module: str, task: str
# ):
#     params = json.loads(os.environ["SCICD_PARAMS"])[0]
#     task = load_luigi_task(module, task, **params)
#     _run([task])


if __name__ == "__main__":
    app()
