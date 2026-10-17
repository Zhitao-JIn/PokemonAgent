"""judge_success 组装：`Brain.judge()` 用的 prompt，唯一的拼装入口。

**渲染在这，不在 `Brain` 里**——跟 `decide_action` 同一个道理：`Brain.judge()`
只认现成的字符串，"素材 → 文本"是 tool 层的事（0913 定案后调用方是
`BrainTool.judge()`，不是 harness）。`judge()` 自己不再扛"渲染失败也要返回
安全结果"的兜底：那条契约随渲染搬走后由调用方决定怎么处理——本层**不吞**
`build_prompt()` 可能抛的 `KeyError`（模板占位符对不上，是编程错误，
重试修不好）——原样上抛。

**只有一个输入参数**：`build_prompt()` 收 `JudgeReq`——跟 `Brain.judge()` 的
调用点是同一个对象（`BrainTool.judge()` 先拼 prompt、再拿同一个 req 取
`goal`/`history`），不必为"拼 prompt"和"问模型"各定义一套参数。

**调用方是 `BrainTool.judge()`**（0913 定案）：信封里**没有 `prompt` 字段**，
拼出来的字符串是局部变量——harness 只管装素材。

**task 层不再单独拼"当前观测"（0909 拍板）**：以前这里从 `req.snapshots[-1]` 另起一份
`$observation`，跟 `$history` 最后一条的"之后变成"是同一份观测、渲染两遍。
task judge 第 0 步不问模型（`harness/episode/gate/judge.py` 的 `obs.step == 0` 分支），
走到这里 `history` 保证非空，最后一条的"之后变成"本来就是当前这一帧，直接复用即可。
`req.snapshots` 字段随这次改动一并从 `JudgeReq`/
`FromHarnessToBrainToolJudgeReq` 删除（不用的字段不留）。
episode 层无逐步 history，改用 observation 单独渲染当前画面。

原来 `JUDGE_BLIND` 常量（挡 `known_objects`/`walk_map`/`landmarks` 三个字段
不让判定器看到）也随这次改动删除——它只用来过滤那份被删掉的"当前观测"，
不是判定器输入的通用防线：`known_objects` 从写入 `ActMemory` 时就被
`SNAPSHOT_BLIND` 挡在外面，历史里从来没出现过；`walk_map` 本来就被
`ActMemory._render_obs()` 挡在历史渲染之外；只有 `landmarks` 是真正被这个
常量单独挡住的，但它一直都在 `$history` 里对判定器可见（`_render_obs()` 不挡
`landmarks`），删掉这份重复的"当前观测"不会让 `landmarks` 新增暴露给判定器，
只是让这份不一致自己消失。**如果以后要真的不让判定器看到 `landmarks`**，
正确的地方是改 `ActMemory._render_obs()`/`render_sequence()`——但那是
`judge`/`verify`/`summarize` 共用的渲染路径，改了会同时影响校验与蒸馏两条链，这次
不在改动范围内。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq
from pokemon_agent.schemas.memory import render_sequence

from . import READ_SCREEN, load
from .decompose import task_table_lines

_TEMPLATE = load("judge_success")
_INTERRUPT_RULE = load("judge_interrupt").render()


def memory_blocks(req: FromHarnessToBrainToolJudgeReq) -> list[str]:
    """三层判定的记忆素材块：上层详情全文，以及 task 层的一行背景索引。

    唯一真源：`build_prompt()` 与 `BrainTool.judge()` 的 `history` 都调它。
    """
    blocks: list[str] = []
    if req.task_table:
        rows = "\n".join(task_table_lines(req.task_table))
        blocks.append(f"## 本局任务表（成败以此为准，下面各 task 记忆里的成败是机器判定）\n{rows}")
    blocks += [f"## task {m.task_id}\n{m.render()}" for m in req.task_memories]
    blocks += [f"## 局 {m.episode_id}\n{m.render()}" for m in req.episode_memories]
    if req.task_index:
        rows = "\n".join(memory.index_line() for memory in req.task_index)
        blocks.append(f"## 本局内此前同目标的 task（背景，不是本 task 完成的证据）\n{rows}")
    if req.episode_index:
        rows = "\n".join(memory.index_line() for memory in req.episode_index)
        blocks.append(f"## 同目标的过往局(背景,不是本局完成的证据)\n{rows}")
    if req.observation is not None:
        blocks.append(f"## 当前画面\n{req.observation.render()}")
    return blocks


def build_prompt(req: FromHarnessToBrainToolJudgeReq) -> str:
    """拼 `judge()` 用的 prompt。**只读 `req.prompt` 之外的字段**——`prompt`
    是这次调用要回填的输出，不是输入。

    `history` 只含**发生过的事**（给判定器看，
    决策者对那件事的主张不给。**

    可能抛 `KeyError`（模板占位符对不上，prompt 是改得最勤的那类文件）——
    调用方负责兜住，见模块文档。

    **渲染用 `render_sequence`**：task 层 history 是本 task 全部 ActMemory，
    相邻两条的 after/before 边界帧只渲染一次，条目不删。
    task_index 是此前同目标 task 的背景，knowledge 是普遍规律，均不能替代执行证据。

    **task 层没有重复的"当前观测"**：`history` 最后一条的"之后变成"就是当前这一帧
    （judge 第 0 步不问模型，走到这里 `history` 保证非空），模板里也不再有
    独立的 `$observation` 占位符；episode 层 observation 由 memory_blocks 渲染。

    **没有插话**：判定在审格，人只对它表态（认 / 推翻），不带话重问判定员。
    """
    goal, history = req.goal, req.history
    steps = render_sequence(list(history))
    # 包装头用**真实步号**（history[i].step），不用窗口序号——步号在这里只是
    # **坐标**（跟 trace / 记忆里的 step 对得上号），窗口从 0 重编号会让模型在两套
    # 数字之间对不上号（0909 维度 1 卡 step 3 的事故之一）。**判据里已经没有任何
    # 步数条件**（0915 撤：模型只有"达成没有"这一个位，预算用尽由 harness 自己判
    # ——见 `tests/integration/test_harness_integrity.py` 的注释），所以这个数字只是参考信息，
    # 别让模板把它写成规则。
    past = "\n\n".join(
        f"## 第 {entry.step} 步\n{rendered}" for entry, rendered in zip(history, steps, strict=True)
    )
    past = "\n\n".join(filter(None, [past, *memory_blocks(req)]))
    return _TEMPLATE.render(
        goal=goal.goal,
        knowledge=req.knowledge or "（没有检索到相关知识）",
        criteria=goal.criteria,
        history=past or "（这是第一步，之前什么都没发生）",
        interrupt_rule=_INTERRUPT_RULE if req.allow_interrupt else "",
        read_screen=READ_SCREEN,
    )
