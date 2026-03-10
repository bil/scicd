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


def get(key, default=None, required=False, module_cfg=None):
    """
    Retrieves a configuration value using dot-notation.

    Args:
        key (str): Dot-notation key (e.g., 'storage.output').
        default (any, optional): Value to return if key is missing.
        required (bool): If True, raises ValueError if key is missing.
        module_cfg (dict, optional): Module configuration to merge with base config before lookup.

    Returns:
        any: The configuration value.

    Raises:
        ValueError: If required is True and the key is missing.
    """
    cfg = get_module_config(module_cfg) if module_cfg else get_config()

    parts = key.split(".")
    val = cfg

    try:
        for part in parts:
            val = val[part]
        return val
    except (KeyError, TypeError) as e:
        if required:
            raise ValueError(
                f"Missing required configuration: '{key}'\n"
                f"Check your scicd.yaml or run 'scicd show_config' to verify."
            ) from e
        return default


def show_config(key=None):
    """
    Prints active configuration or a specific value if key is provided.

    Args:
        key (str, optional): Dot-notation key for specific config lookup (e.g., 'path.output').
    """
    if key:
        val = get(key)
        if val is None:
            print(f"Error: Configuration key '{key}' not found.")
        elif isinstance(val, (dict, list)):
            pprint.pprint(val)
        else:
            print(val)
    else:
        pprint.pprint(get_config())
