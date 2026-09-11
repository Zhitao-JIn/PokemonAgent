"""`BrainTool` → `Brain` 这一跳的校验+蒸馏请求协议：
`VerifyAndSummarizeReq`。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import StepMemory


class VerifyAndSummarizeReq(BaseModel):
    """**递给合并调用的请求**：本局全部 step 记忆 + 检索到的领域知识（校验要用）+
    这一局的结算信息（摘要要用），加上这次问模型用的 prompt。**模块间调用只认
    一个输入参数**——这份 req 同时是
    `pokemon_agent.prompts.verify_and_summarize.build_prompt()` 的输入和
    `Brain.verify_and_summarize()` 的输入，两边共享同一个对象，跟其余三个
    `Brain` 方法（`choose_once`/`judge`）同规则。

    前六个字段（goal 到 images）服务校验；后三个字段（success 到
    max_steps）服务摘要——`key_steps` 不必再单独传，就是
    `entries` 本身（校验判完可信之后，模型自己在同一次输出里只引用可信的
    那部分，不需要调用方先过滤一遍再传一份"已过滤"的列表）。

    **没有 `initial_state`/`final_state`**：这两份观测的内容本来就在
    `entries` 里，`build_prompt()` 拼 `steps_text` 时（`render_sequence()`）
    已经把它们渲成了第 0 条的"当时看到"和最后一条的"之后变成"，字面重复
    一遍纯属浪费 token，而且 `.render()` 比 `render_sequence()` 用的
    `_render_obs()` 更贵（前者带 `walk_map`，后者已经砍掉）。
    """

    goal: str = Field(description="本局目标（判定动作意图、写摘要都要用）")
    entries: list[StepMemory] = Field(description="本局 step 记忆，按 step 升序，全量（未过滤）")
    knowledge: str = Field(default="", description="检索到的领域知识文本，可能为空")
    images: list[str] = Field(
        default_factory=list,
        description="要带的截图（base64 编码的 PNG 字符串，按 entries 用 "
        "`dedup_snapshots()` 去重后的顺序；verify 走豆包，多帧会由 "
        "`ArkProvider._prepare_images` 在发送前拼成一张网格图），默认空列表",
    )
    prompt: str = Field(default="", description="拼好的完整 prompt，构造时留空")

    episode_id: str = Field(
        default="", description="这一局的标识；组装 EpisodeMemory 用，判定不依赖"
    )
    run_id: str = Field(default="", description="本次实验标识；组装 EpisodeMemory 用，判定不依赖")

    success: bool = Field(description="这一局是否成功完成")
    steps: int = Field(ge=0, description="实际完成步数")
    max_steps: int = Field(ge=1, description="最大允许步数")
