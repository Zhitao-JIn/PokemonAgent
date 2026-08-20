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
    ToolResult,
    terrain_legend,
)

INTERACT_KEY = "a"
"""哪个键算"互动"。`a` 作用在**面朝的那一格**上：对着人说话、对着招牌看字、
对着门进去。这是游戏的规则，不是策略，所以写死在工具层。"""

INTERACTIVE = ("人", "招牌", "门")
"""哪些地标值得记一条交互记忆。走得过去的空地按 `a` 什么也不会发生，记了是噪声。"""

BUTTON_HELP: dict[Overlay, dict[str, str]] = {
    Overlay.NONE: {
        "up": "向上走一格", "down": "向下走一格",
        "left": "向左走一格", "right": "向右走一格",
        "a": "与面前的人或物互动（调查、对话、开门）",
        "start": "打开主菜单",
    },
    Overlay.DIALOG: {"a": "推进对话到下一句"},
    Overlay.CHOICE: {
        "up": "光标上移一项", "down": "光标下移一项",
        "a": "选中光标所在项", "b": "取消，退回上一层",
    },
}
"""同一个键在不同 overlay 下含义不同，说明也得跟着变。

`a` 在野外是「互动」、在对话框里是「推进」、在选择框里是「确认」——
给大脑一份放之四海的说明，等于让它自己去猜当前语境。
"""

MAP_HINT = (
    "## 怎么读 walk_map\n"
    "已知事实里的 `walk_map` 是一张 10 列 x 9 行的地图，"
    "**它来自模拟器内存，不是看出来的，100% 准确**：\n"
    + terrain_legend() + "\n"
    "\n"
    "## 两套坐标，别混\n"
    "- **屏幕格 `(列,行)`** —— 只有 `walk_map` 用这套。**列在前，行在后**，\n"
    "  和「第几行第几列」的说法**顺序是反的**：`(7,8)` 是第 8 行的第 7 个字符。\n"
    "  画面永远跟着你走，所以**你恒在 `(4,4)`**；走一步之后同一个 `(3,4)` 就指向\n"
    "  另一块地方了。**它不能跨步骤引用**，也不会出现在记忆里。\n"
    "- **全局坐标 `x= y=`** —— `where`（你在哪）和 `landmarks`（门/招牌/人在哪）\n"
    "  用这套。走一步 `where` 变一格，而 `landmarks` 里那些坐标**永远不变**。\n"
    "  判断「我这一步到底动没动」「我是不是在原地打转」，只能看 `where`。\n"
    "\n"
    "## 两套坐标怎么换算（**照抄，不要自己推**）\n"
    "设 `where` 给的是 `x=X y=Y`：\n"
    "  屏幕格 `(c,r)`  →  全局 `x = X + (c - 4)`，`y = Y + (r - 4)`\n"
    "  全局 `(x,y)`    →  屏幕格 `c = 4 + (x - X)`，`r = 4 + (y - Y)`\n"
    "要在 `walk_map` 上找某个 landmark，用第二条算出 `(c,r)` 就行，\n"
    "**不要反过来去图上一个个数、再倒推它的全局坐标**。\n"
    "\n"
    "## 数字符的两条硬规矩\n"
    "- `walk_map` **每一行恰好 10 个字符，没有空格**，第一行是列号表头 `0123456789`。\n"
    "  要取第 c 个字符，**对着表头竖着看**，不要在心里从左往右数——\n"
    "  `##...S#D##` 里 `##...` 是**三个点**，`S` 在列 5 不是列 4。\n"
    "- **算出来的和 `landmarks` 给的对不上时，是你数错了，不是数据错了。**\n"
    "  两者都来自模拟器内存，同一帧读出来的，不可能互相矛盾。\n"
    "  发现对不上就用表头重新对一遍，**不要花篇幅论证哪一边可信**。\n"
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
    "**没在 `known_objects` 里给出内容的东西，你就是不知道它是谁。**\n"
    "不要在 `rationale` 里写「确认为母亲」「这是宝可梦中心」这种没验证过的身份——\n"
    "`rationale` 会进记忆，下一步取回来，你会把自己上一步的猜测当成已知事实，\n"
    "然后一路照着它走下去。**猜错的身份比没有身份危险得多。**\n"
    "想知道是谁，走过去按 `a`；下一步它就会出现在 `known_objects` 里。\n"
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

        两种事各记各的，合成一个方法是因为它们**共用同一个触发点**（走完一步之后）
        和同一份档案：

        - **互动**（按 `a`）：面朝的那一格给了什么文字。
        - **穿门**（按方向键，而且地图变了）：那扇门通往哪张地图。

        ## 面朝哪一格是算出来的，不是认的

        `place`（内存读的全局坐标）+ `facing`（我们自己的动作历史推的）
        → `place.step_toward(facing)`。两个输入都是确定量，所以这条记忆的**键**是确定的。
        键要是靠模型认"我刚才在跟谁说话"，这套档案立刻就没有意义了。

        ## 什么情况下不记

        - 面朝的不是人/招牌/门：对着空地按 `a` 什么也不会发生。
          判据取自 `landmarks`——内存给的穷尽列表，不是模型认的。
        - 朝向未知（开局、过场之后）：算不出面朝哪一格，宁可不记也不能记错格子。
        - **连按穿门**（`times > 1` 且地图变了）：门可能在中途任意一格，
          算不准是哪一扇。宁可漏记一次，也不能把 `leads_to` 挂到错的门上——
          错的那条会被当成事实反复使用。

        ## 没有文字也要记

        对着一扇门按 `a` 通常什么都不弹。**"我试过，没反应"本身就是有用的**：
        它下次就不会再对着同一扇门按第二次。
        """
        # **按方向键时，朝向是这一次按键决定的，不是上一帧那个。**
        # `before.facts["facing"]` 是走这一步**之前**的朝向——用它去算"我走到了哪格"
        # 会指向完全无关的一格。踩过一次：往东走三步再往北进门，
        # 用旧朝向算出来的是东边那格，于是那扇门永远学不到 `leads_to`。
        # `a` 则相反：它作用在**当前**朝向上，所以用 before 的那个才对。
        facing = BUTTON_FACING.get(action.name, before.facts.get("facing", ""))
        if not facing or before.place is None or after.place is None:
            return []

        target = before.place.step_toward(facing)
        kinds = {
            m.place.key: m.kind
            for m in self._landmarks_of(before)
            if m.kind in INTERACTIVE
        }
        if target.key not in kinds:
            return []

        moved_maps = before.place.map_id != after.place.map_id
        if action.name == INTERACT_KEY:
            note = self._touch(target, kinds[target.key])
            note.see(after.facts.get("dialog_text", ""))
            return [note]

        if moved_maps and action.args.get("times", "1") == "1":
            note = self._touch(target, kinds[target.key])
            note.leads_to = after.place.map_id
            return [note]

        return []

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
