
import subprocess
import yaml


def test_simple_dag(tmp_path):
    out_path = tmp_path / "simple.yml"
    subprocess.run(["scicd", "luigi", "build", "tests.luigi.simple", "CountLetters", "--config-path", "/dev/null", "--file-path", str(out_path)])
    with open(out_path, "r", encoding="utf-8") as f:
        gitlab_yaml = yaml.safe_load(f)
    assert len(gitlab_yaml["stages"]) == 2
    assert "CountLetters" in gitlab_yaml
