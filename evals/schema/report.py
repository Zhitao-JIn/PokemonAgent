"""报告的口径头与 bad case 记录（`docs/eval/spec.md` §六、§十）。

口径头在批跑开始时写进 `header.json`；两份报告除 `report_id` / `created_at` / `git_commit`
外任一项不同，`diff` 拒绝对比。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

COMPARABLE_FIELDS: tuple[str, ...] = (
    "git_dirty",
    "models",
    "config",
    "dataset_version",
    "samples_sha256",
    "rubric_version",
    "knowledge",
    "k",
    "deps",
    "epochs",
    "speed",
    "timeout",
    "rule_ids",
)
"""`diff` 要求两份报告逐项相同的口径字段。"""


class ReportHeader(BaseModel):
    """一次测评的口径。"""

    report_id: str
    created_at: str
    git_commit: str
    git_dirty: bool
    models: dict[str, str]
    config: dict[str, str] = Field(description="`pokemon_agent.config` 全部旋钮的快照")
    dataset_version: str
    samples_sha256: str = Field(description="本次所跑样本定义的整体哈希")
    rubric_version: str
    knowledge: str = Field(description="知识库目录的哈希；关掉知识时为 off")
    k: int = 1
    deps: dict[str, str] = Field(
        default_factory=dict, description="关键依赖版本（inspect-ai / pyboy / pydantic / 本包）"
    )
    epochs: int = Field(default=1, ge=1, description="每样本重复次数（V2；R3 起 eval_set 传真值）")
    speed: int = Field(default=0, description="模拟器速度旋钮（0 = 不限速）")
    timeout: int = Field(default=3600, description="单条样本的超时秒数")
    rule_ids: list[str] = Field(default_factory=list, description="本批样本用到的机械判据 id")
    sample_ids: list[str] = Field(default_factory=list)


class BadCase(BaseModel):
    """bad case 登记：只存指针与归类状态，只追加不删除。"""

    report_id: str
    sample_id: str
    run_id: str
    trigger: Literal["red_line", "mech_fail", "judge_fp", "judge_fn"]
    evidence: list[str] = Field(default_factory=list)
    reason: str
    triage: Literal["pending", "coverage", "criterion", "agent"] = "pending"
    cause: Literal["", "prompt", "skill", "model", "tool", "harness"] = Field(
        default="",
        description="归因类别（人工填）：prompt / skill / 模型能力 / 工具能力 / harness 流程",
    )


__all__ = ["COMPARABLE_FIELDS", "BadCase", "ReportHeader"]
