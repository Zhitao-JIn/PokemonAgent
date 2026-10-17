"""真实 task 图中，按键与脚本一轮都只留一条 ActMemory。"""

from pathlib import Path

import pytest
from _harness_fixtures.harness import build_fake

from pokemon_agent.brain import Action, ActionSegment, ScriptCall, Task
from pokemon_agent.harness.task import compile_task_graph
from pokemon_agent.harness.task.task_entry import run_task
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolExecuteResp,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import TaskInput
from pokemon_agent.world import ActionEntry, ActionSpace


class _Chooser:
    def __init__(self, action: Action) -> None:
        self.action = action

    def choose(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        return FromHarnessToBrainToolChooseOnceResp(
            action=self.action, calls=[ModelCall(payload={})]
        )


@pytest.mark.parametrize("script", [False, True])
def test_one_round_produces_one_act_memory_even_for_scripts(tmp_path: Path, script: bool) -> None:
    fake = build_fake(tmp_path)
    runtime = fake.run_rt.episode.task
    action = (
        Action(script=ScriptCall(name="advance_dialog"))
        if script
        else Action(sequence=[ActionSegment(name="up")])
    )
    runtime.chooser = _Chooser(action)

    def space(
        req: FromHarnessToGameToolGetActionSpaceReq,
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        return FromHarnessToGameToolGetActionSpaceResp(
            action_space=ActionSpace(
                names=["up"], entries=[ActionEntry(kind="script", name="advance_dialog")]
            )
        )

    def execute(req: FromHarnessToGameToolExecuteReq) -> FromHarnessToGameToolExecuteResp:
        return FromHarnessToGameToolExecuteResp(
            report={
                "ok": True,
                "code": "ok",
                "data": {"internal_presses": 5},
                "events": [],
                "calls": [],
            }
            if req.action.script
            else None
        )

    runtime.game.get_action_space = space
    runtime.game.execute = execute
    task_input = TaskInput(
        run_id="r1",
        episode_id="e1",
        total_acts=0,
        task=Task(task_id="t1", goal="子任务", success_criteria="c", max_steps=1),
    )

    output = run_task(runtime, compile_task_graph(), task_input=task_input)
    writes = [event for event in fake.trace.read_events({}) if event.kind == "write_act_memory"]

    assert output.steps_used == 1
    assert len(fake.memory.acts) == len(writes) == 1
    assert fake.memory.acts[0].task_id == "t1"
    assert fake.memory.acts[0].before_frame and fake.memory.acts[0].after_frame
    if script:
        assert "script:advance_dialog" in fake.memory.acts[0].action
