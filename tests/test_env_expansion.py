import os
import textwrap
import pytest
from scicd.config import load_yaml, TaskConfig, WorkspaceConfig, RemoteConfig

def test_expansion_and_escaping(tmp_path):
    """Verify $VAR expansion and $$VAR escaping via load_yaml."""
    os.environ["BUILD_TIME"] = "2024"
    os.environ["MY_IMAGE"] = "python:3.10"
    os.environ["DATA_ROOT"] = "/scratch/data"
    
    config_content = textwrap.dedent("""
        workspace:
          project: "my-project-$BUILD_TIME"
        
        image: "$MY_IMAGE"
        
        remote:
          root: "$DATA_ROOT/outputs"
          url: "s3://bucket/$BUILD_TIME"
        
        variables:
          BUILD_STAMP: "$BUILD_TIME"
          RUNTIME_JOB_ID: "$$CI_JOB_ID"
          ESCAPED_DOLLAR: "$$$$VAL"
    """)
    config_file = tmp_path / "scicd.yaml"
    config_file.write_text(config_content)
    
    data = load_yaml(str(config_file))
    
    # 1. Basic Expansion
    assert data["workspace"]["project"] == "my-project-2024"
    assert data["image"] == "python:3.10"
    assert data["remote"]["root"] == "/scratch/data/outputs"
    assert data["remote"]["url"] == "s3://bucket/2024"
    
    # 2. Variable expansion in nested dicts
    assert data["variables"]["BUILD_STAMP"] == "2024"
    
    # 3. Escaping with $$
    assert data["variables"]["RUNTIME_JOB_ID"] == "$CI_JOB_ID"
    assert data["variables"]["ESCAPED_DOLLAR"] == "$$VAL"

def test_no_expansion_on_direct_instantiation():
    """
    Verify that models do NOT expand variables themselves.
    Expansion is now a build-time/load-time concern handled by yamler.
    """
    os.environ["TEST_VAR"] = "fail"
    
    # Direct model creation should preserve the literal string
    tc = TaskConfig(image="$TEST_VAR")
    assert tc.image == "$TEST_VAR"
    
    ws = WorkspaceConfig(project="org/$TEST_VAR")
    assert ws.project == "org/$TEST_VAR"

def test_complex_escaping(tmp_path):
    """Verify complex mixed strings expand correctly."""
    os.environ["A"] = "alpha"
    config_content = "user: { val: '$$$$$A and $A and $$A' }"
    config_file = tmp_path / "scicd.yaml"
    config_file.write_text(config_content)
    
    data = load_yaml(str(config_file))
    assert data["user"]["val"] == "$$alpha and alpha and $A"
