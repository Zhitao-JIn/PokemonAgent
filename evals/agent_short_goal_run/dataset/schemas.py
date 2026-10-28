"""样本契约（`docs/eval/spec.md` §四）：起点 + 目标 + 机械判据 + rubric + 红线。

四要素对应：manifest = `start`、prompt = `goal`、可行 behavior = `behavior`、
rubric = `rubric` + `red_lines`。
v1 的样本从 run 入口跑完一个单目标 run（`granularity="run"`）。

**档位（`tier`）与冻结内容（`goals`）**：长期档只给 run goal，目标表由 planner 建（现状）；
中期档把 episode 目标表写死在样本里（`goals`，各自不带 task）；短期档再把每局的 task 表
写死（`goals[i].tasks`）。三档与冻结开关一一对应（见 `solver/runner/one.py`），
一致性由 `loader` 在加载期检查。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SampleStart(BaseModel):
    """样本起点为版本目录内的原始 `.state` 文件及其内容哈希。"""

    kind: Literal["archive", "state"]
    archive: str = Field(default="", description="旧数据兼容字段；读取时忽略")
    source_state: str = Field(description="原始 .state（版本相对路径）")
    source_sha256: str = Field(description="原始 .state 的字节哈希")


class SampleTask(BaseModel):
    """短期档冻结的一个 task（`task_id` 由评测入口按样本 id 编号，不在数据里写）。"""

    goal: str = Field(description="这一步要做什么")
    success_criteria: str = Field(description="给 agent 内部 judge 的判据原文")
    max_steps: int = Field(gt=0, description="这一步的键预算")


class SampleGoal(BaseModel):
    """中期 / 短期档冻结的一个 episode 目标（可带冻结的 task 表）。"""

    goal: str = Field(description="本局目标")
    success_criteria: str = Field(description="本局判据原文")
    max_steps: int = Field(gt=0, description="本局建议的 task 数")
    tasks: list[SampleTask] = Field(
        default_factory=list, description="冻结的 task 表（短期档必填、中期档必须为空）"
    )


class RubricLevel(BaseModel):
    """rubric 的一档。"""

    score: int
    anchor: str = Field(description="这一档长什么样")


class RubricItem(BaseModel):
    """路径层 rubric 的一条（v1 打分：0–2 三档）。"""

    item_id: str
    question: str
    levels: list[RubricLevel]
    grader: Literal["code", "human", "model"]
    applies_to: Literal["task", "episode", "run"]


class RedLine(BaseModel):
    """红线：命中即判负，不参与加权。判法写在 `evals/report/redlines.py`。"""

    line_id: str
    question: str


class Rubric(BaseModel):
    """一个数据集版本的 rubric 与红线定义（`dataset/<版本>/rubric.json`）。"""

    version: str
    items: list[RubricItem]
    red_lines: list[RedLine]


class InitialMemory(BaseModel):
    """版本目录内冻结记忆种子的相对目录及 MANIFEST.json 字节哈希。"""

    path: str
    manifest_sha256: str


class EvalSample(BaseModel):
    """一条样本。"""

    sample_id: str = Field(description="与目标的 task_id 同值（episode_start.goal_id 就是它）")
    dataset_version: str
    granularity: Literal["task", "episode", "run"] = "run"
    tier: Literal["short", "mid", "long"] = Field(
        default="long",
        description="评测档位：long 只给 run goal（现状）；mid 冻结目标表；"
        "short 连 task 表一起冻结",
    )
    category: str
    start: SampleStart
    goal: str = Field(description="run 的唯一初始目标（prompt）")
    success_criteria: str = Field(
        description="给 agent 内部 judge 的判据原文；被测对象的输入，不是真值"
    )
    max_steps: int = Field(gt=0)
    goals: list[SampleGoal] = Field(
        default_factory=list, description="冻结的 episode 目标表（long 档必须为空）"
    )
    initial_memory: InitialMemory | None = None
    knowledge_exclude_topics: list[str] = Field(default_factory=list)
    initial_state_hint: str = ""
    behavior: str = Field(description="可行 behavior：合理路径的边界描述，路径层 rubric 的参照")
    check_id: str | None = Field(
        description="机械判据 id（`evals/checks` 注册表）；None = 不可机械判定"
    )
    rubric: list[str] = Field(description="适用的 rubric 条目 id")
    red_lines: list[str] = Field(description="适用的红线 id")
    k_metric: Literal["pass_at_k", "pass_hat_k"]
    split: Literal["train", "val", "test"]


__all__ = [
    "EvalSample",
    "InitialMemory",
    "RedLine",
    "Rubric",
    "RubricItem",
    "RubricLevel",
    "SampleGoal",
    "SampleStart",
    "SampleTask",
]
