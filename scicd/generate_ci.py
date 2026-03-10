"""
CI/CD configuration generator.
Compiles module DAG into GitLab CI YAML using method-specific templates.
"""

import copy
import json
import os

import yaml

from scicd import config, dag, manager, module, paths, yamler


def format_dict(d):
    """Formats a dictionary into a filesystem-safe string."""
    entries = []
    for k, v in d.items():
        if isinstance(v, dict):
            v = format_dict(v)
        entries.append(f"{k}={v}")
    return "__".join(entries)


def _build_job(module_ci, script, stage, needs=None, rules=None, variables=None):
    """Helper to construct a standardized GitLab CI job dictionary."""
    job = copy.deepcopy(module_ci)
    job.update(
        {"stage": stage, "script": script if isinstance(script, list) else [script]}
    )
    if needs:
        job["needs"] = needs
    if rules:
        job["rules"] = rules
    if variables:
        job["variables"] = yamler.deep_update(job.get("variables", {}), variables)
    return job


def generate_child_yml(module_name, module_cfg):
    """Generates a child pipeline for a module."""
    out_dir = f"{paths.ci_dir()}/child"
    module.make(out_dir)
    out_path = os.path.join(out_dir, f"{module_name}.yml")

    res = config.get_module_config(module_cfg)
    conc = res["concurrency"]["gitlab"]
    m, w = conc["method"], conc["workers"]

    mgr = manager.get_manager(m, module_name)
    module_ci_overrides = module_cfg.get("ci", {})
    dispatch_needs = []

    ci_out = {
        "stages": ["dispatch"],
        "default": res["ci"]["default"],
        "variables": res["ci"]["variables"],
    }
    if "workflow" in res["ci"]:
        ci_out["workflow"] = res["ci"]["workflow"]

    # 1. Handle Preparation Stage
    if mgr.has_prepare:
        ci_out["stages"].insert(0, "prepare")
        ci_out[f"{module_name}:prepare"] = _build_job(
            module_ci_overrides,
            f"scicd prepare_module {module_name} --method={m}",
            "prepare",
        )
        dispatch_needs = [{"job": f"{module_name}:prepare", "optional": True}]

    # 2. Handle Dispatch Pattern
    if m == "matrix":
        list_of_inputs = module_cfg.get("input", [{}])
        for d in list_of_inputs:
            job_name = f"{module_name}:{format_dict(d)}" if d else module_name
            ci_out[job_name] = _build_job(
                module_ci_overrides,
                f"scicd dispatch_module {module_name} --method={m}",
                "dispatch",
                needs=dispatch_needs,
                variables={"SCICD_INPUT": json.dumps(d)},
            )
    elif m == "thread":
        cmd = f"scicd dispatch_module {module_name} --method={m}"
        if w:
            cmd += f" --workers={w}"
        ci_out[f"{module_name}:dispatch"] = _build_job(
            module_ci_overrides, cmd, "dispatch", needs=dispatch_needs
        )
    elif m in ["slice", "queue"]:
        ci_out[f"{module_name}:dispatch"] = _build_job(
            module_ci_overrides,
            f"scicd dispatch_module {module_name} --method={m}",
            "dispatch",
            needs=dispatch_needs,
        )
        ci_out[f"{module_name}:dispatch"]["parallel"] = w

    else:
        raise ValueError(f"Unknown concurrency method for CI: {m}")

    yamler.dump_yaml_with_newlines(ci_out, out_path)


def update_gitlab_ci_stages(ranks):
    """
    Updates root .gitlab-ci.yml with include and topological stages.

    Args:
        ranks (list): Topological sorting of module ranks.
    """
    ci_path, ci_dir = ".gitlab-ci.yml", paths.ci_dir()
    if os.path.exists(ci_path):
        with open(ci_path, "r", encoding="utf-8") as f:
            ci_yml = yaml.safe_load(f) or {}
    else:
        ci_yml = {}
    ci_yml["include"] = [{"local": f"{ci_dir}/pipeline.yml"}]
    new_stages = ["__pull__"]
    for rank in ranks:
        new_stages.extend(rank)
    ci_yml["stages"] = new_stages
    yamler.dump_yaml_with_newlines(ci_yml, ci_path, sort_keys=False)


def generate_ci():
    """
    Main entry point for CI compilation.
    Resolves the full DAG and writes topological pipeline artifacts.
    """
    ranks = dag.get_topological_ranks()
    update_gitlab_ci_stages(ranks)
    ci_dir_name = paths.ci_dir()
    module.clearmake(f"{ci_dir_name}/child")

    cfg = config.get_config()
    main_ci = {"default": cfg["ci"]["default"], "variables": cfg["ci"]["variables"]}
    if "workflow" in cfg["ci"]:
        main_ci["workflow"] = cfg["ci"]["workflow"]

    main_ci["__pull__"] = {
        "stage": "__pull__",
        "script": ["scicd pull_data"],
        "resource_group": "remote_storage",
        "rules": [{"if": "$TRIGGER_PULL == 'true'"}],
    }

    current_dag = dag.get_dag()
    for rank in ranks:
        for module_name in rank:
            mod_cfg = yamler.load_yaml(f"{paths.module_dir()}/{module_name}")
            module_ci_overrides = mod_cfg.get("ci", {})
            generate_child_yml(module_name, mod_cfg)

            run_rule = [
                {
                    "if": f"$REQUESTED_MODULES =~ /.*:{module_name}:.*/ || $TRIGGER_ALL == 'true'"
                }
            ]
            base_needs = [{"job": "__pull__", "optional": True}]
            for dep in current_dag.get(module_name, []):
                base_needs.append({"job": f"{dep}:__push__", "optional": True})

            # A. Pre-hook
            last_job = None
            if "pre" in mod_cfg:
                pre_name = f"{module_name}:pre"
                main_ci[pre_name] = _build_job(
                    yamler.deep_update(
                        copy.deepcopy(module_ci_overrides), mod_cfg["pre"].get("ci", {})
                    ),
                    f"scicd run_pre {module_name}",
                    module_name,
                    needs=base_needs,
                    rules=run_rule,
                )
                last_job = pre_name

            # B. Main Trigger
            trigger_name = f"{module_name}:run"
            trigger_needs = (
                [{"job": last_job, "optional": True}] if last_job else base_needs
            )
            trigger_job = _build_job(
                module_ci_overrides,
                [],
                module_name,
                needs=trigger_needs,
                rules=run_rule,
            )
            trigger_job.pop("script")
            trigger_job["trigger"] = {
                "include": [f"{ci_dir_name}/child/{module_name}.yml"],
                "strategy": "depend",
                "forward": {"pipeline_variables": True},
            }
            main_ci[trigger_name] = trigger_job
            last_job = trigger_name

            # C. Post-hook
            if "post" in mod_cfg:
                post_name = f"{module_name}:post"
                main_ci[post_name] = _build_job(
                    yamler.deep_update(
                        copy.deepcopy(module_ci_overrides),
                        mod_cfg["post"].get("ci", {}),
                    ),
                    f"scicd run_post {module_name}",
                    module_name,
                    needs=[{"job": trigger_name, "optional": True}],
                    rules=run_rule,
                )
                last_job = post_name

            # D. Data Durability Push
            push_name = f"{module_name}:__push__"
            main_ci[push_name] = _build_job(
                module_ci_overrides,
                f"scicd push_data --path={mod_cfg['root_path']} --folders_first=True",
                module_name,
                needs=[{"job": last_job, "optional": True}],
                rules=run_rule,
            )
            main_ci[push_name]["resource_group"] = "remote_storage"

    yamler.dump_yaml_with_newlines(main_ci, f"{ci_dir_name}/pipeline.yml")


if __name__ == "__main__":
    generate_ci()
