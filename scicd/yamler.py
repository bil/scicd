"""
YAML and Jinja2 processing with Type Hints.
"""

import os
import re
import pathlib
from typing import Any, Dict, List, TypeVar
from collections.abc import Mapping
from copy import deepcopy

import frontmatter
import yaml
from jinja2 import Environment

# Type alias for common nested structures
T = TypeVar("T")


def yml_suffix(path: str | pathlib.Path) -> str:
    """
    Ensures a path has a valid YAML suffix by checking existence or appending default.
    """
    path = str(path)
    valid_suffixes = [".yml", ".yaml", ".yml.j2", ".yaml.j2"]
    if any(path.endswith(s) for s in valid_suffixes):
        return path

    # Check if the file exists with any of the valid suffixes
    for s in valid_suffixes:
        path_with_suffix = f"{path}{s}"
        if pathlib.Path(path_with_suffix).exists():
            return path_with_suffix

    return path + ".yaml"


def expand_vars(data: T) -> T:
    """
    Recursively expands environment variables in strings.
    """
    if isinstance(data, dict):
        return {k: expand_vars(v) for k, v in data.items()}  # type: ignore
    if isinstance(data, list):
        return [expand_vars(v) for v in data]  # type: ignore
    if isinstance(data, str):
        return os.path.expandvars(data)  # type: ignore
    return data


def find_includes(path: str) -> List[str]:
    """
    Extracts the 'include' list from YAML front-matter.
    """
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        raise FileNotFoundError(f"Include file not found: {path}")

    post = frontmatter.load(path)
    includes = post.get("include", [])
    return includes if isinstance(includes, list) else [includes]


def deep_update(source: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    Performs a recursive dictionary merge.
    """
    source = deepcopy(source)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and value:
            returned = deep_update(source.get(key, {}), value)
            source[key] = returned
        else:
            source[key] = overrides[key]
    return source


def nest_dict(flat_dict: Dict[str, Any], delimiter: str = ".") -> Dict[str, Any]:
    """
    Converts a flat dictionary with delimited keys into a nested dictionary.

    Example:
        >>> nest_dict({"a.b.c": 1, "a.b.d": 2})
        {'a': {'b': {'c': 1, 'd': 2}}}
    """
    nested: Dict[str, Any] = {}
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


def extract_context(path: str, **kwargs: Any) -> Dict[str, Any]:
    """
    Constructs a Jinja2 rendering context by recursively loading includes.
    """
    includes = find_includes(path)
    context: Dict[str, Any] = {}
    for include in includes:
        context = deep_update(context, load_yaml(include))
    context = deep_update(context, kwargs)
    return context


def load_metadata(path: str) -> Dict[str, Any]:
    """
    Retrieves the raw front-matter metadata from a file.
    """
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        return {}
    return frontmatter.load(path).metadata


def render_string(template_str: str, **kwargs: Any) -> str:
    """
    Renders a Jinja2 template string with the given context.
    """
    env = Environment()
    return env.from_string(template_str).render(**kwargs)


def load_yaml(path: str, **kwargs: Any) -> Dict[str, Any]:
    """
    Renders Jinja2, parses YAML, and applies deep inheritance and variable expansion.
    """
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    context = extract_context(path, **kwargs)
    post = frontmatter.load(path)

    env = Environment()
    rendered = env.from_string(post.content).render(context)
    data: Dict[str, Any] = yaml.safe_load(rendered) or {}

    return expand_vars(data)


def slugify(text: str) -> str:
    # Replace anything that isn't a letter, number, or underscore with '_'
    # This handles periods, dashes, spaces, and weird symbols in one pass.
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", text)
    # Collapse multiple underscores (e.g., 'a...b' -> 'a___b' -> 'a_b')
    return re.sub(r"_+", "_", clean).strip("_")
