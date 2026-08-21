"""ObjectMemory —— **交互记忆**：门/招牌/人各自的档案。

从 `GameTools` 里搬出来，单独成一层。理由：这套逻辑（建档、算姿势、算结果）
跟 `GameTools` 真正的职责（转发 `world` 的能力、做 overlay 掩码）不是同一件事，
混在一个类里只会让两边都难读。

**不进 `ToolPort`/`ToolHost` 协议**：大脑不该知道"交互记忆"这个词，
它看到的只是 `Observation.facts["known_objects"]` 里的一段文字——那是
`GameTools.perceive()` 拿这个类的 `known_here()` 拼出来的。`Harness` 需要
在每步之后调 `note_seen()`/`note_step()`，所以它单独持有一份引用（构造时注入），
和 `GameTools` 内部持有的是**同一个实例**——两边共享同一份档案，
不然 Harness 记下去的东西 `GameTools.perceive()` 读不到，等于白记。
"""

from __future__ import annotations

from pokemon_agent.schemas.core import (
    BUTTON_FACING,
    FACING_STEP,
    INTERACT_KEY,
    RESULT_DIALOG,
    RESULT_NONE,
    RESULT_WARP_PREFIX,
    Action,
    Landmark,
    ObjectNote,
    Observation,
    Place,
)

INTERACTIVE = ("人", "招牌", "门")
"""哪些地标值得记一条交互记忆。走得过去的空地按 `a` 什么也不会发生，记了是噪声。"""


class ObjectMemory:
    """全部交互记忆的持有者。`GameTools` 和 `Harness` 各拿一份引用，指向同一个实例。"""

    def __init__(self) -> None:
        self._objects: dict[str, ObjectNote] = {}
        """交互记忆：`(map_id,x,y)` → 那一格的东西跟我说过什么。

        **和情景记忆是两种东西**（见 `ObjectNote` 的完整说明）：情景记忆的作用域是
        一次经过，这一条的作用域是**那一格本身**，域内恒真、而且域会反复出现。

        **不随 episode 清空**——"地图39 x=2 y=3 那个人不是母亲"这件事，
        下一局仍然成立。跨局复用正是要验证的东西。
        """

    def all(self) -> dict[str, ObjectNote]:
        """全部交互记忆。**A/B 实验的自变量之一**，所以要能被数出来。"""
        return dict(self._objects)

    def known_here(self, obs: Observation) -> str:
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
        两维本身就是"角色当时的坐标"和"按了哪个键"，不用再翻译成专门的姿势名字，
        所以存成 `attempts[x=.. y=..→按键] = 结果`。
        结果也是算的：`before.place` 和 `after.place` 一减，换图 / 无效果。

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
          时才把 `RESULT_NONE` 记下来。
        - **两个候选同时存在且换了图**：脚下和面前都是已知对象时，
          算不出是哪一个把地图换掉的，整步作废。

        ## 没有文字也要记

        对着一扇门按 `a` 通常什么都不弹。**"我试过，没反应"本身就是有用的**：
        它下次就不会再对着同一扇门按第二次。同理，`RESULT_NONE` 这条结果
        跟"进入新地图"一样值钱——它是唯一能让 agent 停止重试一条走不通的路的东西。
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
        key_desc = f"x={before.place.x} y={before.place.y}→{action.name}"
        if action.name == INTERACT_KEY:
            kind = self._kind_at(before, ahead)
            if kind is None:
                return []
            text = after.facts.get("dialog_text", "")
            note = self._touch(ahead, kind)
            note.record(key_desc, RESULT_DIALOG if text.strip() else RESULT_NONE)
            note.see(text)
            return [note]

        if action.args.get("times", "1") != "1":
            return []
        moved = self._outcome(before, after, facing)
        if not moved:
            return []

        # **查一圈，不只查面朝的那一格**：角色当前坐标周围一圈——自己脚下 +
        # 四个相邻格——都是这一次按键可能碰到的候选，不只是 `ahead`。
        # 脚下这格尤其要留：人物精灵盖住了它，当帧的 `landmarks` 已经不再报告
        # 那里有扇门（踩在门上朝外按是室内出口唯一的走法）。没有已知地标的候选
        # `_kind_at` 会返回 `None`，自动被下面的循环跳过，不会凭空多记一条。
        candidates = [
            (place, self._kind_at(before, place))
            for place in self._ring(before.place)
        ]
        known = [kind for _, kind in candidates if kind is not None]
        changed = before.place.map_id != after.place.map_id
        if changed and len(known) > 1:
            return []

        result = f"{RESULT_WARP_PREFIX}{after.place.map_id}" if changed else RESULT_NONE
        touched: list[ObjectNote] = []
        for place, kind in candidates:
            if kind is None:
                continue
            note = self._touch(place, kind)
            note.record(key_desc, result)
            touched.append(note)
        return touched

    @staticmethod
    def _ring(place: Place) -> list[Place]:
        """角色当前坐标周围一圈：**自己脚下 + 四个相邻格**，一共 5 格。

        这是一次方向键按下去唯一可能影响到的范围——按键要么改变自己脚下这格
        的状态（踩在门上朝外按），要么作用在某个相邻格上（从旁边推）。
        `FACING_STEP` 只有四个朝向，穷尽，不需要再单独判断"往哪边扩展"。
        """
        return [place] + [
            Place(map_id=place.map_id, x=place.x + dx, y=place.y + dy)
            for dx, dy in FACING_STEP.values()
        ]

    @staticmethod
    def _outcome(before: Observation, after: Observation, facing: str) -> str:
        """这一步动没动：`warp` / `moved` / `stay`；算不准返回空串（整步不记）。

        早一版这里返回的是给模型看的字，而那句字是"过去了"——实测直接把 agent 卡死：
        它站在 `x=2 y=7` 的门上，档案写着「站在上面按right→过去了」，
        于是按 right 走到 `x=3 y=7` 的另一扇门上，那扇门也写着
        「站在上面按left→过去了」，于是按 left 走回去——**两格之间来回踱步**，
        每一步都在"确认"自己走对了。它把"过去了"读成了"穿过去了"。

        现在这个歧义在**渲染层**解决：门的成功判据是固定的（`map_id` 变了），
        所以 `ObjectNote.leads_to` 直接把"哪次尝试换了图"算出来、写在最前面，
        剩下的一律归进 `RESULT_NONE`（试过没用）。这里只要如实报"动没动"就够了。

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
