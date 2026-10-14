"""真实子进程超时的用法示范；只替换 worker 工作，不改超时控制。"""

import subprocess
import sys

import pytest
from _doubles.script_frames import frame, run_of

from evals.world_script_execute.dataset import load
from evals.world_script_execute.isolated import ScriptRequest, ScriptSetupTimeout, run_isolated


@pytest.mark.parametrize("prepared", [True, False])
def test_a_hung_worker_is_killed_and_only_a_prepared_frame_can_be_scored(monkeypatch, prepared):
    original_run = subprocess.run
    case = load()[0]

    def hung_worker(command, **kwargs):
        request = ScriptRequest.model_validate_json(kwargs["input"])
        if prepared:
            checkpoint = run_of(None, frame(), frame(), crash="超时")
            request.checkpoint.write_text(checkpoint.model_dump_json(), encoding="utf-8")
        return original_run([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

    monkeypatch.setattr(subprocess, "run", hung_worker)

    if prepared:
        result = run_isolated(case, timeout=0.1)

        assert result.crash == "超时" and result.report is None
        assert result.before_observation == result.after_observation
    else:
        with pytest.raises(ScriptSetupTimeout, match="装配超时"):
            run_isolated(case, timeout=0.1)
