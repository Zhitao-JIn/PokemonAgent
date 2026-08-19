"""跨层传递的数据模型。

这里的每个模型都是**接口契约的一部分**：只要出现在 `interfaces/` 的签名里，
它的字段含义就是各层之间的共识，改字段等于改接口。

设计约束（来自 CLAUDE.md 铁律 4）：跨层一律用这里的模型，不用裸 dict。

## 这个文件装着两类东西，边界在中间那道分隔线

上半部分是**跨层契约**：`Task` / `Observation` / `Action` / `TraceEvent` 等，
它们出现在 `interfaces/` 的签名里，改字段等于改接口。

下半部分是**感知层的模型**：`Scene` / `Overlay` / `ScreenState` 等。
它们一次都没出现在任何 Port 的签名里——`ScreenState` 由 `PyBoyWorld` 产出、
就地压成 `Observation.facts` 里的字符串，不跨层传递。

**大脑不该 import 下半部分的任何东西。** 以前这是导入图强制的（`react.py` 只认识
`core`，拿不到 `Scene` 这个名字），合并之后只剩纪律。一旦大脑开始按 `scene` 分支，
分层就名存实亡了——这条现在得靠人守。

两半的版本纪律也不同：上半由 `TRACE_SCHEMA_VERSION` 管事件形状，
下半的 `Scene` / `Overlay` 受 append-only 约束（机制三的 `(state-key, action) -> value`
一旦开始积累，枚举值只能增不能改）。改任何一边之前先看清自己在哪一半。
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class Task(BaseModel):
    """一个有明确成败判据的任务。**episode 的边界就是任务的边界。**

    为什么不用"通关"做 episode：通关是几千步、只产出一个 0/1 结果，
    机制三的蒙特卡洛回填折扣一路乘下去，回填到前期步骤上几乎是噪声；
    评测也只能报"通关了没有"这一个二值数字。任务级则能报成功率、失败模式分布、
    有记忆 vs 无记忆的对比。

    但任务有**下界**：必须长到单靠上下文装不下、必须跨任务复用经验才做得好，
    否则记忆架构就失去了存在理由。"打赢二号道馆"合适，"和 NPC 说句话"不合适。
    """

    task_id: str = Field(description="任务标识，同一任务的多次尝试共用它")
    goal: str = Field(description="给 LLM 读的目标描述，会进 prompt")
    success_criteria: str = Field(description="成败判据的人类可读描述；判定由 world 实现")
    max_steps: int = Field(description="步数上限，超出即判失败。> 0")


class Observation(BaseModel):
    """大脑在某一步看到的世界。

    只放**大脑决策需要的**信息。原始画面、模拟器内部状态不进这里——
    那些属于 harness，大脑看不到也不该看到。
    """

    step: int = Field(description="本 episode 内的第几步，从 0 开始")
    goal: str = Field(description="当前任务目标。大脑必须知道自己在干嘛，否则无从选择动作")
    summary: str = Field(description="给 LLM 读的自然语言状态描述")
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="结构化状态字段（位置、HP、持有道具…）。机制一的 state key 未来从这里派生",
    )
    done: bool = Field(default=False, description="episode 是否已终止（成功、失败或超步数）")
    success: bool = Field(
        default=False,
        description="任务是否达成。**只在 done 为 True 时有意义**，否则恒为 False",
    )


class ActionSpace(BaseModel):
    """当前状态下**可用**的动作集合（state-dependent action masking）。

    注意语义：这不是"全部动作"，是"此刻允许的动作"。动作空间不增长，
    增长的是掩码之外的 skill library（本阶段不做）。
    """

    names: list[str] = Field(description="可用动作名，非空")
    descriptions: dict[str, str] = Field(
        default_factory=dict, description="动作名 -> 给 LLM 读的说明"
    )
    note: str = Field(
        default="",
        description="关于整个动作空间的说明（如连按怎么用），不属于任何单个动作。"
        "**必须有这个字段**：prompt 只渲染 names 里的动作说明，"
        "塞进 descriptions 的额外条目永远不会被渲染出去",
    )

    def contains(self, name: str) -> bool:
        return name in self.names


MAX_RATIONALE = 3
"""一个动作最多带几条论据。

抽成常量是因为它有两个执行点——`Action` 的字段约束（数据契约）和 `_parse`
（外部输入校验）。两处必须同源，否则模型给 4 条时会得到一个自相矛盾的系统：
解析器放行、构造时炸。
"""


class Action(BaseModel):
    """大脑选出的一个动作。

    它带着三样东西过来，服务于三个不同的消费方，**不要合并**：

    - `name` / `args` —— 给世界执行。
    - `thought` —— 完整推理，**只进 trace**，不参与任何后续决策。
      不设长度上限：它的长度就是模型这一步的算力，压缩它压的是思考本身，
      不是日志体积。
    - `rationale` —— 最能支持这个动作的论据，**进 memory**，会被未来的步骤检索回去。

    为什么进记忆的是论据而不是结论：结论（"所以该捡药水"）可以从 `name` 反推，
    存进去等于把同一件事存两遍；论据（"地上有药水而我手上没有"）才是 `name`
    里没有的信息。更要紧的是论据是**适用条件**——未来取回这条经验时可以检查
    它现在还成不成立，结论做不到这件事。

    论据一律按**有时效**处理，不区分持久与否。持久知识（"馆主是火属性"）的
    跨 episode 复用属于 skill library（机制二），本阶段不做。
    """

    name: str = Field(description="动作名，必须来自当时的 ActionSpace")
    args: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "动作参数。**当前没有任何消费方**——所有动作都是无参的，world 只按 name 分发。"
            "为宏动作（带参数的按键序列）预留"
        ),
    )
    thought: str = Field(
        min_length=1,
        description="选择该动作的完整推理。只进 trace，不进 memory，不影响后续决策",
    )
    rationale: list[str] = Field(
        min_length=1,
        max_length=MAX_RATIONALE,
        description=f"最能支持该动作的论据，1-{MAX_RATIONALE} 条。"
        "进 memory；经验能否迁移全看它",
    )


class ToolResult(BaseModel):
    """一次动作执行的结果。"""

    ok: bool = Field(description="是否成功执行。失败不抛异常，因为动作失败是预期内的游戏事件")
    message: str = Field(default="", description="给 LLM 读的结果描述")
    observation: Observation | None = Field(
        default=None, description="执行后的新观测；None 表示调用方需另行 perceive()"
    )


class MemoryEntry(BaseModel):
    """一条记忆。

    本阶段只有 **episodic**：这次任务尝试里发生了什么，是自己跑出来的轨迹。
    作用域 = 一个 episode = 一次任务尝试。

    不要和 **semantic** 混淆：semantic 是**外部领域知识**（"水属性克制火属性"、
    某道馆馆主用什么属性），来自攻略/图鉴，不是自己跑出来的，也不随 episode 结束而失效。
    跨任务复用的成功经验既不是 semantic，也应当先归到 episodic 的聚合，
    或晋升后进 skill library（机制二）。

    semantic 记忆与值回填都留到后面的机制，本阶段不做。
    """

    key: str = Field(description="state abstraction 产出的语义 key，本阶段用 step 占位")
    content: str = Field(description="记忆正文")
    step: int = Field(description="写入时所处的步数")
    episode_id: str = Field(description="这条经验来自哪次尝试")

    # `(episode_id, step)` 就是这条记忆的坐标 —— 一步一条，唯一且语义稳定。
    #
    # 不用 trace 的 `event_id`：那是**记录格式的产物**，取决于这一步之间穿插了
    # 多少别的事件，换个记录粒度就变。`step` 是**轨迹坐标**，而机制三沿轨迹
    # 回填折扣正是按 step 走的——用它，回填时不需要任何转换。
    #
    # 要在 trace 里定位这条记忆，按 `(episode_id, step, MEMORY_WRITE)` 过滤即可。


class EpisodeOutcome(BaseModel):
    """一次任务尝试的最终结果。

    这是评测与机制三的输入：成功率按 task_id 分组统计，
    MC 回填拿 success 作为 episode 的最终回报沿轨迹往回传。
    """

    episode_id: str = Field(description="本次尝试的标识")
    task_id: str = Field(description="尝试的是哪个任务")
    success: bool
    steps: int = Field(description="实际用了多少步")
    reason: str = Field(description="终止原因：success / failed / max_steps_exceeded / error")


TRACE_SCHEMA_VERSION = 2
"""事件形状的版本号。

**必须有。** 事件形状还会变（这一版就是第二版），而老 JSONL 被新解析器读时
不会报错，只会**静默读错**——少一个字段就当它是空的，多一个就忽略。
版本号让「这批数据是旧格式」变成一句可判断的话。
"""


class Source(str, Enum):
    """事件由哪一层产生。

    **每种聚合几乎都要按它切**：感知和决策各烧多少 token、失败集中在哪一层、
    延迟花在哪。放信封不放 payload，就是因为它是横切的。
    """

    PERCEPTION = "perception"   # 视觉模型这条链
    DECISION = "decision"       # 文本模型这条链
    HARNESS = "harness"         # 掩码、记忆、生命周期
    WORLD = "world"             # 模拟器


class EventType(str, Enum):
    """trace 事件类型。"""

    EPISODE_START = "episode_start"
    EPISODE_END = "episode_end"
    OBSERVE = "observe"
    MODEL_CALL = "model_call"
    THINK = "think"
    ACT = "act"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    ERROR = "error"
    CHECKPOINT = "checkpoint"


class TraceEvent(BaseModel):
    """追加写的 trace 事件。

    这是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因
    的共同底座，所以它是**不可变的事件**，不是可变的状态快照——
    不要往里加"当前状态"这类字段，那样就没法重放了。
    """

    event_id: int = Field(description="全局单调递增，SSE 断线重连靠它补发。**排序的唯一依据**")
    run_id: str = Field(
        description="哪一次实验。**manifest 的 join key**——"
        "没有它，一份记着模型与 prompt 的 manifest 和一堆事件对不上"
    )
    episode_id: str = Field(description="所属 episode")
    step: int = Field(description="发生在第几步。**不是主键**——一步内有多条事件")
    type: EventType
    source: Source = Field(description="由哪一层产生。成本拆分与失败归因都按它切")
    payload: dict[str, str] = Field(default_factory=dict, description="该类型的结构化内容")
    ts: float = Field(
        description="Unix 时间戳，秒。用于算延迟与对齐外部日志；"
        "**不能替代 event_id 排序**——同毫秒多条事件、时钟回拨都会让时间序失真"
    )
    schema_version: int = Field(default=TRACE_SCHEMA_VERSION)


# =====================================================================
#  以下是**感知层**的模型 —— 一帧画面被解析成什么
#
#  它们不跨层：由 `PyBoyWorld` 产出并就地转成 `Observation`，
#  一次都不出现在 `interfaces/` 的签名里。大脑看的是上半部分的 `Observation`。
# =====================================================================

class Scene(str, Enum):
    """你在什么场合。决定**要读哪些字段**。"""

    FIELD = "field"          # 野外：城镇、路线，可自由走动
    INDOOR = "indoor"        # 室内：研究所、民宅、道馆内部
    BATTLE = "battle"        # 战斗中
    MENU = "menu"            # 系统菜单：START 菜单 / 背包 / 精灵列表 / 状态页
    SHOP = "shop"            # 商店买卖界面
    TRANSITION = "transition"  # 过场：黑屏、进出门、白闪


class Overlay(str, Enum):
    """屏幕上盖着什么等你操作。决定**可以按什么键**。"""

    NONE = "none"      # 没有弹出层，直接操作角色
    DIALOG = "dialog"  # 对话框：一段文本等你推进
    CHOICE = "choice"  # 选择框：一组选项 + 光标


# ---- 两张表：二元组的收益就兑现在这里 ----

OVERLAY_ACTIONS: dict[Overlay, tuple[str, ...]] = {
    Overlay.NONE: ("up", "down", "left", "right", "a", "start"),
    Overlay.DIALOG: ("a",),                      # 方向键无效，只能推进
    Overlay.CHOICE: ("up", "down", "a", "b"),    # 移光标 / 确认 / 取消
}
"""动作掩码**只看 overlay**，与 scene 无关。

这就是拆成二元组最直接的回报：三条规则覆盖所有场合，
而不是每个"场合 × 叠加层"的组合各写一遍。
"""

SCENE_FIELDS: dict[Scene, tuple[str, ...]] = {
    # 野外与室内**没有 fields**：它们的内容全部走 `walk_map` 和 `landmarks`。
    #
    # 曾经这里是 `facing, north, south, east, west, landmarks`，实测全是噪声：
    # `north: grass ×3` 在主角连走六步的过程中一字未变——它根本不是位置的函数，
    # 是"这张图上半部分是草"的函数。字段名承诺的是**测量**，VLM 交付的是**描述**，
    # 两者差一个数量级，不是把 prompt 写好就能弥合的。
    #
    # `facing` 更不该问模型：朝向就是最后一次按的方向键，world 自己知道，
    # 是确定的量，问模型等于把一个已知量换成一个 8/8 全错的猜测。
    Scene.FIELD: (),
    Scene.INDOOR: (),
    Scene.BATTLE: ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp"),
    Scene.MENU: ("title",),
    Scene.SHOP: ("money", "items"),
    Scene.TRANSITION: (),
}
"""每个场合期望读到哪些字段。

**这是数据不是类型**：给某个 scene 加一个字段，不改变任何枚举值，
所以不触发 append-only 的约束。字段名进 prompt 告诉 VLM 该填什么，
填出来的值进 `ScreenState.fields`。
"""


GRID_COLS, GRID_ROWS = 10, 9
"""屏幕上有几列几行格子。160/16 = 10，144/16 = 9。"""

PLAYER_CELL = (4, 4)
"""主角在屏幕上的格子坐标 `(col, row)`，**是个常量**。

宝可梦红的镜头锁死在主角身上，所以他在屏幕上的位置永远不变——28 张真实截图
（野外、室内、有无对话框）无一例外。

这一条把感知任务降了一个维度：**模型不需要定位主角**，只需要读格子内容。
它同时提供一个免费的自检位——模型把 `@` 放到别处，说明它的坐标系整个是错的，
这一帧判废重试，不必等 agent 撞墙才发现。
"""

PLAYER_MARK = "@"
UNKNOWN = "?"


class Tile(BaseModel):
    """一种地形符号的含义。

    **只有名字和说明，没有 `walkable` 布尔位。** 曾经有过，但它没有任何消费方——
    只被 `tile_legend()` 拿去渲染"能走 / 走不过去"几个字，其余全是测试在断言它自己。
    通行性的判断本来就写在 `note` 里，多一个字段等于同一件事说两遍，
    而两遍迟早会打架。等真的出现程序化的消费方（机制一从符号派生 state key、
    或者路径规划器），再把它加回来不迟——那时它才有个明确的用户。

    要紧的是这套符号解决的问题没变：**问"这格是什么"而不是"这格能不能走"。**
    前者是分类，模型做得来；后者是推断，需要游戏知识——实测里它认出了门，
    却因为门看着像墙标了"不能走"，大脑再花 765 个 token 编出解释来自圆其说。
    """

    name: str = Field(description="给人读的名字")
    note: str = Field(description="这格意味着什么。**这句话会原样进两个 prompt**，"
                                  "所以它要能独立读懂，不依赖任何别的字段")


TILES: dict[str, Tile] = {
    ".": Tile(name="普通地面", note="能走"),
    "G": Tile(name="草丛", note="能走，走进去会遇野生宝可梦"),
    "D": Tile(name="门/入口/楼梯", note="能进，通往另一张地图"),
    "L": Tile(name="台阶断崖", note="只能从上往下跳，反方向过不去"),
    "N": Tile(name="人", note="走不过去；面朝它按 A 可以对话"),
    "S": Tile(name="招牌或可调查物", note="走不过去；面朝它按 A 可以调查"),
    "W": Tile(name="水面", note="走不过去，学会冲浪之前过不去"),
    "#": Tile(name="墙/树/建筑/家具", note="走不过去"),
    UNKNOWN: Tile(name="看不清", note="这一帧没读出来。**不代表不能走**，想去就单独走一步试"),
    PLAYER_MARK: Tile(name="主角自己", note="**必须且只能出现在 (4,4)**"),
}
"""地形符号表。**append-only**：一旦机制三开始积累 `(state-key, action) -> value`，
符号的含义就不能再改，只能加新的——改一个字母的意思，等于让历史 value 全部失配。

为什么是这十个而不是更多：每多一个符号，模型就多一次分类机会，也多一处错。
拆到"树 vs 墙"这个粒度对决策毫无影响（都走不过去），只是白白增加错误面。
拆到 `G` 是必要的（它决定会不会遇野生宝可梦），拆到 `D` 是必要的
（它是唯一"看着不能走但其实能过"的东西，也正是上一版栽的地方）。
"""

WALK_CHARS = frozenset(TILES)
WALKABLE = "."
BLOCKED = "#"


def tile_legend() -> str:
    """渲染成 prompt 和动作说明里的图例。**两边共用一份，不手写。**

    手写必然漂移：加一个符号却忘了改其中一处，模型和大脑就在用两套字典，
    而这种错不会报错，只会静默地互相误解。
    """
    return "\n".join(f"- `{ch}` {t.name} —— {t.note}" for ch, t in TILES.items())


class ScreenState(BaseModel):
    """一帧画面被解析成的结构化状态。

    字段值统一放 `fields` 这个扁平 dict，而不是给每个 scene 定一个子模型：
    机制三的 state key 要从 `(scene, overlay, fields)` 均匀派生，
    分成多个子模型会让 key 的构造对 scene 分支，得不偿失。
    """

    scene: Scene
    overlay: Overlay

    overview: str = Field(
        default="",
        description="一句话描述整幅画面的布局，例如「左下角一栋房子，上方一片草丛，"
        "中间横着一排断崖」。**必须写在 walk_map 之前**——字段的声明顺序就是模型的"
        "输出顺序，先说整体会约束后面逐格填的结果；反过来先填格子再总结，"
        "总结就只是在复述已经填错的东西",
    )

    dialog_text: str = Field(
        default="", description="overlay=DIALOG 时框里的文字；其他情况为空"
    )
    options: list[str] = Field(
        default_factory=list,
        description="overlay=CHOICE 时的选项列表。**菜单的区别在这里，不在类型上**",
    )
    cursor: int | None = Field(
        default=None, description="overlay=CHOICE 时光标停在第几项，0 起；未知为 None"
    )
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="该 scene 的结构化字段，键取自 SCENE_FIELDS。读不出的字段直接不放，"
        "**不要填占位值**——分不清'没读到'和'读到了空'会污染状态抽象准确率的标定",
    )
    walk_map: list[str] = Field(
        default_factory=list,
        description=f"{GRID_ROWS} 行、每行 {GRID_COLS} 个字符的通行性矩阵，"
        f"字符取自 {sorted(WALK_CHARS)}；`{PLAYER_MARK}` 必须落在 {PLAYER_CELL}。"
        "只在 field / indoor 下有意义，其余场合留空列表",
    )
    landmarks: list[str] = Field(
        default_factory=list,
        description="带坐标的地标，如 `宝可梦中心门 (4,3)`。"
        "**矩阵只说得出「这格不能走」，说不出「这格是门」**，所以它不能被矩阵取代；"
        "反过来，不带坐标的地标（'北边有一栋建筑'）已实测只会产生噪声，不要",
    )

    @field_validator("fields", mode="before")
    @classmethod
    def _stringify(cls, v: object) -> object:
        """把字段值规整成字符串。

        实测：模型会按**语义**给类型——`walkable` 给 `true`（bool），
        `nearby` 给 `["Gramps"]`（list）。它读得完全正确，却因为
        `dict[str, str]` 被整条拒掉。23 帧里有 11 帧栽在这上面，
        而那和感知质量毫无关系。

        判据同 ```json 包裹、rationale 裸字符串：**常见格式偏差、语义无歧义、
        为它判错不划算。** `walkable` 是 `true` 还是 `"true"` 是序列化细节。

        为什么不干脆放宽成 `dict[str, Any]`：机制一的 state key 要从 fields 派生，
        值的类型不统一就没法稳定地构造 key。规整在入口做一次，下游永远只见字符串。

        **列表排序后再拼**：模型两次读同一个画面可能给出不同顺序的 `nearby`，
        不排序的话同一个状态会派生出不同的 state key，机制三直接失稳。
        """
        if not isinstance(v, dict):
            return v
        out: dict[str, str] = {}
        for k, val in v.items():
            if isinstance(val, bool):
                out[str(k)] = "true" if val else "false"
            elif isinstance(val, (list, tuple, set)):
                out[str(k)] = ", ".join(sorted(str(x) for x in val))
            elif val is None:
                continue  # 读不出的字段直接不放，不留占位值
            else:
                out[str(k)] = str(val)
        return out

    @field_validator("walk_map")
    @classmethod
    def _check_walk_map(cls, v: list[str]) -> list[str]:
        """形状和自检位都不对就整条打回。

        **走异常不走截断**：一张行数不对的地图说明模型的坐标系是错的，
        补齐或裁掉只会把错误藏起来，让下游拿着一张错地图规划路径。
        空列表是合法的——战斗、菜单、过场本来就没有地图。
        """
        if not v:
            return v
        if len(v) != GRID_ROWS:
            raise ValueError(f"walk_map must have {GRID_ROWS} rows, got {len(v)}")
        for i, row in enumerate(v):
            if len(row) != GRID_COLS:
                raise ValueError(f"row {i} has {len(row)} cells, expected {GRID_COLS}")
            bad = set(row) - WALK_CHARS
            if bad:
                raise ValueError(f"row {i} has illegal characters {sorted(bad)}")

        col, row_i = PLAYER_CELL
        if v[row_i][col] != PLAYER_MARK:
            # 自检位。模型认错了自己在哪，这一帧的每一格都不可信。
            raise ValueError(
                f"{PLAYER_MARK!r} must be at {PLAYER_CELL}, "
                f"found {v[row_i][col]!r} there"
            )
        return v

    @model_validator(mode="after")
    def _overview_comes_with_the_map(self) -> ScreenState:
        """有 `walk_map` 就必须有 `overview`。

        它不是可选的补充说明，是**逐格填写之前的那次全局判断**。
        允许它缺失，模型就会跳过它直接填格子——而跳过的正是唯一能约束
        那 90 次孤立猜测的东西。
        """
        if self.walk_map and not self.overview.strip():
            raise ValueError("a walk_map must come with an overview of the whole screen")
        return self

    @field_validator("landmarks")
    @classmethod
    def _check_landmarks(cls, v: list[str]) -> list[str]:
        """每条地标都必须带一个**存在的**格子坐标。

        不校验的话，模型会退回"北边有一栋建筑"那种无坐标描述——上一版实测证明
        那只会产生噪声。而越界坐标（`(12,3)`）比没坐标更糟：它看起来可用，
        大脑会拿它去规划一条通往屏幕外的路。
        """
        for item in v:
            m = re.search(r"\((\d+)\s*,\s*(\d+)\)\s*$", item)
            if not m:
                raise ValueError(f"landmark {item!r} must end with a cell like '(4,3)'")
            col, row = int(m.group(1)), int(m.group(2))
            if not (0 <= col < GRID_COLS and 0 <= row < GRID_ROWS):
                raise ValueError(
                    f"landmark {item!r} points at ({col},{row}), "
                    f"outside the {GRID_COLS}x{GRID_ROWS} grid"
                )
        return v

    def neighbors(self) -> dict[str, str]:
        """主角四周那四格各是什么符号，键是方向键名。

        单独给一个方法，因为这四格和其余 86 格**不是一回事**：
        它们决定这一步能不能动，错一格就是原地撞墙；其余的只影响路径规划，
        错一格多绕一步。标定时两者要分开报，混在一个"整体准确率"里，
        「每步都错」会被藏在「85% 正确」底下。
        """
        if not self.walk_map:
            return {}
        col, row = PLAYER_CELL
        return {
            "up": self.walk_map[row - 1][col],
            "down": self.walk_map[row + 1][col],
            "left": self.walk_map[row][col - 1],
            "right": self.walk_map[row][col + 1],
        }

    def render_walk_map(self) -> str:
        """渲染成给大脑读的样子：带行列号，一行一行。

        列号顶在上面、行号顶在左边，和画在图上的网格标号**必须一致**——
        大脑读到的坐标和模型看到的坐标对不上，整套东西就白做了。
        """
        if not self.walk_map:
            return ""
        head = "   " + " ".join(str(c) for c in range(GRID_COLS))
        body = [f" {r} " + " ".join(row) for r, row in enumerate(self.walk_map)]
        return "\n".join([head, *body])

    def available_actions(self) -> tuple[str, ...]:
        """当前可按的键。**只由 overlay 决定**，masking 的数据来源。"""
        return OVERLAY_ACTIONS[self.overlay]

    def expected_fields(self) -> tuple[str, ...]:
        """当前 scene 期望读到的字段名。用于组 prompt 和标定完整度。"""
        return SCENE_FIELDS[self.scene]


# ---- 给测试用的自描述 ----
#
# prompt 里的字段清单和输出样例是**手写在 .md 里的**，因为 prompt 文件必须能被
# 完整读到——打开文件看到 `$scene_fields` 的话，"prompt 可 review"就是句空话。
#
# 漂移由**测试**挡：`test_prompts.py` 拿这里的输出和 .md 的内容对照，
# 给某个 scene 加了字段却忘了改 prompt，测试当场失败。
# 防漂移不需要牺牲可读性，两者用不同手段各自解决。


def describe_scene_fields() -> str:
    """把 SCENE_FIELDS 渲染成 prompt 里的字段清单。"""
    lines = []
    for scene, fields in SCENE_FIELDS.items():
        if fields:
            lines.append(f"- `{scene.value}` → {', '.join(f'`{f}`' for f in fields)}")
        else:
            lines.append(f"- `{scene.value}` → 不需要任何字段，`fields` 留空对象")
    return "\n".join(lines)


EXAMPLES: dict[Scene, ScreenState] = {
    Scene.FIELD: ScreenState(
        scene=Scene.FIELD,
        overlay=Overlay.NONE,
        overview="左上角一片草丛，中上方一栋房子、门开在正下方；"
                 "画面中间横着一排断崖，只在主角正下方有个缺口；下半部是空地，左侧立着一块招牌。",
        walk_map=[
            "GG####....",
            "GG####....",
            "GG####....",
            "GG##D#....",
            "....@.....",
            "LLLL.LLLLL",
            "..........",
            "..S.......",
            "..........",
        ],
        landmarks=["宝可梦中心 (4,3)", "路线指示牌 (2,7)"],
    ),
    Scene.INDOOR: ScreenState(
        scene=Scene.INDOOR,
        overlay=Overlay.DIALOG,
        overview="一间四面是墙的房间，中间一组柜子，柜子前站着一个人；"
                 "右下方有一处出口。画面下方三行被对话框盖住，看不到地面。",
        dialog_text="OAK: Hello there! Welcome to the world of POKéMON!",
        walk_map=[
            "##########",
            "#........#",
            "#..####..#",
            "#..#N##..#",
            "#...@....#",
            "#....D...#",
            "??????????",
            "??????????",
            "??????????",
        ],
        landmarks=["大木博士 (4,3)", "出口 (5,5)"],
    ),
    Scene.BATTLE: ScreenState(
        scene=Scene.BATTLE,
        overlay=Overlay.CHOICE,
        overview="战斗画面：右上是对手，左下是我方背影，右下角是四选项指令框。",
        options=["FIGHT", "PKMN", "ITEM", "RUN"],
        cursor=0,
        fields={
            "foe_name": "CHARMANDER", "foe_level": "5", "foe_hp": "18/18",
            "my_name": "AL", "my_level": "5", "my_hp": "19/19",
        },
    ),
    Scene.MENU: ScreenState(
        scene=Scene.MENU,
        overlay=Overlay.CHOICE,
        overview="画面右侧弹出一列主菜单条目，光标停在第二项。",
        options=["POKéDEX", "POKéMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT"],
        cursor=1,
        fields={"title": "主菜单"},
    ),
    Scene.SHOP: ScreenState(
        scene=Scene.SHOP,
        overlay=Overlay.CHOICE,
        overview="商店买卖界面：上方是所持金钱，下方是商品与价格的列表。",
        options=["POKé BALL", "POTION", "ANTIDOTE", "CANCEL"],
        cursor=0,
        fields={"money": "3000", "items": "POKé BALL, POTION, ANTIDOTE"},
    ),
    Scene.TRANSITION: ScreenState(
        scene=Scene.TRANSITION,
        overlay=Overlay.NONE,
        overview="画面正在切换，全黑，没有可辨认的内容。",
    ),
}
"""每个 scene 一份合法样例，**同时是 prompt 的内容基准和测试基准**。

为什么每类都要有：只给一份野外样例时，模型在战斗画面上会照着野外那份的形状填——
把 `walk_map` 也填出来。样例是模型唯一能看到的"输出长什么样"的实例，
缺哪一类，那一类就靠它自己猜。

三个样例各自还在示范一件容易错的事：

- `indoor` 带对话框：被挡住的三行**全部写 `?`**，不要凭印象补。
  这是 `?` 唯一一个高频用途，不示范的话模型永远不会用它。
- `battle`：`walk_map` 和 `landmarks` 都是空的——战斗画面没有可走的地图。
- `transition`：**什么都不填**。过场是一帧没有内容的画面，硬填就是编。

prompt 里的样例是手写的（为了文件可读），本模块的这份是基准，
`test_prompts.py` 逐字对照，漂移当场失败。
"""


def json_output_examples() -> dict[Scene, str]:
    """渲染成 prompt 里那几段 JSON。键是 scene，值是格式化好的 JSON 文本。"""
    return {scene: state.model_dump_json(indent=2) for scene, state in EXAMPLES.items()}


def json_output_example() -> str:
    """野外那一份。保留单数形式是因为它是最主要的一类，测试和文档都常单独引用它。"""
    return json_output_examples()[Scene.FIELD]
