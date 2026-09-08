"""judge_success 组装：`Brain.judge()` 用的 prompt，唯一的拼装入口。

**渲染在这，不在 `Brain` 里**——跟 `decide_action` 同一个道理：拼 prompt 是调用方
（Harness）的事，`Brain.judge()` 只认现成的字符串。但 `judge()` 扛着"永远不抛
异常"的契约，渲染搬出来之后这条契约没法再靠 `Brain` 自己的 try/except 兜——
调用方必须自己包一层等价的兜底（把 `build_prompt()` 可能抛的 `KeyError` 吞成
`done=False`），不能让模板缺个占位符就让 `KeyError` 一路冒穿 Harness。

**只有一个输入参数**：`build_prompt()` 收 `FromBrainToolToBrainJudgeReq`——跟 `Brain.judge()`
共享同一个对象（先拼 prompt，`req.model_copy(update={"prompt": ...})` 回填，
再整个交给 `Brain`），不必为"拼 prompt"和"问模型"各定义一套参数。
"""

from __future__ import annotations

from pokemon_agent.schemas.communication import FromBrainToolToBrainJudgeReq
from pokemon_agent.schemas.datastore import render_sequence

from . import load

JUDGE_BLIND: frozenset[str] = frozenset(
    {
        "known_objects",
        "walk_map",
        "landmarks",
    }
)
"""判定器**看不到**的字段。判定器现在有历史了（`history` 参数），
但那份历史是**有界的**：只有本局、只有最近几步。这几个字段是无界的，所以挡掉。

- `known_objects`：**跨 episode 的流水**。「见过 7 次，互动 1 次」「他说过 XXX」
  ——上一局说过的那句话会留在里面，目标是"和母亲对话"时，
  它足以让判定器在**第 0 步**就判完成，而这一局什么都还没发生。
  `history` 之所以安全正是因为它两头有界；这一份没有那个界。
- `walk_map` / `landmarks`：**堵掉坐标推理的原料**。
  光在 prompt 里写"别做坐标换算"是不够的——实测它照做了：
  把 `walk_map` 的行号当成全局 y，得出"他还没进屋"，而 `map_id` 明写着他在屋里。
  拿不到就不会用。位置证据由 `where` 一行直接给出，那是答案，不是原料。
**这是一份黑名单而不是白名单**，方向是刻意选的：漏进一个新字段，代价是判定器
多看一眼；漏掉一个新字段，代价是判定器瞎掉——`dialog_text` 那次就是后者，
判定器一路在说"对话框内容未提供"，一局本该成功的 episode 被静默记成失败。
两种失败模式不对称，所以宁可多给。
"""

_TEMPLATE = load("judge_success")


def build_prompt(req: FromBrainToolToBrainJudgeReq) -> str:
    """拼 `judge()` 用的 prompt。**只读 `req.prompt` 之外的字段**——`prompt`
    是这次调用要回填的输出，不是输入。

    `history` 用 `render(reason=False)`：**发生过的事给判定器看，
    决策者对那件事的主张不给。** `JUDGE_BLIND` 挡掉的是同一条隔离的另一半。

    可能抛 `KeyError`（模板占位符对不上，prompt 是改得最勤的那类文件）——
    调用方负责兜住，见模块文档。

    **渲染用 `render_sequence`**（跟校验链对齐）：`history` 虽然只是
    `JUDGE_HISTORY` 条的小窗口，不像校验链那样全量，但相邻两条之间
    `after`/`before` 重复这件事本身跟窗口大小无关——只要窗口里有连续的
    两步，重复就存在，所以两条链路必须走同一个去重渲染。

    **"当前观测"读 `req.snapshots[-1]`**：`snapshots` 跟 `req.images` 是
    `step_memory.dedup_snapshots()` 同一次遍历一并算出来的，`snapshots[-1]`
    与 `images` 里最后一张截图严格对应同一份观测——不用靠"最后一条 history
    就是当前观测"这条推理去翻 `history[-1].after`（调用方在 history 为空的
    第 0 步已经直接不问
    模型，所以这里只要跑到，正常情况下 `snapshots` 非空）。`snapshots`
    仍可能因为上一步落库被权限拒绝、或那一步截图确实没能落盘而意外为空——
    这时退化成"（这一步之前没有任何观测）"，不抛异常，跟 `history` 本身为空
    时的降级（"这是第一步，之前什么都没发生"）是同一个取舍：宁可这一步
    判定器少看一点，不该让 build_prompt() 崩掉。
    """
    goal, history, snapshots = req.goal, req.history, req.snapshots
    current = snapshots[-1] if snapshots else None
    rendered = (
        (
            "\n".join(f"- {k}: {v}" for k, v in current.facts.items() if k not in JUDGE_BLIND)
            or current.status
        )
        if current is not None
        else "（这一步之前没有任何观测）"
    )
    steps = render_sequence(list(history), reason=False)
    past = "\n\n".join(f"## 第 {i} 条\n{r}" for i, r in enumerate(steps))
    return _TEMPLATE.render(
        goal=goal.goal,
        criteria=goal.criteria,
        observation=rendered,
        history=past or "（这是第一步，之前什么都没发生）",
    )
