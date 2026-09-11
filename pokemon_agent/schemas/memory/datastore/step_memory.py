"""单步情景记忆：一条 = 一步。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.world import ObservationFromWorld

SNAPSHOT_BLIND: frozenset[str] = frozenset({"known_objects", "knowledge"})
"""**不进记忆的字段。** 记忆里每一项都必须跨步骤成立，这两项都不成立：

- `known_objects`：跨 episode 的流水，不是"这一帧看到了什么"。
- `knowledge`：语义记忆的检索结果，本来就不是观察。它走
  `ChooseOnceReq.knowledge`（见 `episode_harness.py`），不折进
  `obs.facts`——这一条留着当双保险，万一哪次改动又把它塞回 `obs.facts`，
  这里还能挡一道，不会静默混进记忆。

（`cursor_said` 从源头上就不写进 `facts`——它不该跨步骤比较，无需在此挡。）

除此之外一律照搬。**这里是排除表而不是白名单**，是有意的：新增一个观测字段时，
默认它应该进记忆，需要理由的是把它挡在外面——反过来的话，加字段的人得记得
回来改清单，而忘了改不报错，只表现为某类画面的变化永远看不见。
"""


class StepMemory(BaseModel):
    """一条情景记忆：**我看到这样的画面，因为这些理由，做了这个动作，然后变成了这样。**

    ## 为什么两头都是完整观察

    只记"结果：你在野外"这种一句话，等于把结果压成一个没有信息量的标签
    （十条全长一个样）。**结果本身也是一次观察**，
    只有把它完整记下来，这条经验才回答得了"那一下到底改变了什么"。

    代价是上一条的 `after` 和下一条的 `before` 内容重复。这是有意接受的：
    **每条自成一体**，取回时不用去拼上下文，也不依赖别的条目还在不在。

    ## 这仍然只是 episodic

    "这次尝试里发生了什么"，是自己跑出来的轨迹，有时效。

    不要和**语义记忆**混淆：那是"世界是什么样"（"水克火"、"map 0 的 (5,5) 通往 map 37"），
    自带作用域、在作用域内永远为真。也不要和**目标**混淆：目标有完成态，
    凡是有完成态的都不是知识，它属于运行时状态，不进这里。

    程序记忆、skill library（机制二）、值回填（机制三）都还没做。
    """

    before: ObservationFromWorld = Field(description="做决定时看到的画面")
    rationale: list[str] = Field(description="当时的理由。**不是完整推理**——那留在 trace 里")
    action: str = Field(description="选了什么，含连按次数，如 `right ×2`")
    after: ObservationFromWorld = Field(description="执行之后的画面。**结果也是一次观察**")

    step: int = Field(description="写入时所处的步数")
    episode_id: str = Field(description="这条经验来自哪次尝试")
    run_id: str = Field(
        default="",
        description="这条经验来自哪个 run——checkpoint 恢复的落盘签名三元组之一"
        "（run_id/episode_id/step），由 Harness 盖章（大脑不知道自己在哪个 run）",
    )

    before_frame: str | None = Field(
        default=None,
        description="`before` 对应的截图，**base64 编码后的 PNG 字符串**——"
        "直接是 VLM REST API `image_url` 要拼的那个格式"
        '（`f"data:image/png;base64,{before_frame}"`），不是文件名，也不是'
        "原始字节。存 base64 不存文件名引用——**这条记忆的"
        "`before`/`after` 本来就有跟相邻条目重复的问题**（上一条的 after =="
        "下一条的 before），文字字段重复是接受的成本，这条也一并接受：换来的是"
        "`judge`/`verify_steps` 用的时候不用再去读盘、不用再关心截图文件是否"
        "存在/是否被撞名改了后缀——`store_step_episode_memory()` 写这条记忆时"
        "已经从 `trace_data/<run_id>/screenshot/` 读过一次盘、编码好了，后面全是内存里的字符串。"
        "**可能是 `None`**（那一步感知失败、截图确实没能落盘）——调用方"
        "（`judge`/`verify_steps` 拼请求）按跳过这张图处理，不能因为一步缺图"
        "让整条判定链路失败",
    )
    after_frame: str | None = Field(
        default=None,
        description="`after` 对应的截图，格式同 `before_frame`（base64 编码的"
        "PNG 字符串）。跟 `before_frame` 之间的关系正是 `render_sequence()`"
        "已经在处理的那种重复——相邻两条 `entries[i].after_frame ==`"
        "`entries[i+1].before_frame`（同一帧画面，编码结果自然相等），拼多模态"
        "请求时应该按这一点去重，不要同一张图发两遍，见 `dedup_snapshots()`",
    )

    # `(episode_id, step)` 就是这条记忆的坐标 —— 一步一条，唯一且语义稳定。
    #
    # 不用 trace 的 `event_id`：那是**记录格式的产物**，取决于这一步之间穿插了
    # 多少别的事件，换个记录粒度就变。`step` 是**轨迹坐标**，而机制三沿轨迹
    # 回填折扣正是按 step 走的——用它，回填时不需要任何转换。

    def render(self, *, reason: bool = True) -> str:
        """渲染成进 prompt 的样子。**检索打分也用它**——

        两处用同一份文本，是为了让"被选中的理由"和"看到的内容"是同一个东西。
        分成两份的话，可能出现"按 A 的内容选中，却把 B 的内容喂进去"，而且不报错。

        `reason=False` 去掉「因为」那一行，**只留发生过的事**。判定器用这一版：
        它需要历史（证据可能出现在三步以前的那一帧里），但**绝不能读到决策者的理由**。
        `rationale` 是被评价者自己的说辞——"我已经和母亲说过话了"这种话一旦进了
        判定器的上下文，成功率就变成它自己发的奖状。
        画面、动作、结果是**发生过的事**，理由是**它对那件事的主张**，两者必须分开。

        渲染成进 prompt 的样子，可选择带不带理由。
        """
        because = "；".join(self.rationale) or "（未给出理由）"
        # **前后两份都完整摆出来，结论留给大脑。**
        #
        # 红线：不做“前后一样就折叠成一句「什么都没变」”的折叠——“这一帧
        # 真正会变的字段”清单不可能手工穷举，折叠依据的字段在战斗帧恒等，
        # 会把“这个动作没有效果”的错误结论喂给大脑，而错误的结论比没有
        # 结论贵得多。只摆事实：两份快照字段对齐、顺序固定，变没变由它
        # 自己读。防不去对比的那条，改在决策 prompt 里说（`decide.md`）。
        lines = [
            f"({self.episode_id}, step={self.step}) 当时看到：",
            self._render_obs(self.before),
        ]
        if reason:
            lines.append(f"  因为  {because}")
        lines += [f"  做了  {self.action}", "  之后变成：\n" + self._render_obs(self.after)]
        return "\n".join(lines)

    @staticmethod
    def _render_obs(obs: ObservationFromWorld) -> str:
        """渲染观测快照，**排除 `walk_map`**——它是坐标推理原料（这一屏哪格能走），
        在记忆的前后对比里几乎不变（同一地图内恒定），每条记忆带两份纯属浪费：
        实测一条记忆 1300 字符，其中 walk_map 占 ~800（before+after 各一份），
        而 judge（3 条历史）/ 审计（整局 8 条）都要渲染它，输入就是这么膨胀的。
        「四邻」（北 G 南 G 西 G 东 G）已给出各方向可通行性，撞墙判断够用，
        不需要整张图。"""
        facts = {k: v for k, v in obs.facts.items() if k != "walk_map"}
        return obs.model_copy(update={"facts": facts}).render()

    @staticmethod
    def _snapshot_equal(a: ObservationFromWorld, b: ObservationFromWorld) -> bool:
        """忽略 `step` 号之外，两份观测是否完全一致。"""
        return a.model_copy(update={"step": 0}) == b.model_copy(update={"step": 0})


def render_sequence(entries: list[StepMemory], *, reason: bool = True) -> list[str]:
    """把一串 `StepMemory` 逐条渲成 prompt 用的文本，**首尾相接的边界只渲一次**。

    **问题**：`StepMemory.render()` 每条都完整摆 `before`/`after`——但连续两条
    之间，上一条的 `after` 和下一条的 `before` 内容其实完全相同（`store_step_
    episode_memory()` 是同一份 `pending_observation` 先当这一条的 `after` 存
    一次，下一步 `look()` 只重新盖个 `step` 号，就变成下一条的 `before`）。
    校验器喂的是**整局全量**（不像 `judge` 只取 `JUDGE_HISTORY` 条——具体
    数字见 `episode_harness.py` 里的定义，这里不重复硬编码），逐条渲染就是把
    每一帧连续存两遍，长局的 prompt 长度直接翻倍。

    **保留全量、只去重渲染**：这里不砍步数（校验器仍然看得到每一步），只在
    相邻两条**确认首尾相接**（`entries[i].step + 1 == entries[i+1].step` 且
    内容一致，用 `_snapshot_equal` 忽略 step 号比较）时，把下一条的"当时看到"
    换成一句指回上一条"之后变成"的提示，不重复贴一遍内容；不连续（比如某步
    因为权限被拒没落库、或调用方本来就传了不连续的子集）时，各自照常完整
    渲染，不猜测省略——这跟 `StepMemory` 本身"每条自成一体、不依赖别的条目
    还在不在"的设计并不冲突：**省的是渲染，不是存储**，条目本身仍然各自完整。

    返回值跟 `entries` 一一对应（长度相同、顺序不变），方便调用方按 index
    各自加编号/包装——`step_verify.py` 用来配 `## 第 i 条`，`StepVerifyVerdict.
    index` 才对得上号；这里不做编号，编号是调用方的事。
    """
    rendered: list[str] = []
    prev: StepMemory | None = None
    for entry in entries:
        because = "；".join(entry.rationale) or "（未给出理由）"
        if (
            prev is not None
            and prev.step + 1 == entry.step
            and StepMemory._snapshot_equal(prev.after, entry.before)
        ):
            # 去重只省画面内容，**条目头必须保留**：头里的 step 号是判定器
            # 执行"看到 step=N 就停"这类步数判据的唯一依据——整段替换掉
            # 的话，窗口里最后一条（恰恰是判停要看的那个步号）在 prompt 里
            # 没有数字，判据永远等不到信号（0909 维度 1 卡 step 3 的事故）。
            before_block = (
                f"({entry.episode_id}, step={entry.step}) 当时看到："
                "（同上一条「之后变成」，同一帧，不重复贴）"
            )
        else:
            before_block = (
                f"({entry.episode_id}, step={entry.step}) 当时看到：\n"
                + StepMemory._render_obs(entry.before)
            )
        lines = [before_block]
        if reason:
            lines.append(f"  因为  {because}")
        lines += [
            f"  做了  {entry.action}",
            "  之后变成：\n" + StepMemory._render_obs(entry.after),
        ]
        rendered.append("\n".join(lines))
        prev = entry
    return rendered


def dedup_snapshots(
    entries: list[StepMemory],
) -> tuple[list[str], list[ObservationFromWorld]]:
    """把一串 `StepMemory` 摊平成 `(before, after, before, after, ...)` 的观测
    序列，去重后**一次遍历、一口气**返回两条严格对齐的列表：截图（base64
    字符串，喂 `VisionDescribeReq.images`）和它们各自对应的 `ObservationFromWorld`
    （给调用方转文字，比如"当前观测"要渲成 `$observation`）。**两条列表长度、
    顺序永远一一对应**——`frames[i]` 就是 `snapshots[i]` 这份观测的那张截图。

    两条列表由构造保证一一对应，调用方不必自己论证“这个索引对应那份观测”
    （靠“最后一条的 after 就是当前观测”去猜索引，只在 history 非空且连续时
    成立，猜错了没人报错、只是悄悄喂错内容）。不需要 `snapshots` 的调用方
    用 `_` 丢弃第二个返回值。

    去重规则不变（跟 `render_sequence()` 是同一件事的图片版）：相邻两条之间
    `entries[i].after_frame` 和 `entries[i+1].before_frame` 本来就是同一帧
    画面（`store_step_episode_memory()` 是同一份观测先存成上一条的 after，
    下一步 `look()` 盖个 step 号变成下一条的 before，编码结果自然相等），
    图片不该重复发一遍——每多发一张图，多模态请求就多花一份 token。去重只看
    **字符串是否等于上一张已经收进来的**：同一帧画面编出来的 base64 永远
    逐字节相等，不会出现"内容相同但字符串不同"需要额外判断的情况；反过来，
    不连续的两条（比如中间有一步权限被拒没能落库）编码结果天然不同，不会
    被误判成重复。

    **没有截图的观测不进这两条列表**（`before_frame`/`after_frame` 为
    `None`，比如那一步感知失败没能落盘）——它们既进不了图片列表，就没有
    "这张图对应哪份观测"这件事，两条列表必须永远等长，宁可这份观测彻底不
    出现，也不能让长度对不上。
    """
    frames: list[str] = []
    snapshots: list[ObservationFromWorld] = []
    for entry in entries:
        for obs, frame in ((entry.before, entry.before_frame), (entry.after, entry.after_frame)):
            if frame is None:
                continue
            if frames and frames[-1] == frame:
                continue
            frames.append(frame)
            snapshots.append(obs)
    return frames, snapshots
