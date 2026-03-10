"""
CLI interface for scicd.
"""

import os
import sys

import fire

from scicd import config, dag, generate_ci, lint, runner, yamler


def main():
    """
    Main entry point for the scicd CLI.
    """
    # Ensure current project directory is in path for loading user modules
    sys.path.insert(0, os.getcwd())

    fire.Fire(
        {
            "show_config": config.show_config,
            "lint_config": lint.lint_config,
            "run_all": runner.run_all,
            "run_module": runner.run_module,
            "run_category": runner.run_category,
            "run_rank": runner.run_rank,
            "run_subgraph": runner.run_subgraph,
            "exec_module": runner.exec_module,
            "prepare_module": runner.prepare_module,
            "dispatch_module": runner.dispatch_module,
            "run_pre": runner.run_pre,
            "run_post": runner.run_post,
            "pull_data": runner.pull_data,
            "push_data": runner.push_data,
            "generate_ci": generate_ci.generate_ci,
            "export_dag": dag.export_dag,
            "load_yaml": yamler.load_yaml,
        }
    )


if __name__ == "__main__":
    main()
