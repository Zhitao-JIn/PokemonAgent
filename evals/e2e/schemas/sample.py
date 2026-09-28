"""样本契约（`docs/eval/spec.md` §四）：起点 + 目标 + 机械判据 + rubric + 红线。

四要素对应：manifest = `start`、prompt = `goal`、可行 behavior = `behavior`、
rubric = `rubric` + `red_lines`。
v1 的样本从 run 入口跑完一个单目标 run（`granularity="run"`）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SampleStart(BaseModel):
    """样本的起点。

    `run_begin`：钉死 `.state` + 目标，批跑时现打包成 run 级存档再 `restore_run`（存档带
    `state_schema_hash`，状态结构一变旧档即拒载，所以冻结的是源、不是存档）。
    `recovered_episode`：真实 run 留下的 episode 级存档，原样恢复。
    """

    kind: Literal["run_begin", "recovered_episode"]
    state_path: str = Field(default="", description="run_begin：钉死 .state，仓库相对路径")
    state_sha256: str = Field(default="", description="run_begin：.state 的哈希，冻结校验")
    checkpoint_root: str = Field(default="", description="recovered_episode：原 run 的存档根")
    manifest_path: str = Field(default="", description="recovered_episode：episode 级清单路径")
    memory_root: str = Field(default="", description="recovered_episode：原 run 的记忆根（含快照）")

    @model_validator(mode="after")
    def _fields_match_kind(self) -> SampleStart:
        """两种起点各自的必填项。"""
        if self.kind == "run_begin" and not (self.state_path and self.state_sha256):
            raise ValueError("run_begin 起点要有 state_path 与 state_sha256")
        if self.kind == "recovered_episode" and not (self.checkpoint_root and self.manifest_path):
            raise ValueError("recovered_episode 起点要有 checkpoint_root 与 manifest_path")
        return self


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


class EvalSample(BaseModel):
    """一条样本。"""

    sample_id: str = Field(description="与目标的 task_id 同值（episode_start.goal_id 就是它）")
    dataset_version: str
    granularity: Literal["task", "episode", "run"] = "run"
    category: str
    start: SampleStart
    goal: str = Field(description="run 的唯一初始目标（prompt）")
    success_criteria: str = Field(
        description="给 agent 内部 judge 的判据原文；被测对象的输入，不是真值"
    )
    max_steps: int = Field(gt=0)
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
    "RedLine",
    "Rubric",
    "RubricItem",
    "RubricLevel",
    "SampleStart",
]
