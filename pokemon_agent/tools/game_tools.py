"""GameTools —— 把「世界的能力」翻译成「大脑的工具」。**全项目只有这一个。**

它以前叫 `Harness`，改名是因为那个名字盖住了两件不同的事：
"大脑怎么碰环境"（这里）和"一局怎么跑"（`harness/harness.py`）。
合在一个类里的时候，`perceive()` 同时是"看一眼"和"新的一步"，
于是需要按步去重来调和两种身份——而那个去重制造了步号回退和判定重复计费。

拆开之后这个类**没有任何跨步骤状态**除了记忆库和"上一次给出的动作空间"，
后者只为 `execute()` 的前置条件服务。它不写 trace、不认识 LLM、不知道 episode 是谁。

## 掩码规则

从 `facts["overlay"]` 查 `OVERLAY_ACTIONS`。
**掩码是策略，所以在这一层；`overlay` 是感知的产物，所以由 world 交出来。**
两边通过 `Observation.facts` 这个公开字段衔接，谁也不认识谁的内部。

`overlay` 在熔断里 23/23 全对，是整条感知链里最可靠的一维——把动作空间挂在它上面
是刻意的：分类错一次的代价是大脑看到一组不该有的动作，比字段读错严重得多。

## 感知归 world，这一层只是转发

用户定的分工：**感知是"tool 调用 world"**。VisionProvider 留在 `PyBoyWorld` 里，
理由是 `Observation` 是跨层契约，谁产出谁负责完整性；而且"一帧只感知一次"的
缓存依赖它在 world 内部。这一层只把 `observe()` 转出来。

## 还没做的

- **记忆检索仍是字符集重叠**。换向量检索是机制一的事，
  现在换会掩盖「检索策略属于实现方」这个分层是否成立。
- **六件套只有 trace 一件**：缺权限确认、沙箱、成本上限、checkpoint、replay。
"""

from __future__ import annotations

from pokemon_agent.interfaces.world import WorldPort
from pokemon_agent.schemas.core import (
    BUTTON_FACING,
    FACING_CN,
    FACING_OPPOSITE,
    INTERACT_KEY,
    OVERLAY_ACTIONS,
    Action,
    ActionSpace,
    Landmark,
    MemoryEntry,
    ObjectNote,
    Observation,
    Overlay,
    Place,
    Task,
    TerrainMap,
    ToolResult,
    terrain_legend,
)

INTERACTIVE = ("人", "招牌", "门")
"""哪些地标值得记一条交互记忆。走得过去的空地按 `a` 什么也不会发生，记了是噪声。"""

BUTTON_HELP: dict[Overlay, dict[str, str]] = {
    Overlay.NONE: {
        "up": "向上走一格", "down": "向下走一格",
        "left": "向左走一格", "right": "向右走一格",
        "a": "与面前的人或物互动（调查、对话、开门）。"
             "**一次只按一次**——写 times>1 也会被夹成 1，对话是一句一句出来的",
        "start": "打开主菜单",
    },
    Overlay.DIALOG: {"a": "推进对话到下一句。**一次一句**，"
                          "连按会把中间那几句整个吃掉，而那几句往往就是你要找的证据"},
    Overlay.CHOICE: {
        "up": "光标上移一项", "down": "光标下移一项",
        "a": "选中光标所在项", "b": "取消，退回上一层",
    },
}
"""同一个键在不同 overlay 下含义不同，说明也得跟着变。

`a` 在野外是「互动」、在对话框里是「推进」、在选择框里是「确认」——
给大脑一份放之四海的说明，等于让它自己去猜当前语境。
"""

def _sample_map() -> str:
    """给模型看的读图范例。**由真正的渲染函数生成，不手写。**

    手写的话它迟早和 `TerrainMap.render()` 漂移，而漂移的症状是模型照着一份
    过时的范例去数一张新格式的图——那种错不报错。这和 `terrain_legend()`
    两边共用一份 `TERRAIN_MEANING` 是同一条理由。
    """
    return TerrainMap(
        cells=["#.....#.GG", "#.....#.GG", "#.....#.GG", "#####N##GG",
               "....@..#GG", "####...#GG", "####...#GG", "#D##...#GG",
               ".......#GG"],
        map_id=0, player_x=15, player_y=2,
    ).render()


MAP_HINT = (
    "## 怎么读 walk_map\n"
    "已知事实里的 `walk_map` 是一张 10 列 x 9 行的地图，"
    "**它来自模拟器内存，不是看出来的，100% 准确**：\n"
    + terrain_legend() + "\n"
    "\n"
    "## 只有一套坐标\n"
    "图上的行号 `y=..`，和 `where` / `landmarks` / `known_objects` 里的 `x= y=`\n"
    "**是同一套数**，不需要任何换算，也没有第二套坐标。\n"
    "\n" + _sample_map() + "\n"
    "\n"
    "`@` 就是你，它那一格的坐标 `where` 那一行写着。\n"
    "**y 向下增大，x 向右增大。**\n"
    "\n"
    "## 图上没有列号，别在图上找东西\n"
    "一列只有一个字符宽，两三位数的 x 写不进去，所以**只给了行号**。\n"
    "这不影响你做任何事，因为**你本来就不该在图上数格子找东西**：\n"
    "- 门 / 招牌 / 人在哪 —— `landmarks` 和 `known_objects` 里写着确切坐标。\n"
    "- 四个方向各是什么 —— `neighbors` 已经算好了，那是决定这一步能不能动的四格。\n"
    "\n"
    "**这张图剩下的用处是看形状**：朝那个方向走得通吗、哪边是死路、\n"
    "绕过去要从哪边绕。看形状不需要列号，从 `@` 往那个方向看过去就行。\n"
    "\n"
    "`walk_map` **每一行恰好 10 个字符，没有空格**——`##...S#D##` 里 `##...`\n"
    "是**三个点**。**图和 `landmarks` 对不上时是你数错了，不是数据错了**：\n"
    "两者都来自模拟器内存，同一帧读出来的，不可能互相矛盾。\n"
    "不要花篇幅论证哪一边可信，以 `landmarks` 为准。\n"
    "\n"
    "## 站在 `D` 上的时候，朝地图外面那个方向按\n"
    "**室内的出口就是这么用的**：门格贴着地图边界，`neighbors` 会告诉你那个方向是\n"
    "`#`，但**按下去就出去了**。`#` 说的是「走不过去」，不是「按了没用」——\n"
    "门格上的那一下不是走路，是开门。\n"
    "\n"
    "所以站在 `D` 上没换图时，**先把四个方向里那个朝向地图边界的试一遍**，\n"
    "而不是换一扇门。两扇门挨着的时候尤其要注意：\n"
    "从这扇门走到那扇门，走的还是屋里，`map_id` 一个数都没变。\n"
    "\n"
    "## 地标没有名字，`known_objects` 才有\n"
    "`landmarks` 只说「这里有一扇门 / 一块招牌 / 一个人」和它在哪，**不说那是谁家、"
    "招牌上写什么**——那些字在这个画面里根本没有渲染，写出来只能是编的。\n"
    "\n"
    "已知事实里的 `known_objects` 是**这张地图上你见过的每一个**门/招牌/人的档案，"
    "坐标和 `landmarks` 是同一套，**直接对得上，不需要换算**：\n"
    "  `地图0 x=13 y=5 的「门」→ 通往地图39（见过 7 次，互动 1 次）`\n"
    "  `地图0 x=11 y=5 的「招牌」→ PALLET TOWN…（见过 7 次，互动 1 次）`\n"
    "  `地图0 x=5 y=5 的「门」→ **还没互动过**（见过 7 次，互动 0 次）`\n"
    "\n"
    "**「还没互动过」是你的待办清单。** 想找的东西不在已知的那几条里，"
    "就去试没试过的那几个——而不是对着试过的再按一遍。\n"
    "门的「通往地图N」是**你自己走进去换来的**，没走过就没有。\n"
    "\n"
    "## 一扇门有哪 8 种碰法\n"
    "**站在门那一格上**按四个方向之一：\n"
    "  `站在上面按up` / `站在上面按down` / `站在上面按left` / `站在上面按right`\n"
    "**从旁边推过去**（走到它相邻的那一格，再朝它按）：\n"
    "  `站在南边按up` / `站在北边按down` / `站在东边按left` / `站在西边按right`\n"
    "\n"
    "**门只有一种成功：`map_id` 变了。** 人走到了门那一格上不算——\n"
    "两扇门挨着的时候尤其要注意，从这扇门走到那扇门，走的还是屋里。\n"
    "\n"
    "## 档案里写的是结果，不是碰法\n"
    "  `地图37 x=2 y=7 的「门」 → 站在上面按down → 地图0`\n"
    "  `地图0 x=5 y=5 的「门」 → **还没打开过**（试过 站在南边按up，还剩 7 种没试）`\n"
    "\n"
    "第一种是**照着做就行**：先走到那一格，再按那个键。\n"
    "第二种里「试过」那几个**别再试第二遍**，「还剩 N 种」是从上面那 8 种里减掉它们——\n"
    "**这个数大于 0 就说明还有别的可试，不要换一扇门**。\n"
    "写不出「还剩」说明 8 种全试过了：这扇门就是打不开（剧情没到，或者它是装饰）。\n"
    "\n"
    "人和招牌不用这一套：它们只有「面朝它按 `a`」一种碰法，说过的话直接写在条目里。\n"
    "\n"
    "`walk_map` 和 `landmarks` 都来自模拟器内存，**都不会错**。"
    "地图每一帧重新给出，不存在跨步骤的额度或余量。"
)
"""怎么读地图。

这段话的重点从「怎么理解一个可能不准的判断」变成了「怎么用一张准确的地图」——
早先它是视觉模型逐格猜出来的，会错；现在它直接读模拟器内存（`world/ram.py`），
抄的是游戏自己的碰撞判定，**几何这一维从 87% 变成 100%**，而且不要钱、零延迟。

所以这一段最要紧的是把两者的可信度差别讲清楚：`walk_map` 不会错，`landmarks` 会。
不讲清楚的话，模型又会像上一版那样，为了自圆其说去编一个"门是特殊格"出来。

最后一句有来历：更早一版里模型把 `north: grass x3` 当成了**跨步骤的额度**
（"我按过 3 次了，用完了"），在这上面写了 700 token 的自我拉扯。
地图是每帧重出的，这件事必须说明白。
"""

REPEAT_HINT = (
    "## 怎么用连按\n"
    "用 `\"args\": {\"times\": \"N\"}` 连按同一个键，N 最多 8。\n"
    "**每一步都要花一次感知调用。** 一条直线拆成五步走，就是把同一段路的成本乘以五，"
    "而且中间那四次观测你什么新东西都不会看到。\n"
    "**规则：先在 walk_map 上把路径规划到转弯处，再把开头那段同方向的一次走完。**\n"
    "  例：路径是 left, left, down —— 开头两个都是 left，"
    "所以这一步选 `left` 且 `times` 填 `2`；下一步再选 `down`。\n"
    "  例：路径是 up, right —— 开头只有一个 up，`times` 填 `1`。\n"
    "N 直接从 walk_map 上数：沿那个方向连续有几个 `.`，数到 `#`、`?` 或要转弯的那格为止。\n"
    "只有一种情况该主动放弃连按：目标格是 `?`，或者你预期中途会触发对话、遭遇战。"
)
"""连按提示。

随动作空间下发而不是写进 prompt 模板，因为它是**动作接口的一部分**——
模型能不能用 `times` 取决于工具层认不认，和 prompt 怎么写无关。

## 为什么要写成规则加例子，而不是只说"可以连按"

实测：模型已经把路径算对了（`(4,4)→left→(3,4)→left→(2,4)→down→(2,5)`），
却仍然只走第一步。它不是不会用 `times`，是**没有理由用**——
"可以连按"是一句许可，许可不会改变行为。

所以这里给的是三样东西：**代价**（每步一次感知调用）、**规则**（把开头同向的一段
合并）、**例子**（left,left,down → `left ×2`）。例子最要紧，它把规则落在
模型自己刚写出来的那种路径上。

反过来，"什么时候不该连按"也要写明（目标是 `?`、预期中途有事件），
否则收紧一处会在另一处过度放开。

**放 `ActionSpace.note` 而不是 `descriptions`**：prompt 只遍历 `names`
渲染说明，塞进 descriptions 的额外键永远不会被渲染出去——写了等于没写。
"""


class GameTools:
    """`ToolHost` 的唯一实现。持有 world 与记忆库，**不持有 episode**。"""

    def __init__(self, world: WorldPort) -> None:
        self._world = world
        self._memories: list[MemoryEntry] = []
        self._objects: dict[str, ObjectNote] = {}
        """交互记忆：`(map_id,x,y)` → 那一格的东西跟我说过什么。

        **和情景记忆是两种东西**（见 `ObjectNote` 的完整说明）：情景记忆的作用域是
        一次经过，这一条的作用域是**那一格本身**，域内恒真、而且域会反复出现。

        和 `_memories` 一样**不随 episode 清空**——"地图39 x=2 y=3 那个人不是母亲"
        这件事，下一局仍然成立。跨局复用正是要验证的东西。
        """
        self._last_space: tuple[ActionSpace, str] | None = None
        """上一次交出去的动作空间，**连同它是给哪一帧算的**。

        它回答两个问题，缺一不可：

        1. 大脑选的这个按键，是不是从我刚给它的那份清单里选的；
        2. 那份清单，是不是**还对着现在这一帧**。

        第二条以前是靠图的形状保证的（`look` 每轮都重算），注释里写的是
        "世界一推进就作废"。**那句话在 `inspect` / `push_goal` 路径上是假的**：
        那两轮 `step` 加了 1 而这里没被清（清空只发生在 `execute()` 和 `reset()`），
        它确确实实跨了步。

        目前无害，但这条不变量没有任何东西守着。将来只要有一类
        "不经过 look 直接 press" 的路径（重试、宏动作、skill library），
        下面那条断言就只会检查按键名在不在**上一轮**的清单里——而 `a` 在三种
        overlay 下都在，于是**断言放行，大脑在错误的语境下按了键**。
        所以把帧哈希一起存下来，让"这份清单过期了"变成一条能当场炸掉的契约。
        """

    # ---- ToolHost（只有 Harness 用）----

    def reset(self, task: Task) -> Observation:
        """开新一局。**记忆不清空**——跨任务复用经验正是要验证的东西。"""
        self._last_space = None
        return self._world.reset(task)

    def drain_calls(self) -> list[dict[str, str]]:
        """取走待记账的模型调用。转发给 world。"""
        return self._world.drain_calls()

    @property
    def last_frame_sha(self) -> str:
        return self._world.last_frame_sha

    # ---- ToolPort（大脑用）----

    def perceive(self) -> Observation:
        """看一眼当前画面，**并把这张地图上已知的交互记忆附上去**。

        world 自己按帧缓存，所以一帧之内调多少次都只花一次感知的钱；
        附加交互记忆是纯字典查找，不花钱。

        **附加在这一层而不是 world 里**：记忆库归工具层，world 只管画面。
        """
        obs = self._world.observe()
        known = self._known_here(obs)
        if not known:
            return obs
        return obs.model_copy(update={"facts": {**obs.facts, "known_objects": known}})

    def _known_here(self, obs: Observation) -> str:
        """这张地图上，我互动过的那些格子分别给了什么。

        **只筛当前地图，不筛当前屏幕**：地图内的条目一共也没几条，而"屏幕外那扇门
        我进去过"恰恰是它规划路线时最需要的一条。筛屏幕反而把最有用的滤掉了。

        坐标和 `landmarks` 是同一套（全局 `x= y=`），所以模型不需要做任何换算就能
        把两边对上——**它做不好的正是换算**。
        """
        if obs.place is None:
            return ""
        here = obs.place.map_id
        lines = [
            n.render() for n in self._objects.values()
            if n.landmark.place.map_id == here
        ]
        return "\n".join(sorted(lines))

    def note_seen(self, obs: Observation, stamp: str) -> None:
        """把这一帧看到的地标全部记进档案（没互动过的也记）。

        前置条件：**一步只调一次**——`seen` 是"进过几次视野"，
            调两次这个数就没有意义了。调用方是 `Harness._observe()`，
            那里本来就是全项目唯一一步产出一次观测的地方。

        ## 为什么没互动过的也要建档

        这份档案最有价值的一类条目正是"**这里有一扇门，我见过 7 次，一次都没进去过**"。
        没有它，agent 只能从 `landmarks` 看到那里有扇门，
        **分不出哪扇是探索过的、哪扇是新的**——而那正是它规划下一步要去哪的依据。

        `stamp` 是调用方给的不透明时刻标记（`ep0#3`）。这一层不解释它是什么，
        也就不需要知道 episode 是谁。
        """
        for mark in self._landmarks_of(obs):
            note = self._objects.setdefault(
                mark.place.key, ObjectNote(landmark=mark, first_seen=stamp)
            )
            note.seen += 1
            note.last_seen = stamp

    def note_step(
        self, before: Observation, action: Action, after: Observation
    ) -> list[ObjectNote]:
        """这一步碰到了什么，记进档案。返回被更新的条目（可能为空）。

        几件事各记各的，合成一个方法是因为它们**共用同一个触发点**（走完一步之后）
        和同一份档案：

        - **互动**（按 `a`）：面朝的那一格给了什么文字。
        - **姿势**（按方向键）：从旁边推过去、或者站在它上面朝外按，分别发生了什么。
        - **穿门**（姿势的结果是换了地图）：那扇门通往哪张地图。

        ## 姿势是这一步唯一新增的一维

        用户的原话：有的门走上前就行，有的要踩在门上撞墙，有些坡只有一个方向能走。
        这三件事的差别只有两维——**我人在它旁边还是在它上面**、**按的哪个方向**——
        所以存成 `tried[姿势] = 结果`，而不是给每个 kind 加一个专属枚举字段。
        结果也是算的：`before.place` 和 `after.place` 一减，换图 / 过去了 / 没动。

        ## 面朝哪一格是算出来的，不是认的

        `place`（内存读的全局坐标）+ `facing`（我们自己的动作历史推的）
        → `place.step_toward(facing)`。两个输入都是确定量，所以这条记忆的**键**是确定的。
        键要是靠模型认"我刚才在跟谁说话"，这套档案立刻就没有意义了。

        ## 什么情况下不记

        - 面朝的不是人/招牌/门：对着空地按 `a` 什么也不会发生。
          判据取自 `landmarks`——内存给的穷尽列表，不是模型认的。
        - 朝向未知（开局、过场之后）：算不出面朝哪一格，宁可不记也不能记错格子。
        - **连按方向键**（`times > 1`）：中途经过哪些格子算不出来，
          结果挂不到确定的一格上。宁可漏记一次，也不能把 `leads_to` 挂到错的门上——
          错的那条会被当成事实反复使用。
        - **原地转身**：宝可梦里朝向不同时按方向键，第一帧只转向不移动。
          那种"没动"和"这边过不去"长得一模一样，所以只有**本来就朝着那个方向**
          时才把 `没动` 记下来。
        - **两个候选同时存在且换了图**：脚下和面前都是已知对象时，
          算不出是哪一个把地图换掉的，整步作废。

        ## 没有文字也要记

        对着一扇门按 `a` 通常什么都不弹。**"我试过，没反应"本身就是有用的**：
        它下次就不会再对着同一扇门按第二次。同理，`没动` 这条结果比"换到地图37"
        还值钱——它是唯一能让 agent 停止重试一条走不通的路的东西。
        """
        # **按方向键时，朝向是这一次按键决定的，不是上一帧那个。**
        # `before.facts["facing"]` 是走这一步**之前**的朝向——用它去算"我走到了哪格"
        # 会指向完全无关的一格。踩过一次：往东走三步再往北进门，
        # 用旧朝向算出来的是东边那格，于是那扇门永远学不到 `leads_to`。
        # `a` 则相反：它作用在**当前**朝向上，所以用 before 的那个才对。
        facing = BUTTON_FACING.get(action.name, before.facts.get("facing", ""))
        if not facing or before.place is None or after.place is None:
            return []

        ahead = before.place.step_toward(facing)
        if action.name == INTERACT_KEY:
            kind = self._kind_at(before, ahead)
            if kind is None:
                return []
            note = self._touch(ahead, kind)
            note.see(after.facts.get("dialog_text", ""))
            return [note]

        if action.args.get("times", "1") != "1":
            return []
        moved = self._outcome(before, after, facing)
        if not moved:
            return []

        ahead_kind = self._kind_at(before, ahead)
        # 脚下这一格：**只能从档案里认**。人物精灵盖住了它，
        # 当帧的 `landmarks` 已经不再报告那里有扇门了——而"踩在门上朝外按"
        # 恰恰是室内出口唯一的走法。
        on_kind = self._kind_at(before, before.place)
        changed = before.place.map_id != after.place.map_id
        if changed and ahead_kind is not None and on_kind is not None:
            return []

        warped = f"换到地图{after.place.map_id}"
        touched: list[ObjectNote] = []
        for place, kind, pose, result in (
            (ahead, ahead_kind,
             f"站在{FACING_CN[FACING_OPPOSITE[facing]]}边按{action.name}",
             warped if changed else "没换图" if moved == "moved" else "没动"),
            (before.place, on_kind, f"站在上面按{action.name}",
             warped if changed else "没换图" if moved == "moved" else "没动"),
        ):
            if kind is None:
                continue
            note = self._touch(place, kind)
            note.try_it(pose, result)
            if changed:
                note.leads_to = after.place.map_id
            touched.append(note)
        return touched

    @staticmethod
    def _outcome(before: Observation, after: Observation, facing: str) -> str:
        """这一步动没动：`warp` / `moved` / `stay`；算不准返回空串（整步不记）。

        早一版这里返回的是给模型看的字，而那句字是"过去了"——实测直接把 agent 卡死：
        它站在 `x=2 y=7` 的门上，档案写着「站在上面按right→过去了」，
        于是按 right 走到 `x=3 y=7` 的另一扇门上，那扇门也写着
        「站在上面按left→过去了」，于是按 left 走回去——**两格之间来回踱步**，
        每一步都在"确认"自己走对了。它把"过去了"读成了"穿过去了"。

        现在这个歧义在**渲染层**解决：门的成功判据是固定的（`map_id` 变了），
        所以 `ObjectNote._door_status()` 直接把"哪个姿势能过去"算出来写在最前面，
        剩下的一律归进"试过没用"。这里只要如实报"动没动"就够了。

        全部来自两个 `place` 相减——**没有一个字是模型说的**。
        """
        assert before.place is not None and after.place is not None
        if after.place.map_id != before.place.map_id:
            return "warp"
        if (after.place.x, after.place.y) != (before.place.x, before.place.y):
            return "moved"
        if before.facts.get("facing", "") == facing:
            return "stay"
        return ""

    def _kind_at(self, obs: Observation, place: Place) -> str | None:
        """那一格上是什么。当帧的 `landmarks` 优先，认不出来再查档案。

        两个来源不是冗余：`landmarks` 是内存给的当帧真相，但它**看不见被主角
        踩住的那一格**；档案记的是"我以前见过那里有什么"，正好补上这个盲区。
        """
        for mark in self._landmarks_of(obs):
            if mark.place.key == place.key and mark.kind in INTERACTIVE:
                return mark.kind
        note = self._objects.get(place.key)
        if note is not None and note.landmark.kind in INTERACTIVE:
            return note.landmark.kind
        return None

    @staticmethod
    def _landmarks_of(obs: Observation) -> list[Landmark]:
        """把 `facts["landmarks"]` 那一行读回结构。

        **只在这里解析一次**，而且解析的是我们自己刚渲染出去的格式。
        真正干净的做法是让 `Observation` 直接带结构化的 landmarks，
        但那要给跨层契约再加一个字段，而目前只有这一个消费方——
        等第二个消费方出现再提上去。
        """
        if obs.place is None:
            return []
        out: list[Landmark] = []
        for item in obs.facts.get("landmarks", "").split("; "):
            parts = item.split()
            if len(parts) != 3 or not parts[1].startswith("x=") or not parts[2].startswith("y="):
                continue
            out.append(Landmark(
                kind=parts[0],
                place=Place(map_id=obs.place.map_id,
                            x=int(parts[1][2:]), y=int(parts[2][2:])),
            ))
        return out

    def _touch(self, place: Place, kind: str) -> ObjectNote:
        note = self._objects.setdefault(
            place.key, ObjectNote(landmark=Landmark(kind=kind, place=place))
        )
        note.touched += 1
        return note

    @property
    def object_notes(self) -> dict[str, ObjectNote]:
        """全部交互记忆。**A/B 实验的自变量之一**，所以要能被数出来。"""
        return dict(self._objects)

    def inspect(self, focus: str) -> Observation:
        """对同一帧再问一次感知。转发给 world —— 换的是 prompt，不是画面。"""
        assert focus.strip(), "inspect() got an empty focus"
        return self._world.inspect(focus)

    def get_action_space(self) -> ActionSpace:
        """掩码发生在这里，**只看 overlay**。

        后置条件：names 非空。走投无路也必须给至少一个动作——
            空动作空间是这一层的 bug，不能推给大脑处理。
        """
        obs = self._world.observe()
        overlay = Overlay(obs.facts.get("overlay", Overlay.NONE.value))
        names = [a for a in OVERLAY_ACTIONS[overlay] if a in self._world.all_actions()]

        assert names, f"action space must never be empty (overlay={overlay})"
        # `intents` 留空（默认只有 press）—— 由 Harness 覆写。
        # 能不能拆子目标取决于目标栈有多深，工具层不知道也不该知道。
        space = ActionSpace(
            names=names,
            descriptions=dict(BUTTON_HELP[overlay]),
            note=f"{MAP_HINT}\n\n{REPEAT_HINT}",
        )
        # 连同帧哈希一起记：掩码是**按这一帧的 overlay 算的**，换帧就作废。
        self._last_space = (space, self._world.last_frame_sha)
        return space

    def execute(self, action: Action) -> ToolResult:
        """执行动作，推进世界。

        前置条件：调用方必须先调用过 `get_action_space()`，且 action 来自那次结果。
        后置条件：`result.observation` 非空。
        """
        assert self._last_space is not None, "execute() before get_action_space()"
        space, frame = self._last_space
        assert space.contains(action.name), (
            f"execute() got {action.name!r} outside {space.names}"
        )
        # **掩码必须是给当前这一帧算的。** 只查名字是不够的：`a` 在野外、对话框、
        # 选择框里都可用，名字对得上不代表语境对得上。画面换过之后再拿旧清单放行，
        # 就是在一个已经变了的世界里按一个按当时语境选的键。
        assert frame == self._world.last_frame_sha, (
            "execute() got an action space computed for an older frame "
            f"({frame} != {self._world.last_frame_sha}) — call get_action_space() again"
        )

        result = self._world.step(action)
        self._last_space = None      # 世界推进了，上次的空间失效

        assert result.observation is not None, "world.step() must return the new observation"
        return result

    def memory_query(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """本阶段是朴素的字符重叠打分。**检索策略属于实现方**，签名不变。

        ## 它现在几乎不筛，这一点要知道

        中文条目里"的、了、是、在、边"这类字随处都有，任意两条中文文本的重叠数
        几乎恒大于零。实测查"北边是草丛"，一条讲"南边有水面"的记忆也会被选中——
        只因为共用了一个"边"字。排序还是对的（相关那条重叠数明显更高），
        但**筛选形同虚设**，实际效果接近"按 step 倒序返回最近 N 条"。

        为什么写在这里：做「有记忆 vs 无记忆」的 A/B 时，很容易把
        "最近 N 条也有用"误读成"检索有用"——那是两个完全不同的结论。
        机制一（状态归并 + 向量检索）要换掉的就是这个方法体。
        """
        assert limit > 0, f"limit must be > 0, got {limit}"

        # 打分对着 `render()` 的文本，**和喂进 prompt 的是同一份**。
        # 分成两份的话，可能出现"按 A 的内容选中，却把 B 的内容喂进去"，而且不报错。
        scored = sorted(
            self._memories,
            key=lambda m: (self._overlap(query, m.render()), m.step),
            reverse=True,
        )
        hits = [m for m in scored if self._overlap(query, m.render()) > 0][:limit]

        assert len(hits) <= limit, "memory_query must respect the limit"
        return hits

    def recent(self, episode_id: str, limit: int) -> list[MemoryEntry]:
        """**这一局**最近几步，按时间顺序。判定器要的历史是这一份。

        和 `memory_query()` 是两件事，不能互相替代：

        - `memory_query` 按相似度找"以前遇到过的类似情形"，**跨 episode**，
          给的是经验。
        - 这一个按时间取"刚刚发生了什么"，**只限本局**，给的是证据。

        只限本局是关键的一条线。判定器需要历史，因为证据可能出现在三步以前
        那一帧的对话框里——尤其是子目标：一条第 10 步才压进来的目标，
        前 9 步根本没人问过它，那几帧的证据就这么丢了。
        但跨 episode 的历史会造出另一种错：上一局说过的那句话让它在**第 0 步**
        就判完成。本局窗口两头都有界（局内 + 最近 N 步），那种错就发生不了。
        """
        assert limit > 0, "recent() needs a positive limit"
        return [m for m in self._memories if m.episode_id == episode_id][-limit:]

    def memory_write(self, entry: MemoryEntry) -> None:
        assert entry.rationale, "memory_write() got an entry without a rationale"
        self._memories.append(entry)

    @property
    def memory_size(self) -> int:
        """库里有多少条。**它是 A/B 实验的自变量本身**，所以要能被记进 EPISODE_START。"""
        return len(self._memories)

    @staticmethod
    def _overlap(query: str, content: str) -> int:
        return len(set(query) & set(content))
