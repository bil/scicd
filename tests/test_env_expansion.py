import os
import textwrap

from scicd.config import WorkspaceConfig, RemoteConfig, TaskConfig, load_yaml


def test_selective_expansion():
    os.environ["TEST_VAR"] = "expanded_value"
    os.environ["HOME_PATH"] = "/home/user"

    # Workspace expansion
    ws = WorkspaceConfig(url="https://$TEST_VAR.com", project="org/$TEST_VAR")
    assert ws.url == "https://expanded_value.com"
    assert ws.project == "org/expanded_value"

    # Remote expansion
    rem = RemoteConfig(root="$HOME_PATH/data", url="s3://$TEST_VAR/bucket")
    assert rem.root.endswith("/home/user/data")
    assert rem.url == "s3://expanded_value/bucket"

    # Namespace inclusion
    rem = RemoteConfig(
        root="$HOME_PATH/data", url="s3://$TEST_VAR/bucket", namespace="a-namespace"
    )
    assert rem.total_root.endswith("a-namespace")
    assert rem.total_url.endswith("a-namespace")

    # TaskConfig expansion
    tc = TaskConfig(image="python:$TEST_VAR", variables={"MY_VAR": "$KEEP_ME"})
    assert tc.image == "python:expanded_value"
    # Task variables should NOT be expanded by SciCD
    assert tc.variables["MY_VAR"] == "$KEEP_ME"


def test_jinja_env_expansion(tmp_path):

    os.environ["BUILD_TIME"] = "2024"
    config_content = textwrap.dedent(
        """
        workspace:
          project: "my-project-{{ env.BUILD_TIME }}"
        cpu: 2
        variables:
          RUNTIME_VAR: "$CI_JOB_ID"
    """
    )
    config_file = tmp_path / "scicd.yaml"
    config_file.write_text(config_content)

    data = load_yaml(str(config_file))

    assert data["workspace"]["project"] == "my-project-2024"
    assert data["variables"]["RUNTIME_VAR"] == "$CI_JOB_ID"
