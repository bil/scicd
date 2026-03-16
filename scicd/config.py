from typing import Optional
from copy import deepcopy
from collections.abc import Mapping
from pprint import pformat

import luigi


def deep_update(source, overrides):
    """
    Performs a recursive dictionary merge.

    Args:
        source (dict): The base dictionary to be updated.
        overrides (dict): The dictionary containing overriding values.

    Returns:
        dict: The updated source dictionary.
    """
    source = deepcopy(source)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and value:
            returned = deep_update(source.get(key, {}), value)
            source[key] = returned
        else:
            source[key] = overrides[key]
    return source


class scicd(luigi.Config):
    """
    Standard Luigi Config to define the [scicd] section and parameter types.
    """

    # CI/CD govenance
    image = luigi.OptionalParameter(default="python:3.10-slim")
    tags = luigi.OptionalListParameter(default=[])
    variables = luigi.OptionalDictParameter(default={})
    retries = luigi.OptionalIntParameter(default=0)
    cpu = luigi.OptionalIntParameter(default=1)
    memory = luigi.OptionalParameter(default="8Gi")

    # Gitlab
    gitlab_url = luigi.OptionalParameter(default="https://gitlab.com")
    gitlab_project = luigi.Parameter()
    gitlab_extras = luigi.OptionalDictParameter(default=None)

    # GCP
    gcp_project = luigi.OptionalParameter(default=None)
    gcp_pubsub_topic = luigi.OptionalParameter(default=None)
    gcp_pubsub_subscription = luigi.OptionalParameter(default=None)

    # Concurrency
    concurrency_method = luigi.OptionalParameter(default="biject")
    concurrency_workers = luigi.OptionalIntParameter(default=1)


class SciCDConfig:
    """
    The Smart Wrapper. Use this in your code.
    It doesn't inherit from luigi.Config to avoid metaclass/singleton issues.
    """

    def __init__(self, family: Optional[str] = None, **runtime_overrides):
        self.family = family
        self.cfg = scicd(**runtime_overrides)
        self.types_dict = dict(scicd.get_params())
        self._cfg = luigi.configuration.get_config()

    def __getattr__(self, name):

        val = getattr(self.cfg, name)
        if self.family is None:
            return val

        task_cfg = self._cfg.get("scicd", self.family, {})

        if name in task_cfg:
            # Parse the raw TOML string into the correct type
            task_val = self.types_dict[name].parse(task_cfg[name])
            # If it's a dict, deep merge
            if isinstance(val, Mapping):
                # Convert FrozenOrderedDict to regular dict for merging
                val = deep_update(dict(val), task_val)
            else:
                val = task_val

        return val

    def to_dict(self) -> dict:
        """Resolves all parameters into a single dictionary."""
        return {name: getattr(self, name) for name in self.types_dict}

    def __repr__(self):
        header = f"<{self.__class__.__name__}(family={self.family})>"
        body = pformat(self.to_dict(), indent=2, width=80)
        return f"{header}\n{body}"
