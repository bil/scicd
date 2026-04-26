"""
Implementation for GNU Make
"""

from __future__ import annotations

import re
import subprocess

from dataclasses import dataclass, field, InitVar
from typing import Optional, Annotated

from cyclopts import App, Parameter

from scicd.adapter import BaseAdapter
from scicd.config import (
    DynamicModel,
    get_task_config,
    TaskConfig,
    get_workspace_config,
)
from scicd.yamler import nest_dict
import scicd.dag

app = App(name="make", help="Make sub-command")

# NOT SUPPORTED
# double-colon rules: https://www.gnu.org/software/make/manual/html_node/Double_002dColon.html
# these are used to specify MULTIPLE recipes for the same target
# you can use the same target in multiple rules to add deps but not to add multiple execution paths


def get_stem(implicit_pattern: str, value: str) -> Optional[str]:
    assert "%" in implicit_pattern
    prefix, suffix = implicit_pattern.split("%")
    re_stem = re.compile(rf"^{re.escape(prefix)}(\w+){re.escape(suffix)}$")
    match = re_stem.search(value)
    if not match:
        return None
    stem = match.group(1)
    return stem


def match_pattern(pattern: str, value: str) -> bool:
    if "%" in pattern:
        out = get_stem(pattern, value)
        return out is not None
    return pattern == value


def fill_patterns(patterns: list[str], stem: str) -> list[str]:
    out = []
    for pat in patterns:
        if "%" in pat:
            pat = pat.replace("%", stem)
        out.append(pat)
    return out


@dataclass
class Rule:
    """
    Data description of a single GNU Make rule/recipe
    """

    name: str
    line: Optional[int] = None
    implicit: bool = False
    phony: bool = False
    grouped: bool = False
    config: Optional[TaskConfig] = None
    config_path: Optional[str] = None

    target_patterns: InitVar[Optional[list[str]]] = None
    prereq_patterns: InitVar[Optional[list[str]]] = None

    def __post_init__(
        self,
        target_patterns: Optional[list[str]],
        prereq_patterns: Optional[list[str]],
    ):
        if self.implicit:
            self.grouped = True
        # initialize map
        if prereq_patterns is None:
            prereq_patterns = []
        self.prereq_map = {
            target: prereq_patterns for target in target_patterns
        }

    def __repr__(self):
        return f"<Rule: {self.name} " f"Mapping: {self.prereq_map}"

    def match_stem(self, value: str) -> Optional[str]:
        if not self.implicit:
            return None
        for pat in self.prereq_map:
            stem = get_stem(pat, value)
            if stem is not None:
                return stem
        return None

    def match(self, value: str) -> bool:
        for pat in self.prereq_map:
            if match_pattern(pat, value):
                return True
        return False

    def add_pattern(self, target: str, prereqs: list[str]) -> None:
        if target in self.prereq_map:
            for prereq in prereqs:
                if prereq not in self.prereq_map[target]:
                    self.prereq_map[target].append(prereq)
            return
        self.prereq_map[target] = prereqs
        self.prereq_map = dict(sorted(self.prereq_map.items()))


def find_rule_by_line(rules: list[Rule], line: int) -> Optional[Rule]:
    for rule in rules:
        if rule.line == line:
            return rule
    return None


def find_rule(rules: list[Rule], value) -> Optional[Rule]:
    for rule in rules:
        if rule.match(value):
            return rule
    return None


@dataclass
class MakeWork:
    """
    # A Python wrapper for performing a Make rule."""

    # name: str
    makefile_path: str
    rule: Rule
    targets: list[str]
    outputs: list[str]
    prereqs: list[str]
    inputs: list[str]
    stem: Optional[str] = None

    def __post_init__(self) -> None:
        self.name = self.rule.name

    def add_target(self, val: str) -> None:
        if val in self.targets:
            return
        self.targets.append(val)


def find_work(target_name: str, works: list[MakeWork]) -> Optional[MakeWork]:
    for work in works:
        if target_name in work.targets:
            return work
    return None


class MakeAdapter(BaseAdapter):
    """
    Make adapter
    """

    def __init__(
        self, work: MakeWork, config_path: Optional[str] = None
    ) -> None:
        """
        Initialize the adapter.
        """
        self._deps: list[MakeAdapter] = []
        super().__init__(work, config_path)

    def __repr__(self) -> str:
        return self.identifier

    @property
    def name(self) -> str:
        """
        The name of the procedure.
        """
        return self.work.name

    @property
    def identifier(self) -> str:
        """A unique, deterministic string identifying this unit of work."""
        # unique association between an explicit target and a rule
        return "&".join(self.work.targets)

    @property
    def params(self) -> DynamicModel:
        """Return procedure parameters as a flexible Pydantic model."""
        if self.work.stem:
            return DynamicModel(stem=self.work.stem)
        else:
            return DynamicModel()

    @property
    def cfg(self) -> TaskConfig:
        """The fully resolved TaskConfig for this specific work unit."""
        return self.work.rule.config

    # @property
    # def target_patterns(self) -> list[str]:
    #     return self.work.rule.target_patterns

    @property
    def commands(self) -> list[str]:
        """Script command"""
        cmd = f"make -f {self.work.makefile_path}"
        wspace = get_workspace_config(self.config_path)
        if wspace.data_root:
            cmd += f' -C "{wspace.data_root}"'
        cmd += f" {' '.join(self.work.targets)}"  # pylint: disable=inconsistent-quotes
        return [cmd]

    @property
    def inputs(self) -> list[str]:
        """A list of input files"""
        return self.work.inputs

    @property
    def outputs(self) -> list[str]:
        return self.work.outputs

    def match(self, target_name: str) -> bool:
        return target_name in self.work.targets

    @property
    def deps(self) -> list[MakeAdapter]:
        """Adapters for immediately upstream work"""
        return self._deps

    def add_dep(self, val: MakeAdapter) -> None:
        if val not in self._deps:
            self._deps.append(val)


def get_make_trace(
    makefile_path: str = "Makefile",
    targets: Optional[list[str]] = None,
) -> str:
    trace_cmd = ["make", "-f", makefile_path, "-Bnd"]
    if targets is None:
        targets = []
    for target in targets:
        trace_cmd.append(target)
    make_trace = subprocess.run(
        trace_cmd, check=True, capture_output=True
    ).stdout.decode("utf-8")
    return make_trace


def get_db_trace(
    makefile_path: str = "Makefile",
    targets: Optional[list[str]] = None,
) -> str:
    db_cmd = ["make", "-f", makefile_path, "-Bnp"]
    if targets is None:
        targets = []
    for target in targets:
        db_cmd.append(target)
    db_trace = subprocess.run(
        db_cmd, check=True, capture_output=True
    ).stdout.decode("utf-8")
    return db_trace


def extract_rules_from_db(
    db_text: str, makefile_path: str = "Makefile", config_path: str = None
) -> list[Rule]:
    """
    Prases a `make -p` database.
    """
    # print(f"Extracting rules from file: {makefile_path}")
    rules: list[Rule] = []

    current_target = None
    current_prereqs = None
    started = False
    not_a_target = False
    # Regex to catch: "(from 'Makefile', line 12)"
    re_line_num = re.compile(
        rf"\(from '{re.escape(makefile_path)}', line (\d+)\)"
    )
    re_also_makes = re.compile(r"Also makes: (\S+)")
    re_not_a_target = re.compile(r"Not a target:")
    re_phony_target = re.compile(
        re.escape("Phony target (prerequisite of .PHONY).")
    )

    for line in db_text.splitlines():
        # Skip dry run outpu
        if not started:
            if line.startswith("# Make data base, printed"):
                started = True
            continue
        # Skip empty lines or recipe commands (which start with a tab)
        if not line or line.startswith("\t"):
            continue

        if re_not_a_target.search(line):
            not_a_target = True
            continue

        if not_a_target:
            # Skip subsequent line
            not_a_target = False
            continue

        if (
            not line.startswith("#")
            and ":" in line
            and "::" not in line
            and "=" not in line
        ):
            # Assumes colons not used in paths
            linespl = line.split(":")
            assert len(linespl) == 2
            current_target = linespl[0].strip()
            current_prereqs = linespl[1].strip().split()
            continue

        # FIND ITS LINE NUMBER
        # If we have a target loaded and we hit a Make metadata comment
        if current_target and line.startswith("#"):
            match = re_phony_target.search(line)
            if match:
                rules.append(
                    Rule(
                        name=current_target,
                        target_patterns=[current_target],
                        prereq_patterns=current_prereqs,
                        line=None,
                        phony=True,
                    )
                )
                current_target = None
                continue

            match = re_also_makes.search(line)
            if match:
                target_group = set(match.group(1).strip().split())
                target_group.add(current_target)  # just in case
                target_group = list(sorted(target_group))
                matched_rule = None
                for val in target_group:
                    matched_rule = find_rule(rules, val)
                    if matched_rule is not None:
                        break
                if matched_rule is not None:
                    if not matched_rule.implicit:
                        for val in target_group:
                            matched_rule.add_pattern(val, current_prereqs)
                    matched_rule.grouped = True
                else:
                    # Line number information comes later
                    rules.append(
                        Rule(
                            name=current_target,
                            target_patterns=target_group,
                            prereq_patterns=current_prereqs,
                            grouped=True,
                        )
                    )
                continue

            # Rule with a recipe...
            match = re_line_num.search(line)
            if match:
                # line indicates start of recipe by default
                line_number = int(match.group(1)) - 1
                if "%" in current_target:
                    target_patterns = current_target.split()
                    rules.append(
                        Rule(
                            name=target_patterns[0],
                            target_patterns=target_patterns,
                            prereq_patterns=current_prereqs,
                            line=line_number,
                            implicit=True,
                        )
                    )
                    # print(
                    #     (f"Added implicit rule {current_target} "
                    #     f"with patterns {patterns}")
                    # )
                    current_target = None
                    continue

                matched_rule = find_rule(rules, current_target)
                if matched_rule is not None:
                    if matched_rule.line is not None:
                        assert matched_rule.line == line_number
                    else:
                        matched_rule.line = line_number
                    current_target = None
                    continue

                matched_rule = find_rule_by_line(rules, line_number)

                # this happens for multi-target rules that are split
                if matched_rule is not None:
                    matched_rule.add_pattern(current_target, current_prereqs)
                    current_target = None
                    continue

                rules.append(
                    Rule(
                        name=current_target,
                        target_patterns=[current_target],
                        prereq_patterns=current_prereqs,
                        line=line_number,
                    )
                )
                current_target = None
                continue
    for rule in rules:
        rule.config = extract_rule_config(rule, makefile_path, config_path)
        rule.config_path = config_path
    return rules


def extract_rule_config(
    rule: Rule,
    makefile_path: str = "Makefile",
    config_path: Optional[str] = None,
) -> TaskConfig:
    config = {}
    if rule.line:
        with open(makefile_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        rule_lines = lines[rule.line :]
        for l in rule_lines:
            if "# scicd:" in l:
                _, config_str = l.split("# scicd", maxsplit=1)
                config_str = config_str.strip()
                parts = config_str.split()
                for part in parts:
                    if "=" not in part:
                        continue
                    key, val = part.split(sep="=")
                    config[key] = val
            else:
                break
    nested_overrides = nest_dict(config)
    out = get_task_config(rule.name, config_path, **nested_overrides)
    return out


def find_adapter(
    adapters: list[MakeAdapter], target_name: str
) -> Optional[MakeAdapter]:
    for adapter in adapters:
        if adapter.match(target_name):
            return adapter
    return None


def parse_make_trace(
    make_trace: str,
    rules: list[Rule],
    makefile_path: str = "Makefile",
) -> MakeAdapter:
    """Parses a make -Bnd trace into a wired graph of MakeAdapters."""
    works: list[MakeWork] = []
    adapters: list[MakeAdapter] = []
    stack: list[MakeAdapter] = (
        []
    )  # Keeps track of the current parent-child chain

    # Pre-compile regexes for speed
    # name is enclosed with single quotes
    re_considering = re.compile(r"Considering target file '([^']+)'")
    re_considered_already = re.compile(r"File '([^']+)' was considered already")
    re_pruning = re.compile(r"Pruning file '([^']+)'")
    re_finished = re.compile(r"Finished prerequisites of target file '([^']+)'")

    target_name: Optional[str] = None
    current_adapter: Optional[MakeAdapter] = None
    root: Optional[MakeAdapter] = None

    for line in make_trace.splitlines():
        # NEW TARGET
        match_target = re_considering.search(line)
        if match_target:
            target_name = match_target.group(1)
            if target_name == makefile_path:
                continue

            rule = find_rule(rules, target_name)
            if rule is None:
                continue
            if find_work(target_name, works) is None:
                if rule.implicit:
                    stem = rule.match_stem(target_name)
                    assert stem is not None

                    targets = fill_patterns(list(rule.prereq_map.keys()), stem)
                    outputs = targets
                    # all targets have same prereqs
                    prereqs = fill_patterns(
                        list(rule.prereq_map.values())[0], stem
                    )
                elif rule.grouped:
                    stem = None
                    targets = list(rule.prereq_map.keys())
                    outputs = targets
                    prereqs = list(rule.prereq_map.values())[0]
                elif rule.phony:
                    stem = None
                    targets = list(rule.prereq_map.keys())
                    outputs = []
                    prereqs = list(rule.prereq_map.values())[0]
                else:  # could be an instantiation of multi-target rule
                    stem = None
                    targets = [target_name]
                    outputs = targets
                    prereqs = rule.prereq_map[target_name]
                    # prereqs = rule.prereq_patterns

                inputs = [
                    prereq
                    for prereq in prereqs
                    if not find_rule(rules, prereq).phony
                ]

                work = MakeWork(
                    targets=targets,
                    outputs=outputs,
                    prereqs=prereqs,
                    inputs=inputs,
                    stem=stem,
                    makefile_path=makefile_path,
                    rule=rule,
                )
                # if rule.phony:
                #     targets = rule.
                # work = MakeWork(makefile_path=makefile_path, rule=rule)
                # works.append(work)
                # if rule.phony:
                #     work.add_target(target_name)
                # else:
                #     if rule.implicit:
                #         stem = rule.match_stem(target_name)
                #         assert stem is not None
                #         work.stem = stem
                #         filled_patterns = fill_patterns(rule.target_patterns, stem)
                #         filled_prereqs = fill_patterns(rule.prereq_patterns, stem)
                #         for target in filled_patterns:
                #             work.add_target(target)
                #         for prereq in filled_prereqs:
                #             work.add_prereq(prereq)
                #     elif rule.grouped:
                #         assert target_name in rule.target_patterns
                #         for pat in rule.target_patterns:
                #             work.add_target(pat)
                #     else:
                #         work.add_target(target_name)
                current_adapter = MakeAdapter(work, work.rule.config_path)
                adapters.append(current_adapter)
            else:
                # print(f"FINDING ADAPTER: {target_name}")
                current_adapter = find_adapter(adapters, target_name)

            # If there is a parent on the stack, link them!
            if stack:
                parent = stack[-1]
                parent.add_dep(current_adapter)

            # Push current target to the top of the stack
            stack.append(current_adapter)
            continue

        match_considered_already = re_considered_already.search(line)
        if match_considered_already:
            assert stack
            considered_target = match_considered_already.group(1)
            assert stack[-1].match(considered_target)
            # print(f"{considered_target} already handled! Popping!")
            stack.pop()

        match_prune = re_pruning.search(line)
        # we should be visiting with a parent on stack
        # and the adapter should already exist
        if match_prune:
            assert stack
            pruned_target = match_prune.group(1)
            # print(f"PRUNING: {pruned_target}")
            adapter = find_adapter(adapters, pruned_target)
            assert adapter is not None
            parent = stack[-1]
            parent.add_dep(adapter)
            continue

        match_finished = re_finished.search(line)
        if match_finished:
            # we should be in the midst of a stack
            if not stack:
                continue
            finished_target = match_finished.group(1)
            assert stack[-1].match(finished_target)
            out = stack.pop()
            # print(f"POPPING: {finished_target}")
            if not stack:
                assert not root
                root = out

    assert root
    return root


@app.command
def rules(
    makefile_path: Annotated[str, Parameter(alias="-f")] = "Makefile",
    targets: Annotated[Optional[list[str]], Parameter(alias="t")] = None,
    config_path: Annotated[Optional[str], Parameter(alias="-c")] = None,
) -> list[Rule]:
    db_text = get_db_trace(makefile_path, targets)
    rules = extract_rules_from_db(db_text, makefile_path, config_path)
    return rules


# def _run(makefile_path: str = "Makefile", targets: Optional[list[str]] = None) -> None:
#     cmd = [
#         "make",
#         "-f",
#         makefile_path,
#     ]
#     if targets:
#         cmd.extend(targets)
#     subprocess.run(cmd, check=True)


# @app.command()
# def run(
#     makefile_path: str = "Makefile", targets: Optional[list[str]] = None
# ) -> None:  # pylint: disable=unused-argument
#     _run(makefile_path, targets)

# @app.command()
# def run_slice(patterns: list[str], makefile_path: str = "Makefile"):
#     my_params = get_my_params()
#     targets = []
#     for prms in my_params:
#         targets.extend(fill_patterns(patterns, prms["stem"]))
#     _run(makefile_path, targets)


@app.command
def build(
    makefile_path: Annotated[str, Parameter(alias="-f")] = "Makefile",
    targets: Annotated[Optional[list[str]], Parameter(alias="t")] = None,
    config_path: Annotated[Optional[str], Parameter(alias="-c")] = None,
    backend: Annotated[str, Parameter(alias="-b")] = "gitlab",
    file_path: Annotated[Optional[str], Parameter(alias="-o")] = None,
) -> None:
    make_trace = get_make_trace(makefile_path, targets)
    db_trace = get_db_trace(makefile_path, targets)
    rules = extract_rules_from_db(db_trace, makefile_path, config_path)
    adapter = parse_make_trace(make_trace, rules, makefile_path)
    dag = scicd.dag.build(adapter)
    dag.export(backend, file_path)
    return


if __name__ == "__main__":
    app()
