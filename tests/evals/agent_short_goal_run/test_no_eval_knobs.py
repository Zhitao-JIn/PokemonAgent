"""删除评测旋钮 knowledge / speed / watch：配置、请求模型与函数签名都不再含这三项。"""

from __future__ import annotations

import inspect
import json

from evals.agent_short_goal_run.solver.record import RunOneRequest
from evals.agent_short_goal_run.solver.runner.one import run_one
from evals.agent_short_goal_run.solver.solver import run_one_solver
from evals.agent_short_goal_run.task import agent_short_goal_run
from evals.runconfig import CONFIG_PATH, REQUIRED_KEYS

KNOBS = {"knowledge", "speed", "watch"}


def test_config_and_required_keys_agree_and_have_no_eval_knobs() -> None:
    """config.json 与 REQUIRED_KEYS 都不含旋钮，且必需键都在 config 里。"""
    config_keys = set(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))

    assert not (KNOBS & config_keys)
    assert not (KNOBS & set(REQUIRED_KEYS))
    assert set(REQUIRED_KEYS) <= config_keys


def test_run_one_request_has_no_eval_knobs() -> None:
    """RunOneRequest 无 knowledge / speed 字段。"""
    assert not (KNOBS & set(RunOneRequest.model_fields))


def test_signatures_have_no_eval_knobs() -> None:
    """task / solver / runner 三个入口签名都不含旋钮。"""
    for function in (agent_short_goal_run, run_one_solver, run_one):
        parameters = set(inspect.signature(function).parameters)
        assert not (KNOBS & parameters), f"{function.__name__} 还带着评测旋钮"
