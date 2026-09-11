"""judge_success 组装：`Brain.judge()` 用的 prompt，唯一的拼装入口。

**渲染在这，不在 `Brain` 里**——跟 `decide_action` 同一个道理：拼 prompt 是调用方
（Harness）的事，`Brain.judge()` 只认现成的字符串。但 `judge()` 扛着"永远不抛
异常"的契约，渲染搬出来之后这条契约没法再靠 `Brain` 自己的 try/except 兜——
调用方必须自己包一层等价的兜底（把 `build_prompt()` 可能抛的 `KeyError` 吞成
`done=False`），不能让模板缺个占位符就让 `KeyError` 一路冒穿 Harness。

**只有一个输入参数**：`build_prompt()` 收 `JudgeReq`——跟 `Brain.judge()`
共享同一个对象（先拼 prompt，`req.model_copy(update={"prompt": ...})` 回填，
再整个交给 `Brain`），不必为"拼 prompt"和"问模型"各定义一套参数。

**不再单独拼"当前观测"（0909 拍板）**：以前这里从 `req.snapshots[-1]` 另起一份
`$observation`，跟 `$history` 最后一条的"之后变成"是同一份观测、渲染两遍。
judge 第 0 步不问模型（`episode_harness.py::judge()` 的硬编码分支），走到这里
`history` 保证非空，最后一条的"之后变成"本来就是当前这一帧，直接复用即可。
`req.snapshots` 字段随这次改动一并从 `JudgeReq`/
`FromHarnessToBrainToolJudgeReq` 删除（不用的字段不留）。

原来 `JUDGE_BLIND` 常量（挡 `known_objects`/`walk_map`/`landmarks` 三个字段
不让判定器看到）也随这次改动删除——它只用来过滤那份被删掉的"当前观测"，
不是判定器输入的通用防线：`known_objects` 从写入 `StepMemory` 时就被
`SNAPSHOT_BLIND` 挡在外面，历史里从来没出现过；`walk_map` 本来就被
`StepMemory._render_obs()` 挡在历史渲染之外；只有 `landmarks` 是真正被这个
常量单独挡住的，但它一直都在 `$history` 里对判定器可见（`_render_obs()` 不挡
`landmarks`），删掉这份重复的"当前观测"不会让 `landmarks` 新增暴露给判定器，
只是让这份不一致自己消失。**如果以后要真的不让判定器看到 `landmarks`**，
正确的地方是改 `StepMemory._render_obs()`/`render_sequence()`——但那是
`judge`/`verify_and_summarize` 共用的渲染路径，改了会同时影响校验链，这次
不在改动范围内。
"""

from __future__ import annotations

from pokemon_agent.schemas.brain import JudgeReq
from pokemon_agent.memory import render_sequence

from . import load

_TEMPLATE = load("judge_success")


def build_prompt(req: JudgeReq) -> str:
    """拼 `judge()` 用的 prompt。**只读 `req.prompt` 之外的字段**——`prompt`
    是这次调用要回填的输出，不是输入。

    `history` 用 `render(reason=False)`：**发生过的事给判定器看，
    决策者对那件事的主张不给。**

    可能抛 `KeyError`（模板占位符对不上，prompt 是改得最勤的那类文件）——
    调用方负责兜住，见模块文档。

    **渲染用 `render_sequence`**（跟校验链对齐）：`history` 虽然只是
    `JUDGE_HISTORY` 条的小窗口，不像校验链那样全量，但相邻两条之间
    `after`/`before` 重复这件事本身跟窗口大小无关——只要窗口里有连续的
    两步，重复就存在，所以两条链路必须走同一个去重渲染。

    **没有单独的"当前观测"**：`history` 最后一条的"之后变成"就是当前这一帧
    （judge 第 0 步不问模型，走到这里 `history` 保证非空），模板里也不再有
    独立的 `$observation` 占位符——理由见模块文档。
    """
    goal, history = req.goal, req.history
    steps = render_sequence(list(history), reason=False)
    # 包装头用**真实步号**（history[i].step），不用窗口序号——判据里
    # "看到 step=N 就停"指的是轨迹坐标，窗口从 0 重编号会让模型在两套
    # 数字之间对不上号（0909 维度 1 卡 step 3 的事故之一）。
    past = "\n\n".join(
        f"## 第 {entry.step} 步\n{rendered}" for entry, rendered in zip(history, steps, strict=True)
    )
    return _TEMPLATE.render(
        goal=goal.goal,
        criteria=goal.criteria,
        history=past or "（这是第一步，之前什么都没发生）",
    )
