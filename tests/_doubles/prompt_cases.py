"""Small, deterministic inputs for CP0; no model, clock, or environment configuration."""

from __future__ import annotations

from pydantic import BaseModel, JsonValue

from pokemon_agent.brain.interface import Goal, Task, VerifyVerdict
from pokemon_agent.mcpclient.action_space import action_space_for
from pokemon_agent.schemas import harness as h
from pokemon_agent.schemas.harness.domain import GoalEntry, JudgeFeedback, TaskEntry
from pokemon_agent.schemas.harness.domain.termination import Termination
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, RunMemory, TaskMemory
from pokemon_agent.schemas.memory.datastore.object_memory import ObjectDialogEvent
from pokemon_agent.world import Facts, TaskObservation, TaskScene
from pokemon_agent.world.interface.domain.takeover_view import (
    BagEntry,
    BagView,
    BattleMenuView,
    BattleSwitchView,
    BoxEntry,
    LearnMoveView,
    MonEntry,
    MoveEntry,
    NamingView,
    PartyView,
    PcView,
    ShopItem,
    ShopItemsView,
)


def observation(step: int = 0) -> TaskObservation:
    """A walk frame with enough geometry to exercise the existing text projection."""
    return TaskObservation(
        step=step,
        status="门口",
        scene=TaskScene.WALK,
        facts=Facts(
            overlay=Facts.Overlay.NONE,
            map_id=1,
            where="map=1 x=2 y=3",
            facing="up",
            neighbors="北 . 南 . 西 # 东 .",
            walk_map="y=3 #@. (x=1..3)",
        ),
    )


def acts(*, connected: bool = True) -> list[ActMemory]:
    """Two entries whose boundary frames either match or differ."""
    frames = [
        ActMemory.Observation.model_validate(observation(i).model_dump(mode="json"))
        for i in range(3)
    ]
    before = frames[1].model_copy(deep=True)
    if not connected:
        before.status = "另一帧"
    return [
        ActMemory(
            before=frames[0],
            after=frames[1],
            action="up",
            result="前进一步",
            step=1,
            episode_id="ep-1",
            task_id="task-1",
            run_id="run-1",
        ),
        ActMemory(
            before=before,
            after=frames[2],
            action="a",
            step=2,
            episode_id="ep-1",
            task_id="task-1",
            run_id="run-1",
        ),
    ]


def task_memory() -> TaskMemory:
    return TaskMemory(
        run_id="run-1",
        episode_id="ep-1",
        task_id="task-1",
        goal="进门",
        termination="goal_done",
        steps_used=2,
        total_acts=0,
        summary="走到门口并进门。",
        reason="地图改变",
        quality_score=0.8,
        quality_rationale="有前后帧",
        reusable_patterns=["对准门口"],
        critical_decisions=["向上"],
        failure_points=["不要撞墙"],
        tags=["导航"],
        markdown="进门记录",
    )


def episode_memory() -> EpisodeMemory:
    return EpisodeMemory(
        episode_id="ep-1",
        run_id="run-1",
        run_goal="出发",
        goal="进门",
        steps=1,
        acts_used=2,
        termination="goal_done",
        summary="已进门。",
        reason="地图改变",
        quality_score=0.8,
        quality_rationale="有执行证据",
        reusable_patterns=["从门口向上"],
        critical_decisions=["选门"],
        failure_points=["避免撞墙"],
        tags=["导航"],
        markdown="本局记录",
    )


def run_memory() -> RunMemory:
    return RunMemory(
        run_id="run-old",
        run_goal="出发",
        episodes=1,
        succeeded=0,
        acts_used=2,
        termination="budget_exhausted",
        summary="此前未进门。",
        quality_score=0.5,
        quality_rationale="预算不足",
    )


def goal_entry() -> GoalEntry:
    return GoalEntry(
        task=Task(task_id="goal-1", goal="进门", success_criteria="地图改变", max_steps=3)
    )


def object_event() -> ObjectDialogEvent:
    return ObjectDialogEvent(
        episode_id="ep-1",
        step=1,
        run_id="run-1",
        actor_place={"map_id": 1, "x": 2, "y": 3},
        place={"map_id": 1, "x": 2, "y": 2},
        object_kind="招牌",
        button="a",
        text="欢迎",
    )


def task_summary(entries: list[ActMemory]) -> h.FromHarnessToBrainToolSummarizeTaskReq:
    """Shared wrapper for synthetic entries and the unmodified real ActMemory inputs."""
    return h.FromHarnessToBrainToolSummarizeTaskReq(
        entries=entries,
        verdicts=[
            VerifyVerdict(
                index=i, positive=i % 2 == 0, why="与目标有关" if i % 2 == 0 else "偏离目标"
            )
            for i in range(len(entries))
        ],
        entry_id="entry-1",
        task_id="task-1",
        episode_id="ep-1",
        run_id="run-1",
        goal="进门",
        termination=Termination.GOAL_DONE,
        judge_reason="地图改变",
        steps_used=len(entries),
        max_steps=max(3, len(entries)),
    )


def synthetic_cases() -> list[tuple[str, str, dict[str, JsonValue]]]:
    """Return named current-envelope inputs; each name records the intended branch."""
    cases: list[tuple[str, str, dict[str, JsonValue]]] = []

    def add(task: str, name: str, req: BaseModel) -> None:
        cases.append((task, "synthetic-" + name, req.model_dump(mode="json", round_trip=True)))

    goal = Goal(goal="进门", criteria="地图改变")
    base = h.FromHarnessToBrainToolChooseOnceReq(
        goals=[goal],
        obs=observation(),
        space=action_space_for(observation(), ["up", "a", "b"]),
        memories=[],
    )
    for overlay in Facts.Overlay:
        obs = TaskObservation(
            step=0,
            status="门口",
            scene=TaskScene.DIALOG if overlay == Facts.Overlay.DIALOG else TaskScene.WALK,
            facts=Facts(
                overlay=overlay,
                where="map=1 x=2 y=3",
                dialog_text="欢迎" if overlay == Facts.Overlay.DIALOG else "",
                options=["YES", "NO"] if overlay == Facts.Overlay.CHOICE else [],
                cursor="YES" if overlay == Facts.Overlay.CHOICE else None,
            ),
        )
        add(
            "decide_action",
            "overlay-" + overlay.value,
            base.model_copy(update={"obs": obs, "space": action_space_for(obs, ["up", "a", "b"])}),
        )
    for connected in (True, False):
        add(
            "decide_action",
            "adjacent-" + ("hit" if connected else "miss"),
            base.model_copy(update={"memories": acts(connected=connected)}),
        )
    for name, update in [
        ("human-note", {"human_note": "先确认门口"}),
        ("last-result", {"last_result": "walk_to → completed：到门口"}),
        ("task-index", {"task_index": [task_memory()]}),
        ("knowledge", {"knowledge": "门可通往室内"}),
    ]:
        add("decide_action", name, base.model_copy(update=update))
    known = observation()
    known.facts = known.facts.model_copy(update={"known_objects": "招牌 (2,2)：欢迎"})
    add("decide_action", "known-objects", base.model_copy(update={"obs": known}))
    mon = MonEntry(
        name="BULBASAUR",
        level=5,
        hp=8,
        max_hp=20,
        active=True,
        moves=[MoveEntry(name="TACKLE", pp=10)],
    )
    fainted = mon.model_copy(update={"name": "PIDGEY", "hp": 0, "active": False, "status": "PSN"})
    bag = [BagEntry(name="POTION", quantity=2)]
    views = [
        ShopItemsView(money=500, items=[ShopItem(name="POTION", price=300)], bag=bag),
        NamingView(target="YOUR NAME?", typed="RED"),
        BattleMenuView(mine=mon, foe=fainted, party=[mon, fainted], bag=bag),
        BattleSwitchView(party=[mon, fainted]),
        BagView(bag=bag, party=[mon]),
        PartyView(party=[mon]),
        PcView(
            items=bag, bag=[], box=[BoxEntry(name="PIDGEY", level=3)], box_number=1, party=[mon]
        ),
        LearnMoveView(pokemon="BULBASAUR", new_move="GROWL", moves=mon.moves),
    ]
    for view in views:
        obs = TaskObservation(
            step=1,
            status="接管",
            scene=TaskScene(view.kind),
            takeover=view,
            facts=Facts(overlay=Facts.Overlay.CHOICE, screen="选择操作", cursor="1"),
        )
        add(
            "decide_action",
            "takeover-" + view.kind,
            base.model_copy(update={"obs": obs, "space": action_space_for(obs, ["up", "a", "b"])}),
        )
    missing = TaskObservation(
        step=1,
        status="背包",
        scene=TaskScene.BAG,
        menu_decode_complete=False,
        facts=Facts(screen="PALLET TOWN"),
    )
    add(
        "decide_action",
        "takeover-missing",
        base.model_copy(update={"obs": missing, "space": action_space_for(missing, ["a", "b"])}),
    )

    for level in ("task", "episode", "run"):
        for interrupt in (False, True):
            req = h.FromHarnessToBrainToolJudgeReq(goal=goal, allow_interrupt=interrupt)
            if level == "task":
                req.history = acts()
                req.task_index = [task_memory()]
            elif level == "episode":
                req.task_memories = [task_memory()]
                req.task_table = [TaskEntry(entry_id="entry-1", task=goal_entry().task, round=1)]
                req.episode_index = [episode_memory()]
                req.observation = observation()
            else:
                req.episode_memories = [episode_memory()]
                req.goal_table = [goal_entry()]
                req.run_index = [run_memory()]
                req.observation = observation()
            add("judge_success", f"{level}-interrupt-{str(interrupt).lower()}", req)

    plan = h.FromHarnessToBrainToolPlanOnceReq(run_goal=goal, run_id="run-1", plan=[], max_push=2)
    add("run_plan", "empty", plan)
    for name, update in [
        ("details", {"details": [episode_memory()]}),
        ("run-index", {"run_index": [run_memory()]}),
        ("knowledge", {"knowledge": ["门通往室内"]}),
        ("observation", {"observation": observation()}),
        ("objects", {"objects": [object_event()]}),
        ("last-judge", {"last_judge": JudgeFeedback(decision="continue", why="尚未进门")}),
        ("human-note", {"human_note": "先找入口"}),
        (
            "planning-budget",
            {"remaining_planning_rounds": 2, "execution_order": ["goal-1"], "plan": [goal_entry()]},
        ),
    ]:
        add("run_plan", name, plan.model_copy(update=update))

    for i, termination in enumerate(
        [
            Termination.GOAL_DONE,
            Termination.BUDGET_EXHAUSTED,
            Termination.INTERRUPTED,
            Termination.ERROR,
            Termination.WORLD_ENDED,
        ]
    ):
        entries = acts(connected=i % 2 == 0)
        verify = h.FromHarnessToBrainToolVerifyReq(
            goal="进门",
            entries=[] if i == 0 else [task_memory()] if i == 4 else entries,
            knowledge="门通往室内" if i % 2 else "",
        )
        add("verify", f"variant-{i}", verify)
        summary = task_summary(entries)
        summary.termination = termination
        summary.judge_reason = "" if i % 2 else "检查结果"
        add("summarize_task", f"variant-{i}", summary)
        run = h.FromHarnessToBrainToolSummarizeRunReq(
            run_id="run-1",
            run_goal="出发",
            goals=[] if i % 2 else [goal_entry()],
            episode_memories=[episode_memory()],
            termination=termination,
            judge_reason="" if i % 2 else "检查结果",
            episodes=1,
            succeeded=1 if i == 0 else 0,
            acts_used=2,
            max_episodes=3,
        )
        add("summarize_run", f"variant-{i}", run)
    for i, (reason, raw) in enumerate(
        [
            ("JSON 格式错误", "{broken"),
            ("动作不在空间内", '{"name":"unknown"}'),
            ("缺少 args", ""),
            ("段数超限", "第一行\n第二行"),
        ]
    ):
        cases.append(
            (
                "retry_prompt",
                f"synthetic-retry-{i}",
                {
                    "base_prompt": "基础 prompt\n请输出 JSON。",
                    "attempt": i + 1,
                    "reason": reason,
                    "raw": raw,
                },
            )
        )
    return cases
