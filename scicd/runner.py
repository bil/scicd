"""
Orchestration engine for DAG traversal and task dispatching.
"""

import os
import subprocess
import importlib

from abc import ABC, abstractmethod

import gitlab
from dotenv import load_dotenv

from scicd import config, dag, manager, module, paths, yamler
from scicd.generate_ci import generate_ci

load_dotenv()


def pull_data(path=".", transfers=10):
    """
    Syncs project data from remote storage to local filesystem.

    Args:
        path (str): Sub-path to pull (relative to project root).
        transfers (int): Parallel transfer count for rclone.
    """
    source = paths.remote_path(path)
    dest = paths.local_path(path)
    print(f"PULL {source} -> {dest}")
    try:
        rclone_sync(str(source), str(dest), transfers=transfers)
    except subprocess.CalledProcessError:
        print("WARN Remote directory missing. Skipping.")


def push_data(path=".", folders_first=True, transfers=10):
    """
    Syncs project data from local filesystem to remote storage.

    Args:
        path (str): Sub-path to push (relative to project root).
        folders_first (bool): If True, syncs directory structure before files.
        transfers (int): Parallel transfer count for rclone.
    """
    dest = paths.remote_path(path)
    source = paths.local_path(path)
    print(f"PUSH {source} -> {dest}")
    rclone_sync(
        str(source), str(dest), folders_first=folders_first, transfers=transfers
    )


def rclone_sync(source, dest, folders_first=True, transfers=10):
    """
    Performs recursive directory synchronization using rclone.

    Args:
        source (str): Source directory.
        dest (str): Destination directory.
        folders_first (bool): Sync structure before data.
        transfers (int): Parallel worker count.
    """
    if folders_first:
        subprocess.run(
            ["rclone", "copy", source, dest, "--filter", "+ */", "--filter", "- *"],
            check=True,
            capture_output=True,
        )
    cmd = ["rclone", "sync", source, dest, "-P", "--transfers", str(transfers)]
    subprocess.run(cmd, check=True)


def run_pipeline(
    requested_modules=None,
    trigger_all=False,
    trigger_pull=True,
    runner=None,
    branch=None,
):
    """
    Triggers a child pipeline via the GitLab API.

    Args:
        requested_modules (str, optional): Regex for module filtering.
        trigger_all (bool): Ignores filtering if True.
        trigger_pull (bool): Executes __pull__ stage if True.
        runner (str, optional): GitLab runner hardware tag.
        branch (str, optional): Target git branch.
    """
    dotenv_path = os.path.join(os.getcwd(), ".env")
    load_dotenv(dotenv_path, override=True)
    cfg = config.get_config()["gitlab"]
    pat = os.getenv("GITLAB_PAT")
    if not pat:
        raise RuntimeError("Missing 'GITLAB_PAT' in environment or .env file.")

    client = gitlab.Gitlab(cfg["url"], private_token=pat)
    project = client.projects.get(cfg["project"])

    branch = branch or paths.get_branch()
    if not branch:
        raise RuntimeError("Git branch required for CI triggering.")

    variables = []
    if requested_modules:
        variables.append({"key": "REQUESTED_MODULES", "value": requested_modules})
    if trigger_all:
        variables.append({"key": "TRIGGER_ALL", "value": "true"})

    pull_val = "true" if str(trigger_pull).lower() == "true" else "false"
    variables.append({"key": "TRIGGER_PULL", "value": pull_val})

    if runner:
        variables.append({"key": "RUNNER", "value": runner})

    p = project.pipelines.create({"ref": branch, "variables": variables})
    print(f"PIPE {p.id} ({branch}) | {requested_modules or 'ALL'}")


def git_push(message="new"):
    """
    Syncs repository state with remote origin.

    Args:
        message (str): Commit message.
    """
    subprocess.run(["git", "add", "."], check=False)
    subprocess.run(["git", "commit", "-m", message], check=False)
    subprocess.run(["git", "push"], check=False)


class Runner(ABC):
    """
    Interface for orchestration environments.
    """

    name = None

    @abstractmethod
    def run_module(self, *module_names, workers=None, method=None):
        """Executes modules by name."""

    @abstractmethod
    def run_rank(self, *module_names, workers=None, method=None):
        """Executes forward-slice from module rank."""

    @abstractmethod
    def run_subgraph(self, *module_names, workers=None, method=None):
        """Executes module and its descendants."""

    @abstractmethod
    def run_category(self, *category_names, workers=None, method=None):
        """Executes all modules in semantic categories."""

    @abstractmethod
    def run_all(self, workers=None, method=None):
        """Executes full DAG."""


class LocalRunner(Runner):
    """
    Initiates execution on local machine.
    """

    name = "local"

    def run_module(self, *module_names, workers=None, method=None):
        """
        Sequentially executes atomic steps for each module.

        Args:
            *module_names: Modules to execute.
            workers (int, optional): Parallel jobs override.
            method (str, optional): Strategy override.
        """
        for name in module_names:
            print(f"--- {name} ({self.name}) ---")

            module_dir = paths.module_dir()
            module_cfg = yamler.load_yaml(f"{module_dir}/{name}.yml.j2")
            res = config.get_module_config(module_cfg)
            conc = res["concurrency"][self.name]

            m = method or conc["method"]
            w = workers or conc["workers"]

            mgr = manager.get_manager(m, name)
            if self.name not in mgr.supported_executors:
                raise RuntimeError(
                    f"Method '{m}' not supported by '{self.name}' runner.\n"
                    f"Supported executors: {mgr.supported_executors}"
                )

            run_pre(name)
            prepare_module(name, method=m)
            dispatch_module(name, method=m, workers=w)
            run_post(name)

    def run_rank(self, *module_names, workers=None, method=None):
        """Executes modules starting from earliest target rank."""
        ranks = dag.get_topological_ranks()
        indices = [
            next(i for i, r in enumerate(ranks) if name in r) for name in module_names
        ]
        selected = [m for r in ranks[min(indices) :] for m in r]
        self.run_module(*selected, workers=workers, method=method)

    def run_subgraph(self, *module_names, workers=None, method=None):
        """Executes descendants of target modules."""
        selected = dag.get_subgraph(list(module_names))
        for r in dag.get_topological_ranks():
            sub = [m for m in r if m in selected]
            if sub:
                self.run_module(*sub, workers=workers, method=method)

    def run_category(self, *category_names, workers=None, method=None):
        """Executes modules sharing semantic tags."""
        cat_map = dag.get_category_map()
        targets = set()
        for name in category_names:
            targets.update(cat_map.get(name, []))
        for r in dag.get_topological_ranks():
            sub = [m for m in r if m in targets]
            if sub:
                self.run_module(*sub, workers=workers, method=method)

    def run_all(self, workers=None, method=None):
        """Executes discovered DAG."""
        print("\n>>> STARTING LOCAL DAG EXECUTION <<<")
        self.run_subgraph(*dag.list_modules(), workers=workers, method=method)
        print("\n>>> DAG EXECUTION COMPLETE <<<")


class GitLabRunner(Runner):
    """
    Triggers pipelines in GitLab.
    """

    name = "gitlab"

    def __init__(self, pull=True, runner=None, branch=None):
        """
        Initializes the trigger.

        Args:
            pull (bool): Executes __pull__ stage if True.
            runner (str, optional): GitLab runner hardware tag.
            branch (str, optional): Target git branch.
        """
        self.pull = pull
        self.runner = runner
        self.branch = branch

    def _trigger(self, requested_modules=None, trigger_all=False):
        """Compiles, pushes, and triggers remote pipeline."""
        generate_ci()
        git_push()
        run_pipeline(
            requested_modules=requested_modules,
            trigger_all=trigger_all,
            trigger_pull=self.pull,
            runner=self.runner,
            branch=self.branch,
        )

    def run_module(self, *module_names, workers=None, method=None):
        """Triggers modules by name."""
        self._trigger(requested_modules=":" + ":".join(module_names) + ":")

    def run_rank(self, *module_names, workers=None, method=None):
        """Triggers forward-slice from module rank."""
        ranks = dag.get_topological_ranks()
        indices = [
            next(i for i, r in enumerate(ranks) if name in r) for name in module_names
        ]
        selected = [m for r in ranks[min(indices) :] for m in r]
        self._trigger(requested_modules=":" + ":".join(selected) + ":")

    def run_subgraph(self, *module_names, workers=None, method=None):
        """Triggers descendants of target modules."""
        selected = dag.get_subgraph(list(module_names))
        self._trigger(requested_modules=":" + ":".join(selected) + ":")

    def run_category(self, *category_names, workers=None, method=None):
        """Triggers modules sharing semantic tags."""
        cat_map = dag.get_category_map()
        targets = set()
        for name in category_names:
            targets.update(cat_map.get(name, []))
        self._trigger(requested_modules=":" + ":".join(targets) + ":")

    def run_all(self, workers=None, method=None):
        """Triggers full DAG."""
        self._trigger(trigger_all=True)


def _run_hook(module_name, hook_name):
    """
    Executes a module hook (pre or post).
    Automatically initializes root results directory.
    """
    module_dir = paths.module_dir()
    cfg = yamler.load_yaml(f"{module_dir}/{module_name}")
    hook_cfg = cfg.get(hook_name)

    if not hook_cfg:
        # Fallback to pure OOP hook
        module_cls = module.get_module_class(module_name)
        if not hasattr(module_cls, hook_name):
            return

        module.make(paths.local_path(cfg["root_path"]))
        kwargs = {"root_path": cfg["root_path"]}

        print(f"HOOK {module_name}.{hook_name}")
        getattr(module_cls, hook_name)(**kwargs)
        return

    root_path = paths.local_path(cfg["root_path"])
    module.make(root_path)

    kwargs = hook_cfg.get("param", {}).copy()
    kwargs["root_path"] = root_path

    if "script" in hook_cfg:
        commands = hook_cfg["script"]
        if isinstance(commands, str):
            commands = [commands]

        for cmd_template in commands:
            cmd = yamler.render_string(cmd_template, **kwargs)
            print(f"HOOK {module_name}.{hook_name} -> {cmd}")
            subprocess.run(cmd, shell=True, cwd=str(root_path), check=True)
    elif "src" in hook_cfg:
        mod = importlib.import_module(hook_cfg["src"])
        cls = getattr(mod, hook_cfg.get("class", "Hook"))
        cls(**kwargs)
    else:
        # Fallback if there's a hook block without script or src
        module_cls = module.get_module_class(module_name)
        if hasattr(module_cls, hook_name):
            print(f"HOOK {module_name}.{hook_name} (OOP)")
            getattr(module_cls, hook_name)(**kwargs)


def run_pre(module_name):
    """
    Executes module setup hook.
    Automatically initializes root results directory.

    Args:
        module_name (str): Target module.
    """
    _run_hook(module_name, "pre")


def run_post(module_name):
    """
    Executes module cleanup hook.
    Automatically initializes root results directory.

    Args:
        module_name (str): Target module.
    """
    _run_hook(module_name, "post")


def prepare_module(module_name, method):
    """
    Executes transport initialization.

    Args:
        module_name (str): Target module.
        method (str): Scaling strategy.
    """
    module_dir = paths.module_dir()
    module_cfg = yamler.load_yaml(f"{module_dir}/{module_name}.yml.j2")
    mgr = manager.get_manager(method, module_name)

    if mgr.has_prepare:
        print(f"PREP {module_name} ({mgr.method})")
        inputs = manager.get_inputs(module_name, module_cfg)
        mgr.prepare(inputs)


def dispatch_module(module_name, method, workers=None):
    """
    Executes task engine.

    Args:
        module_name (str): Target module.
        method (str): Scaling strategy.
        workers (int, optional): Parallel worker count.
    """
    mgr = manager.get_manager(method, module_name)

    if method == "thread":
        module_dir = paths.module_dir()
        module_cfg = yamler.load_yaml(f"{module_dir}/{module_name}.yml.j2")
        res = config.get_module_config(module_cfg)

        # Ensure workers is an integer or None for Joblib
        w = (
            int(workers)
            if workers is not None and str(workers).lower() != "none"
            else None
        )
        mgr.dispatch(workers=w, **res.get("joblib", {}))
    else:
        mgr.dispatch()


def exec_module(module_name, **kwargs):
    """
    Directly executes a single module task.

    Args:
        module_name (str): Target module.
        **kwargs: Task identity parameters.
    """
    manager.exec_module(module_name, **kwargs)


def get_runner(name="local", **kwargs):
    """
    Instantiates environment-specific initiator.

    Args:
        name (str): 'local' or 'gitlab'.
        **kwargs: Initializer parameters.

    Returns:
        Runner: Initiator instance.
    """
    if name == "local":
        return LocalRunner()
    if name == "gitlab":
        return GitLabRunner(**kwargs)
    raise ValueError(f"Unknown runner: {name}")


def run_module(
    *module_names, workers=None, method=None, executor="local", **runner_kwargs
):
    """Public initiator for module execution."""
    get_runner(executor, **runner_kwargs).run_module(
        *module_names, workers=workers, method=method
    )


def run_rank(
    *module_names, workers=None, method=None, executor="local", **runner_kwargs
):
    """Public initiator for rank-based execution."""
    get_runner(executor, **runner_kwargs).run_rank(
        *module_names, workers=workers, method=method
    )


def run_subgraph(
    *module_names, workers=None, method=None, executor="local", **runner_kwargs
):
    """Public initiator for subgraph execution."""
    get_runner(executor, **runner_kwargs).run_subgraph(
        *module_names, workers=workers, method=method
    )


def run_category(
    *category_names, workers=None, method=None, executor="local", **runner_kwargs
):
    """Public initiator for category execution."""
    get_runner(executor, **runner_kwargs).run_category(
        *category_names, workers=workers, method=method
    )


def run_all(workers=None, method=None, executor="local", **runner_kwargs):
    """Public initiator for DAG execution."""
    get_runner(executor, **runner_kwargs).run_all(workers=workers, method=method)
