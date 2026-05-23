"""Node implementation for CI/CD DAG"""

from __future__ import annotations
import hashlib
from abc import ABC
from typing import Any

from pydantic import BaseModel, model_validator, ConfigDict

from scicd.config import TaskConfig, get_workspace_config
import scicd.yamler
import scicd.adapter
import scicd.remote
import scicd.backend.gitlab
from scicd.executor import get_executor

# def make_cicd_job_name(s: str) -> str:

#     """
#     Convert string to valid GitLab job name.

#     Allows: a-z A-Z 0-9 _ - . /
#     Replaces invalid chars with hyphens.
#     """
#     # Replace invalid characters with hyphens
#     valid = re.sub(r"[^a-zA-Z0-9_.\-/]", "-", s)

#     # Collapse multiple hyphens
#     valid = re.sub(r"-+", "-", valid)

#     # Strip leading/trailing hyphens
#     valid = valid.strip("-")

#     # Ensure not empty
#     if not valid:
#         valid = "job"

#     return valid


class Node(BaseModel, ABC):
    """
    Abstract base class for a node in the SciCD DAG.

    A node represents a logical step in the pipeline. It contains a list of
    adapters (the work to be done) and a set of dependency nodes.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    adapters: list[scicd.adapter.BaseAdapter]
    rank: int
    deps: list[Node]

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        return f"<{cls_name} name='{self.name}' jobs={self.jobs}"

    @property
    def identity(self) -> str:
        return "&".join([adapter.identifier for adapter in self.adapters])

    @property
    def idhash(self) -> str:
        """An 8-character string from the hash of `self.identity`"""
        idhash = hashlib.sha256(self.identity.encode("utf-8")).hexdigest()[:8]
        return idhash

    def __hash__(self) -> int:
        return hash(self.identity)

    def __eq__(self, other: Node) -> bool:
        return self.identity == other.identity

    @property
    def name(self) -> str:
        return self.adapters[0].name

    @property
    def commands(self) -> list[list[str]]:
        wspace = get_workspace_config(self.adapters[0].config_path)
        if self.cfg.concurrency.method == "biject":
            adapter = self.adapters[0]
            out = adapter.setup_commands + adapter.commands + adapter.teardown_commands
            if wspace.remote_root:
                out = (
                    scicd.remote.remote_commands(adapter.inputs, wspace, "pull")
                    + out
                    + scicd.remote.remote_commands(adapter.outputs, wspace, "push")
                )
            out = [out]
            return out
        if self.cfg.concurrency.method == "slice":
            adapter_slices = [
                self.adapters[i :: self.cfg.concurrency.workers]
                for i in range(self.cfg.concurrency.workers)
            ]
            out = []
            for adapter_slice in adapter_slices:
                slice_inputs = []
                slice_outputs = []
                slice_commands = adapter_slice[0].setup_commands
                for adapter in adapter_slice:
                    slice_inputs.extend(adapter.inputs)
                    slice_outputs.extend(adapter.outputs)
                    slice_commands.extend(adapter.commands)
                slice_commands += adapter_slice[0].teardown_commands
                slice_inputs = list(set(slice_inputs))
                slice_outputs = list(set(slice_outputs))
                if wspace.remote_root:
                    slice_commands = (
                        scicd.remote.remote_commands(slice_inputs, wspace, "pull")
                        + slice_commands
                        + scicd.remote.remote_commands(slice_outputs, wspace, "push")
                    )
                out.append(slice_commands)
            return out
        raise NotImplementedError

    @property
    def jobs(self) -> list[str]:
        """CI/CD job names."""
        if self.cfg.concurrency.method == "biject":
            adapter = self.adapters[0]
            name = self.identity
            # 80 character target
            if len(name) > 80:
                name = f"{adapter.name}:{self.idhash}"
            return [name]
        if self.cfg.concurrency.method == "slice":
            out = []
            for w in range(self.cfg.concurrency.workers):
                name = f"{self.adapters[0].name}:worker{w}:{self.idhash[:8]}"
                out.append(name)
            return out
        raise NotImplementedError

    @property
    def needs(self) -> list[str]:
        """Flattened list of unique job dependencies."""
        out = []
        for node in self.deps:
            out.extend(node.jobs)
        return sorted(list(set(out)))

    @model_validator(mode="after")
    def check_name(self) -> Node:
        names = [adapter.name for adapter in self.adapters]
        if len(set(names)) > 1:
            raise ValueError("Detected adapters with different names!")
        return self

    @model_validator(mode="after")
    def check_cfg(self) -> Node:
        cfg_paths = [adapter.config_path for adapter in self.adapters]
        if len(set(cfg_paths)) > 1:
            raise ValueError("Detected adapters with different config paths!")
        cfgs = [adapter.cfg_json for adapter in self.adapters]
        if len(set(cfgs)) > 1:
            raise ValueError("Detected multiple unique task configs!")
        return self

    @property
    def cfg(self) -> TaskConfig:
        return self.adapters[0].cfg

    @property
    def cfg_json(self) -> str:
        return self.adapters[0].cfg_json

    @property
    def executor_vars(self) -> dict:
        out = {}
        if self.cfg.tags:
            executor = get_executor(self.cfg.tags)
            # rich.print(
            #     f"[bold magenta]{self.name}[/bold magenta]:",
            #     f"Matched tags {list(self.cfg.tags)}",
            #     f"to executor [cyan]{executor.name}[/cyan]",
            # )
            executor_vars = executor.func(self.cfg)
            if executor_vars:
                out.update(executor_vars)
        return out

    @model_validator(mode="after")
    def check_adapters(self) -> Node:
        if not self.adapters:
            raise ValueError("Node has no adapters!")
        if (self.cfg.concurrency.method == "biject") and (len(self.adapters) != 1):
            raise ValueError(
                f"Biject concurrency expects 1 adapter per node, received: {len(self.adapters)}."
            )
        if (self.cfg.concurrency.method == "slice") and (
            len(self.adapters) < self.cfg.concurrency.workers
        ):
            n = len(self.adapters)
            m = self.cfg.concurrency.workers
            raise ValueError(f"Slice concurrency received {n} adapters (< {m} workers)")

        return self

    def export(self, backend: str = "gitlab") -> Any:
        if backend == "gitlab":
            return scicd.backend.gitlab.export_node(self)
        else:
            raise NotImplementedError(f"Node export not implemented for {backend}")

    @property
    def dot_label(self) -> str:
        """Generate a label showing the name and parameters."""
        if self.cfg.concurrency.method == "biject":
            out = self.adapters[0].name
            if self.adapters[0].identifier != out:
                out += f" ({self.adapters[0].identifier})"
            return out

        if self.cfg.concurrency.method == "slice":
            label_lines = [self.adapters[0].name]
            for adapter in self.adapters:
                label_lines.append(f"[{adapter.identifier}]")
            return "\\n".join(label_lines)

        raise NotImplementedError


# def get_my_params():
#     params_list = json.loads(os.environ["SCICD_PARAMS"])
#     if "CI_NODE_INDEX" in os.environ: # gitlab
#         worker_index = int(os.environ["CI_NODE_INDEX"]) - 1
#         worker_total = int(os.environ["CI_NODE_TOTAL"])
#     else:
#         raise NotImplementedError
#     my_params = [
#         params
#         for i, params in enumerate(params_list)
#         if i % worker_total == worker_index
#     ]
#     return my_params
