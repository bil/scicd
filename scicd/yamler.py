"""
YAML and Jinja2 processing engine.
Provides universal environment variable expansion and configuration merging.
"""

import os
import pathlib
from collections.abc import Mapping

import fire
import frontmatter
import yaml
from jinja2 import Environment


def yml_suffix(path):
    """
    Ensures a path has a valid YAML suffix.

    Args:
        path (str|Path): The file path to check.

    Returns:
        str: The path with a guaranteed .yml, .yaml, .yml.j2, or .yaml.j2 suffix.
    """
    path_str = str(path)
    valid_suffixes = [".yml", ".yaml", ".yml.j2", ".yaml.j2"]
    if any(path_str.endswith(s) for s in valid_suffixes):
        return path_str
    return path_str + ".yml.j2"


def expand_vars(data):
    """
    Recursively expands environment variables in strings using os.path.expandvars.

    Args:
        data (any): Dictionary, list, or string to expand.

    Returns:
        any: The data structure with all string values expanded.
    """
    if isinstance(data, dict):
        return {k: expand_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [expand_vars(v) for v in data]
    if isinstance(data, str):
        return os.path.expandvars(data)
    return data


def find_includes(path):
    """
    Extracts the 'include' list from YAML front-matter.

    Args:
        path (str): Path to the YAML file.

    Returns:
        list: List of included file paths.
    """
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        raise FileNotFoundError(f"Include file not found: {path}")
    post = frontmatter.load(path)
    return post.get("include", [])


def deep_update(source, overrides):
    """
    Performs a recursive dictionary merge.

    Args:
        source (dict): The base dictionary to be updated.
        overrides (dict): The dictionary containing overriding values.

    Returns:
        dict: The updated source dictionary.
    """
    for key, value in overrides.items():
        if isinstance(value, Mapping) and value:
            returned = deep_update(source.get(key, {}), value)
            source[key] = returned
        else:
            source[key] = overrides[key]
    return source


def extract_context(path, **kwargs):
    """
    Constructs a Jinja2 rendering context by recursively loading includes.

    Args:
        path (str): Path to the target YAML file.
        **kwargs: Additional variables to inject into the context.

    Returns:
        dict: The consolidated context dictionary.
    """
    includes = find_includes(path)
    context = {}
    for include in includes:
        context = deep_update(context, load_yaml(include))
    context = deep_update(context, kwargs)
    return context


def load_metadata(path):
    """
    Retrieves the raw front-matter metadata from a file.

    Args:
        path (str): Path to the YAML file.

    Returns:
        dict: The metadata dictionary.
    """
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        return {}
    return frontmatter.load(path).metadata


def render_string(template_str, **kwargs):
    """
    Renders a Jinja2 template string with the given context.

    Args:
        template_str (str): The Jinja2 template string.
        **kwargs: Variables for rendering.

    Returns:
        str: The rendered string.
    """
    env = Environment()
    return env.from_string(template_str).render(**kwargs)


def load_yaml(path, **kwargs):
    """
    Renders Jinja2, parses YAML, and applies deep inheritance and variable expansion.

    Args:
        path (str): Path to the YAML file.
        **kwargs: Variables for Jinja2 rendering.

    Returns:
        dict: The fully resolved configuration dictionary.
    """
    path = yml_suffix(path)
    if not pathlib.Path(path).exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    context = extract_context(path, **kwargs)
    post = frontmatter.load(path)

    env = Environment()
    rendered = env.from_string(post.content).render(context)
    data = yaml.safe_load(rendered) or {}

    if "merge" in post.metadata:
        base_path = post.metadata["merge"]
        base_data = load_yaml(base_path, **kwargs)
        data = deep_update(base_data, data)

    return expand_vars(data)


def dump_yaml_with_newlines(data, path, sort_keys=True):
    """
    Serializes a dictionary to YAML with block-level spacing for readability.

    Args:
        data (dict): Data to serialize.
        path (str): Target file path.
        sort_keys (bool): Whether to sort keys alphabetically.
    """
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=sort_keys, indent=2)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    processed = []
    for line in lines:
        if line and not line.startswith(" ") and not line.startswith("-"):
            processed.append("\n" + line)
        else:
            processed.append(line)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(processed)


if __name__ == "__main__":
    fire.Fire()
