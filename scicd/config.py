"""
Configuration management system.
"""

import pathlib
import pprint
from importlib import resources

import yaml

from scicd import yamler


def load_config():
    """Resolves project configuration levels."""
    defaults_path = resources.files("scicd.resources").joinpath("defaults.yaml")
    with defaults_path.open("r") as f:
        config_data = yaml.safe_load(f) or {}

    project_path = pathlib.Path.cwd() / "scicd.yaml"
    project_config = (
        yamler.load_yaml(str(project_path)) if project_path.exists() else {}
    )

    return yamler.deep_update(config_data, project_config)


def get_config():
    """Returns project configuration."""
    return load_config()


def get_module_config(module_cfg):
    """Merges module configuration with project defaults."""
    return yamler.deep_update(get_config(), module_cfg)


def show_config():
    """Prints active configuration."""
    pprint.pprint(get_config())
