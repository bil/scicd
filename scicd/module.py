"""
Base Class for analysis modules.
Handles path management, input validation, and resource fetching.
"""

import importlib
import os
import pathlib
import shutil
import subprocess
from abc import ABC, abstractmethod

import requests

from scicd import config, paths, yamler


class Module(ABC):
    """
    Abstract base for analysis modules.
    Identity (inputs) determines path. Behavior (params) determines run logic.
    Subclasses must accept 'root_path' as their first __init__ argument.
    """

    def __init__(self, root_path, path=None):
        """
        Initializes the module instance.

        Args:
            root_path (str): The base directory for this module's results.
            path (str, optional): An explicit path override from configuration.
        """
        self.root_path = root_path
        self._provided_path = path
        make(self.full_path())

    def path(self):
        """
        Returns the instance-specific path suffix. Defaults to empty Path.
        Child classes can override this, but explicit paths will take precedence.

        Returns:
            pathlib.Path: The subdirectory relative to the root_path.
        """
        return pathlib.Path()

    def full_root_path(self):
        """
        Returns the absolute root directory for this module.

        Returns:
            pathlib.Path: The resolved absolute root path.
        """
        return paths.local_path(self.root_path)

    @abstractmethod
    def run(self):
        """
        Main execution logic for the module. Implementation required in subclasses.
        """

    def full_path(self):
        """
        Returns the absolute directory for this specific module instance.
        If an explicit path was provided via configuration, it overrides any
        custom path() logic.

        Returns:
            pathlib.Path: The resolved absolute instance path.
        """
        suffix = (
            pathlib.Path(self._provided_path)
            if self._provided_path is not None
            else self.path()
        )
        return self.full_root_path() / suffix

    def get_file(self, filename):
        """
        Retrieves a module resource. Checks local disk, then falls back to deposition_url.

        Args:
            filename (str): The name of the file to retrieve.

        Returns:
            pathlib.Path: The path to the verified local file.

        Raises:
            FileNotFoundError: If the file is missing locally and fetch fails.
        """
        local_file = self.full_path() / filename
        if local_file.exists():
            return local_file

        deposition_url = config.get("storage.deposition_url")

        if deposition_url:
            print(f"Resource missing: {filename}. Fetching from {deposition_url}...")
            if self._fetch_file(filename, deposition_url):
                return local_file
            raise FileNotFoundError(
                f"Resource '{filename}' not found at {deposition_url} for {self.__class__.__name__}"
            )

        raise FileNotFoundError(
            f"Resource '{filename}' missing locally for {self.__class__.__name__}.\n"
            f"No 'storage.deposition_url' configured for remote fetching.\n"
            f"Run {self.__class__.__name__} to generate this file."
        )

    def _fetch_file(self, filename, base_url):
        """
        Downloads a file from an HTTP endpoint.

        Args:
            filename (str): Target filename.
            base_url (str): Source base URL.

        Returns:
            bool: True if successful, False otherwise.
        """
        clean_base = base_url.rstrip("/")
        path_suffix = pathlib.Path(self.root_path) / self.path() / filename
        url = f"{clean_base}/{path_suffix}"

        target_path = self.full_path() / filename
        make(target_path.parent)

        try:
            print(f"GET {url}")
            response = requests.get(url, stream=True, timeout=(10, 30))
            response.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except requests.RequestException as e:
            print(f"Fetch failed: {e}")
            return False


def make(path):
    """
    Ensures a directory exists.

    Args:
        path (str|Path): Target directory path.
    """
    pathlib.Path(path).mkdir(parents=True, exist_ok=True)


def clearmake(path, keepdir=True):
    """
    Recursively deletes a directory and optionally recreates it.

    Args:
        path (str|Path): Target directory.
        keepdir (bool): If True, recreates the directory after deletion.
    """
    path = pathlib.Path(path)
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    if keepdir:
        make(path)


def get_root_path(module_name):
    """
    Retrieves the absolute root path for a named module.

    Args:
        module_name (str): Name of the module.

    Returns:
        pathlib.Path: The absolute root path.
    """
    cfg = paths.module_cfg(module_name)
    return paths.local_path(cfg["root_path"])


def get_path(module_name, **kwargs):
    """
    Retrieves the absolute instance path for a named module and specific inputs.

    Args:
        module_name (str): Module name.
        **kwargs: Task inputs defining the instance identity.

    Returns:
        pathlib.Path: The absolute instance path.
    """
    return get_module_instance(module_name, **kwargs).full_path()


class ScriptModule(Module):
    """
    Adapter for executing generic bash/R/CLI scripts.
    Handles path rendering via Jinja2 and sets environment variables.
    """

    def __init__(self, root_path, cfg=None, **kwargs):
        self.cfg = cfg or {}
        self.inputs = kwargs
        super().__init__(root_path)

    def path(self):
        """
        Renders the output path using the YAML template.
        """
        template = self.cfg.get("path", "")
        return pathlib.Path(yamler.render_string(template, **self.inputs))

    def run(self, **params):
        """
        Executes the script commands sequentially.
        """
        env = os.environ.copy()
        env["SCICD_OUT_DIR"] = str(self.full_path())
        for k, v in self.inputs.items():
            env[f"SCICD_INPUT_{k.upper()}"] = str(v)
        for k, v in params.items():
            env[f"SCICD_PARAM_{k.upper()}"] = str(v)

        context = {**self.inputs, **params, "SCICD_OUT_DIR": str(self.full_path())}

        commands = self.cfg.get("script", [])
        if isinstance(commands, str):
            commands = [commands]

        for cmd_template in commands:
            cmd = yamler.render_string(cmd_template, **context)
            print(f"Running: {cmd}")
            subprocess.run(
                cmd, shell=True, env=env, cwd=str(self.full_path()), check=True
            )


def get_module_class(module_name):
    """
    Dynamically loads the Module class associated with a configuration.

    Args:
        module_name (str): Module name.

    Returns:
        class: The Python class inherited from Module.
    """
    cfg = paths.module_cfg(module_name)
    if "script" in cfg:
        return ScriptModule
    mod = importlib.import_module(cfg["src"])
    return getattr(mod, cfg.get("class", module_name))


def get_module_instance(module_name, **kwargs):
    """
    Instantiates a module with arguments, automatically injecting the correct root_path.

    Args:
        module_name (str): Module name.
        **kwargs: Task inputs.

    Returns:
        instance (Module): An instance of the module class.
    """
    cfg = paths.module_cfg(module_name, **kwargs)
    kwargs["root_path"] = cfg["root_path"]

    if "script" in cfg:
        return ScriptModule(cfg=cfg, **kwargs)

    if "path" in cfg:
        kwargs["path"] = yamler.render_string(cfg["path"], **kwargs)

    return get_module_class(module_name)(**kwargs)


def module_root_clearmake(module_name):
    """
    Resets the root results directory for a specific module type.

    Args:
        module_name (str): Module name.
    """
    clearmake(get_root_path(module_name))


def require(local_vars, *keys):
    """
    Enforces the presence of mandatory parameters in local scope or kwargs.

    Args:
        local_vars (dict): Typically locals().
        *keys: Required parameter names.

    Raises:
        ValueError: If a required key is missing.
    """
    for k in keys:
        if local_vars.get(k) is None and local_vars.get("kwargs", {}).get(k) is None:
            raise ValueError(f"Missing parameter: '{k}'")
