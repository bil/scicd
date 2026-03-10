"""
Module configuration linter and validation engine.
"""

import pathlib
import sys

import yaml
from jinja2 import TemplateError

from scicd import dag, paths, yamler


# Module Configuration Schema (Key: Type)
VALID_KEYS = {
    "src": str,
    "class": str,
    "script": (str, list),
    "root_path": str,
    "path": str,
    "needs": list,
    "input": list,
    "param": dict,
    "overwrite": list,
    "category": str,
    "ci": dict,
    "concurrency": dict,
    "pre": dict,
    "post": dict,
    "input_generator": dict,
    "logging": dict,
    "joblib": dict,
    "gcp": dict,
}

# Infrastructure keys reserved for workspace-level scicd.yaml
INFRA_KEYS = {"internal", "storage", "gitlab"}

# Rules for linter validation
SCHEMA_MANDATORY = {"root_path"}
SCHEMA_EXCLUSIVE = [("src", "script"), ("input", "input_generator")]
SCHEMA_DEPENDENT = {"script": ["path"]}
SCHEMA_FORBIDDEN = {"script": ["class"]}

# Hook-specific constraints
VALID_HOOK_KEYS = {"script", "param", "ci"}
HOOK_NAMES = ["pre", "post", "input_generator"]


def lint_config(*module_names):
    """
    Validates module configurations against framework rules.
    If no names provided, lints all discovered modules.

    Args:
        *module_names: Variadic list of module names to lint.
    """
    targets = list(module_names) if module_names else dag.list_modules()
    errors = []

    for name in targets:
        path = paths.module_yml(name)
        if not pathlib.Path(path).exists():
            errors.append(f"[{name}] File not found: {path}")
            continue

        try:
            # 1. Check Front-matter (Metadata)
            meta = yamler.load_metadata(path)
            if "include" in meta and not isinstance(meta["include"], (str, list)):
                errors.append(f"[{name}] 'include' must be string or list.")
            if "merge" in meta and not isinstance(meta["merge"], str):
                errors.append(f"[{name}] 'merge' must be a string path.")

            # 2. Check Module Body
            body = yamler.load_yaml(path)

            # A. Mandatory Keys
            for key in SCHEMA_MANDATORY:
                if key not in body:
                    errors.append(f"[{name}] Missing mandatory key: '{key}'.")

            # B. Infrastructure Overrides (Forbidden)
            forbidden = [k for k in body if k in INFRA_KEYS]
            if forbidden:
                errors.append(
                    f"[{name}] Forbidden infrastructure override: {forbidden}"
                )

            # C. Key and Type Validation
            for k, v in body.items():
                if k not in VALID_KEYS:
                    errors.append(f"[{name}] Invalid module keyword: '{k}'")
                    continue

                expected_type = VALID_KEYS[k]
                if not isinstance(v, expected_type):
                    if isinstance(expected_type, type):
                        type_names = expected_type.__name__
                    else:
                        type_names = [t.__name__ for t in expected_type]
                    errors.append(
                        f"[{name}] Key '{k}' must be of type {type_names} (got {type(v).__name__})."
                    )

            # D. Mutually Exclusive Keys
            for set_a, set_b in SCHEMA_EXCLUSIVE:
                if set_a in body and set_b in body:
                    errors.append(
                        f"[{name}] Cannot define both '{set_a}' and '{set_b}'."
                    )
                if set_a not in body and set_b not in body:
                    errors.append(
                        f"[{name}] Must define either '{set_a}' or '{set_b}'."
                    )

            # E. Dependent Keys
            for trigger, deps in SCHEMA_DEPENDENT.items():
                if trigger in body:
                    for dep in deps:
                        if dep not in body:
                            errors.append(
                                f"[{name}] Key '{trigger}' requires '{dep}' to be defined."
                            )

            # F. Forbidden Keys (Backend-specific)
            for trigger, forbidden_keys in SCHEMA_FORBIDDEN.items():
                if trigger in body:
                    for f_key in forbidden_keys:
                        if f_key in body:
                            errors.append(
                                f"[{name}] Key '{f_key}' is not allowed when '{trigger}' is used."
                            )

            # G. Hook Constraints (pre/post/input_generator)
            for hook in HOOK_NAMES:
                if hook in body:
                    hcfg = body[hook]
                    if not isinstance(hcfg, dict):
                        errors.append(f"[{name}] '{hook}' hook must be a dict.")
                        continue

                    invalid_hook = [k for k in hcfg if k not in VALID_HOOK_KEYS]
                    if invalid_hook:
                        errors.append(
                            f"[{name}] Invalid key in '{hook}' hook: {invalid_hook}"
                        )

                    if "script" in body:
                        if "script" not in hcfg:
                            errors.append(
                                f"[{name}] Script modules must define 'script' for '{hook}' hook."
                            )

            # H. Overwrite Structure
            if "overwrite" in body:
                for idx, rule in enumerate(body["overwrite"]):
                    if (
                        not isinstance(rule, dict)
                        or "input" not in rule
                        or "param" not in rule
                    ):
                        errors.append(
                            f"[{name}] 'overwrite' rule #{idx} must have 'input' and 'param' dicts."
                        )

        except (yaml.YAMLError, ValueError, TemplateError) as e:
            errors.append(f"[{name}] Configuration error: {str(e)}")
        except Exception as e:
            # Re-raise unexpected system/internal errors
            print(f"[{name} ] ERROR")
            raise e

    if errors:
        print("\n--- CONFIG LINT FAILED ---")
        for err in errors:
            print(f"ERROR: {err}")
        sys.exit(1)
    else:
        print(f"PASS: {len(targets)} modules validated.")
