"""verify_and_summarize 组装：`Brain.verify_and_summarize()` 用的 prompt，
唯一的拼装入口。多帧截图的网格**打包**在 provider 层
（`ArkProvider._prepare_images`，豆包按张计费）；prompt 里的网格读法说明
是**静态文案，只写死 3 列**，行数由模型看图自己数——0909 拍板撤掉随 n
变化的 `$images_note`，整份 prompt 不再有随帧数变化的文字。

校验（`step_verify`）与蒸馏（`episode_summary`）在同一次 LLM 调用里问，
问题合并成一份 prompt 问。`build_prompt()`
只读 `VerifyAndSummarizeReq` 除 `prompt` 外的字段拼出字符串；调用方
（`EpisodeHarness.verify_and_summarize`）拿到字符串后 `req.model_copy(update=
{"prompt": ...})` 回填，再整个交给 `Brain.verify_and_summarize()`——跟
`judge_success` 是同一个模式，`Brain` 不认识
`pokemon_agent.prompts` 这个包。
"""

from __future__ import annotations

from pokemon_agent.schemas.brain import VerifyAndSummarizeReq
from pokemon_agent.schemas.memory import render_sequence

from . import load

_TEMPLATE = load("verify_and_summarize")


def build_prompt(req: VerifyAndSummarizeReq) -> str:
    """拼出这次合并调用要问的完整 prompt。

    `entries` 用 `render_sequence()` 去重相邻重复快照，`## 第 i 条` 编号；
    `reason=False`（校验判定看"发生了什么"，不该看到决策者自己的说法）。

    **没有 `initial_state`/`final_state` 一节**：这两份观测本来就是
    `steps_text` 第 0/最后一条的"当时看到"/"之后变成"，字面重复一遍，
    还是更贵的版本（`.render()` 带 `walk_map`，`render_sequence()` 走的
    `_render_obs()` 已经把 `walk_map` 砍掉了）。
    """
    rendered = render_sequence(list(req.entries), reason=False)
    steps_text = "\n\n".join(f"## 第 {i} 条\n{r}" for i, r in enumerate(rendered))
    return _TEMPLATE.render(
        goal=req.goal,
        steps_text=steps_text or "（本局没有任何步骤记录）",
        knowledge=req.knowledge or "（没有检索到相关领域知识）",
        result="成功完成" if req.success else "未能完成",
        steps=req.steps,
        max_steps=req.max_steps,
    )
