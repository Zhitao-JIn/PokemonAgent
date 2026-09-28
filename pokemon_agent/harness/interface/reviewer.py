"""`Reviewer`：人与图之间的那扇门——**插话**与**审**两种机制。

**判据只有一条**（`docs/PLAN_console_reviewer.md` §2）：人不满意的那个东西，
是**多字段结构体**（→ 插话）还是**单一结论**（→ 审）。

| | 插话 `inject` | 审 `audit` |
|---|---|---|
| 人不满意的是 | LLM 返回的多字段结构体 | 一个已给的单一结论 |
| 人做什么 | 说一句"不对"（可不说） | 表态：认 / 推翻 |
| 谁出最终结果 | **LLM 带着这句重填** | **人自己** |
| 落点 | **只在 plan 格**（`plan_run` / `plan_episode`） | **只在 `review_and_judge` 格** |

**"接管（人自己按键）"不存在**：`act` 要处理的 `Action` 字段多，人填不了，
所以它也是插话——人**从不手填任何字段**。

**两种机制都是阻塞的**：图停下来、把东西亮给人、等人说完（或直接跳过）再继续。
槽那套的非阻塞语义在这里完全不成立——控制台里人就在图的调用栈上。

**实现必须写在这里**（`harness/interface/`）而不是紧挨 `ConsoleReviewer`：
用户定调"以后还会有别的类"（测试假件、脚本化回放、将来的 TUI）。
`ConsoleReviewer` 只是其中一个实现。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)


@runtime_checkable
class Reviewer(Protocol):
    """人在环里的两个动作：插话（对表单提意见）与审（对结论表态）。"""

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        """**插话**：把一张表单亮给人，收一句反馈。

        req：给人看的说明 + 那个结构体本体。
        后置条件：`resp.text` 是人说的话，**空串 = 人没有意见**（这是常态，不是失败）；
            没人答（超时 / 断连 / 无人值守）时 `text=""`、`answered=False`。
            实现**不重问 LLM**——"带着这句重问"是调用方节点的事（`plan_run` / `plan_episode`）。
        不抛异常：超时阈值由实现自己定。
        """
        ...

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        """**审**：把一条结论亮给人，收一个表态。

        req：这一局的机械结算 + 该局完整 trace。
        后置条件：永远返回一个表态（认 / 推翻）。没人答时按**认账**处理、`answered=False`。
        推翻时 `resp.note` 是理由：审结果时 harness 把它写进表里那一行，
            审裁决时写进本层 `last_judge`——下一次 plan 都看得见。
        """
        ...


__all__ = ["Reviewer"]
