"""YAML and Jinja2 processing utilities."""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any, TypeVar
from copy import deepcopy
import yaml

# Type alias for common nested structures
T = TypeVar("T")


def expand_vars(data: dict | list | str) -> dict | list | str:
    """Expand environment variables in strings and nested structures with $$ escaping."""
    if isinstance(data, dict):
        return {k: expand_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [expand_vars(v) for v in data]
    if isinstance(data, str):
        # Use a unique placeholder to protect escaped $$ during expansion
        placeholder = "___SCICD_ESCAPED_DOLLAR___"
        text = data.replace("$$", placeholder)
        text = os.path.expandvars(text)
        return text.replace(placeholder, "$")


def load_yaml(path: str, expand=True) -> dict[str, Any]:
    if not Path(path).exists():
        raise FileNotFoundError(f"No file found at {path}!")
    with open(path, "r", encoding="utf-8") as f:
        out = yaml.safe_load(f)

    if out is None:
        out = {}

    if expand:
        out = expand_vars(out)

    assert isinstance(out, dict)

    return out


def deep_merge(source: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Perform recursive dictionary merge."""
    source = deepcopy(source)
    for key, value in overrides.items():
        if isinstance(value, dict) and value:
            returned = deep_merge(source.get(key, {}), value)
            source[key] = returned
        else:
            source[key] = overrides[key]
    return source


def nest_dict(flat_dict: dict[str, Any], delimiter: str = ".") -> dict[str, Any]:
    """Convert flat dictionary with delimited keys to nested dictionary."""
    nested: dict[str, Any] = {}
    for key, value in flat_dict.items():
        parts = key.split(delimiter)
        current = nested
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                # Handle potential collisions where a key is both a leaf and a branch
                current[part] = {"_value": current[part]}
            current = current[part]
        current[parts[-1]] = value
    return nested
