"""YAML and Jinja2 processing utilities."""

import os
import re
import pathlib
from typing import Any, TypeVar, Union
from collections.abc import Mapping
from copy import deepcopy

import frontmatter
import yaml
from jinja2 import Environment

# Type alias for common nested structures
T = TypeVar("T")


def yml_suffix(path: Union[str, pathlib.Path]) -> str:
    """Validate and return path with YAML suffix."""
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
    """Expand environment variables in strings and nested structures with $$ escaping."""
    if isinstance(data, dict):
        return {k: expand_vars(v) for k, v in data.items()}  # type: ignore
    if isinstance(data, list):
        return [expand_vars(v) for v in data]  # type: ignore
    if isinstance(data, str):
        # Use a unique placeholder to protect escaped $$ during expansion
        placeholder = "___SCICD_ESCAPED_DOLLAR___"
        text = data.replace("$$", placeholder)
        text = os.path.expandvars(text)
        return text.replace(placeholder, "$")  # type: ignore
    return data


def find_includes(path: str) -> list[str]:
    """Extract 'include' list from YAML front-matter."""
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        raise FileNotFoundError(f"Include file not found: {path}")

    post = frontmatter.load(path)
    includes = post.get("include", [])
    return includes if isinstance(includes, list) else [includes]


def deep_update(source: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Perform recursive dictionary merge."""
    source = deepcopy(source)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and value:
            returned = deep_update(source.get(key, {}), value)
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


def extract_context(path: str, **kwargs: Any) -> dict[str, Any]:
    """Construct Jinja2 context by loading includes."""
    includes = find_includes(path)
    context: dict[str, Any] = {}
    for include in includes:
        context = deep_update(context, load_yaml(include))
    context = deep_update(context, kwargs)
    return context


def load_metadata(path: str) -> dict[str, Any]:
    """Retrieve raw front-matter metadata from file."""
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        return {}
    return frontmatter.load(path).metadata


def render_string(template_str: str, **kwargs: Any) -> str:
    """Render Jinja2 template string."""
    env = Environment()
    return env.from_string(template_str).render(**kwargs)


def load_yaml(path: str, **kwargs: Any) -> dict[str, Any]:
    """Parse YAML after Jinja2 rendering and deep inheritance."""
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    context = extract_context(path, **kwargs)

    post = frontmatter.load(path)

    jinja_env = Environment()
    rendered = jinja_env.from_string(post.content).render(context)
    data: dict[str, Any] = yaml.safe_load(rendered) or {}

    return expand_vars(data)


def slugify(text: str) -> str:
    """Convert text to alphanumeric slug with underscores."""
    # Replace anything that isn't a letter, number, or underscore with '_'
    # This handles periods, dashes, spaces, and weird symbols in one pass.
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", text)
    # Collapse multiple underscores (e.g., 'a...b' -> 'a___b' -> 'a_b')
    return re.sub(r"_+", "_", clean).strip("_")
