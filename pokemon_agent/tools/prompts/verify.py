"""`verify.md` 的装配逻辑：加载、拼装，都在这一个文件里。

服务 `Brain.verify()`——拼好的字符串交给 `BrainTool.verify()`（0913 定案：
prompt 由"拥有这次调用的那个 tool"自己拼），跟 `judge_success` 同一个模式：
信封里**没有 `prompt` 字段**，拼出来的字符串是局部变量，`Brain` 不认识
`pokemon_agent.tools.prompts` 这个包。

**两级校验共用这一份模板**（0923 192）：task 层标 ActMemory（对照 task
goal）、episode 层标 TaskMemory（对照本局 goal）。渲染分家：ActMemory 走
`render_sequence()`（相邻首尾相接的快照只渲一次），TaskMemory 一条一个
task、各自独立渲染——一条调用只装一种素材（信封契约），按首条的类型分流。

多帧截图的网格**打包**在 provider 层（`_prepare_images`，按张计费）；prompt
里的网格读法说明是**静态文案，只写死 3 列**，行数由模型看图自己数——0909
拍板撤掉随 n 变化的 `$images_note`，整份 prompt 不再有随帧数变化的文字。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import FromHarnessToBrainToolVerifyReq
from pokemon_agent.schemas.memory import ActMemory, TaskMemory, render_sequence

from . import load

_TEMPLATE = load("verify")


def build_prompt(req: FromHarnessToBrainToolVerifyReq) -> str:
    """拼出校验这次调用要问的完整 prompt。

    `entries` 逐条渲成 `## 第 i 条`（**编号必须与 `entries` 下标一一对应**
    ——`verdicts.index` 要按它落回调用手里的条目，错位就等于判错了对象）。
    ActMemory 用 `render_sequence()` 去重相邻重复快照；TaskMemory 各自
    `render()`。一次调用只装一种素材（信封契约），按首条类型分流。
    """
    entries = list(req.entries)
    if entries and isinstance(entries[0], TaskMemory):
        rendered = [entry.render() for entry in entries]
    else:
        rendered = render_sequence([e for e in entries if isinstance(e, ActMemory)])
    steps_text = "\n\n".join(f"## 第 {i} 条\n{r}" for i, r in enumerate(rendered))
    return _TEMPLATE.render(
        goal=req.goal,
        steps_text=steps_text or "（本局没有任何步骤记录）",
        knowledge=req.knowledge or "（没有检索到相关领域知识）",
    )
