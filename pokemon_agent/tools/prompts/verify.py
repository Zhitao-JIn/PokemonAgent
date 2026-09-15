"""`verify.md` 的装配逻辑：加载、拼装，都在这一个文件里。

服务 `Brain.verify()`——拼好的字符串交给 `BrainTool.verify()`（0913 定案：
prompt 由"拥有这次调用的那个 tool"自己拼），跟 `judge_success` 同一个模式：
信封里**没有 `prompt` 字段**，拼出来的字符串是局部变量，`Brain` 不认识
`pokemon_agent.tools.prompts` 这个包。

**它和 `summarize.py` 曾共用一份 prompt**：`verify`/`summarize` 原本是
`Brain.verify_and_summarize()` 的一次合并调用，模板 `calls/verify_and_summarize.md`
一份问两件事。拆成两次独立调用后（CHANGELOG 第 39 条），prompt 侧同步拆成
`calls/verify.md` + `calls/summarize.md`，组装也跟着拆成同名的两个 `.py`
——一份 prompt 只服务一次调用，模板与装配模块同名，跟
`decide_action.py`/`judge_success.py`/`run_plan.py` 一致。

多帧截图的网格**打包**在 provider 层（`_prepare_images`，按张计费）；prompt
里的网格读法说明是**静态文案，只写死 3 列**，行数由模型看图自己数——0909
拍板撤掉随 n 变化的 `$images_note`，整份 prompt 不再有随帧数变化的文字。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import FromHarnessToBrainToolVerifyReq
from pokemon_agent.schemas.memory import render_sequence

from . import load

_TEMPLATE = load("verify")


def build_prompt(req: FromHarnessToBrainToolVerifyReq) -> str:
    """拼出校验这次调用要问的完整 prompt。

    `entries` 用 `render_sequence()` 去重相邻重复快照、`## 第 i 条` 编号
    （**编号必须与 `entries` 下标一一对应**——`verdicts.index` 要按它落回
    调用方手里的条目，错位就等于判错了对象）；`reason=False`，校验判定看
    "发生了什么"，不该看到决策者自己的说法。
    """
    rendered = render_sequence(list(req.entries), reason=False)
    steps_text = "\n\n".join(f"## 第 {i} 条\n{r}" for i, r in enumerate(rendered))
    return _TEMPLATE.render(
        goal=req.goal,
        steps_text=steps_text or "（本局没有任何步骤记录）",
        knowledge=req.knowledge or "（没有检索到相关领域知识）",
    )
