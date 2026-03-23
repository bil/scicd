
import luigi
import pytest
import json
import hashlib
from scicd.frontend.luigi.task import SciTask
from scicd.config import reset_config, TaskConfig, DynamicModel

class DeterministicTask(SciTask):
    param = luigi.Parameter()
    def output(self):
        return luigi.LocalTarget(f"tmp/{self.param}")

def test_fingerprint_determinism_cfg_order(mocker):
    """Verify that different dictionary insertion orders in cfg produce the same fingerprint."""
    reset_config()
    mocker.patch("scicd.frontend.luigi.task.get_git_commit", return_value="abc1234")
    
    task = DeterministicTask(param="test")
    
    # We mock 'cfg' such that its 'model_dump' returns different orders
    mock_cfg1 = mocker.MagicMock()
    mock_cfg1.model_dump.return_value = {"z": 1, "a": 2}
    
    mock_cfg2 = mocker.MagicMock()
    mock_cfg2.model_dump.return_value = {"a": 2, "z": 1}
    
    # Patch the task instance's cfg property
    mocker.patch.object(task, "cfg", mock_cfg1)
    fp1 = task.get_fingerprint()
    
    mocker.patch.object(task, "cfg", mock_cfg2)
    fp2 = task.get_fingerprint()
    
    assert fp1 == fp2

def test_fingerprint_determinism_params_order(mocker):
    """Verify that different parameter orders produce the same fingerprint."""
    reset_config()
    mocker.patch("scicd.frontend.luigi.task.get_git_commit", return_value="abc1234")
    
    task = DeterministicTask(param="test")
    
    # Mock 'cfg' to return a stable dict
    mock_cfg = mocker.MagicMock()
    mock_cfg.model_dump.return_value = {"window": 5}
    mocker.patch.object(task, "cfg", mock_cfg)

    # Mock param_kwargs with different orders
    mocker.patch.object(task, "param_kwargs", {"z": 1, "a": 2})
    fp1 = task.get_fingerprint()
    
    mocker.patch.object(task, "param_kwargs", {"a": 2, "z": 1})
    fp2 = task.get_fingerprint()
    
    assert fp1 == fp2
