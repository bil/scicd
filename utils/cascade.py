"""Cascading configuration utilities"""
from pathlib import Path
from typing import Optional
from scicd.config import DynamicModel
from scicd.yamler import deep_update, load_yaml

def cascading_config(
    file_path: str | Path,
    root_key: Optional[str | list[str]] = None,
    spec: Optional[dict[str, tuple]] = None,
    **match,
) -> DynamicModel:
    """
    Load a YAML file and apply cascading config logic based on regex matching.
    """
    path = Path(filepath)

    if not path.exists():
        return {}

    cfg = load_yaml(str(path))

    # Check root_key was provided
    if root_key:
        if isinstance(root_key, str):
            root_key = root_key.split(".")

        for k in root_key:
            cfg = cfg.get(k, {})

    config = cfg.get("config", {})
    override = cfg.get("override", [])

    return cascade(config, override, spec, **match)


def cascade(
    config: dict,
    override: list,
    spec: Optional[dict[str, tuple]] = None,
    **kwargs,
) -> DynamicModel:
    """Apply regex-based cascading override logic to a config dict."""
    out = config.copy()
    if not override:
        return out

    for rule in override[::-1]:  # top rule has priority
        rule_match = rule.get("match", {})
        rule_config =  rule.get("config", {})
        # Ensure values are matched as strings for regex compatibility
        if all(re.match(str(v), str(kwargs.get(k))) for k, v in rule_match.items()):
            out = deep_update(out, rule_config)
    if spec:
        model_cls = create_model(
            "CascadingConfig", __base__=DynamicModel, **spec
        )
    else:
        model_cls = DynamicModel

    return model_cls.model_validate(out)
