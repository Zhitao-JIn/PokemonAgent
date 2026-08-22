"""`MemoryTool` —— `MemoryToolPort` 的实现，**Harness 读写记忆走的唯一一扇门**。

它组合两类记忆，各自的读写语义完全不同，所以不合并成一套方法：

    情景记忆   `self._episodes: list[MemoryEntry]`   按相似度/时间检索
    语义记忆   `self._objects: SemanticObjectStore`   按坐标查

**这一层做编排，`memory/semantic/object_store.py` 只做存储。** "一次按键该查
哪几格候选""朝向算不算数""连按要不要跳过"这些游戏规则性质的判断都在这里——
`ObjectMemory` 只知道怎么按坐标存取一条 `ObjectFact`，不知道"按键"是什么。

程序记忆（procedural）还没做，先不留空方法——协议和实现都不该为一个还不存在的
东西预留形状，等真的要做的时候再看它需要什么样的读写接口。
"""

from __future__ import annotations

from pokemon_agent.memory.semantic.knowledge.store import load_all as _load_knowledge_base
from pokemon_agent.memory.port import SemanticObjectStore
from pokemon_agent.memory.semantic.object_store import ObjectMemory
from pokemon_agent.memory.util import kind_in_frame, parse_landmarks, surrounding_cells
from pokemon_agent.schemas.action import Action
from pokemon_agent.schemas.memory_episodic import MemoryEntry
from pokemon_agent.schemas.memory_semantic import (
    RESULT_DIALOG,
    RESULT_NONE,
    RESULT_WARP_PREFIX,
    ObjectFact,
)
from pokemon_agent.schemas.observation import (
    BUTTON_FACING,
    INTERACT_KEY,
    Observation,
    Place,
)

INTERACTIVE = ("人", "招牌", "门")
"""哪些地标值得记一条语义记忆。走得过去的空地按 `a` 什么也不会发生，记了是噪声。"""


class MemoryTool:
    """`MemoryToolPort` 的唯一实现。持有情景记忆列表 + 语义记忆（object）存储。"""

    def __init__(self, objects: SemanticObjectStore | None = None) -> None:
        self._episodes: list[MemoryEntry] = []
        self._objects: SemanticObjectStore = objects or ObjectMemory()
        """默认建一个 `ObjectMemory`，但接受注入——**类型标成协议**，测试可以喂一个
        假实现，将来换存储后端也不用碰这个类的任何一行。"""
        self._knowledge = _load_knowledge_base()
        """开局读一次就够——`memory/knowledge/*.md` 的内容在一次进程运行期间
        不会变，没必要每次调用 `knowledge_base()` 都重新扫一遍目录。"""

    # ---- 情景记忆：episodic ----

    def query_episodic(self, query: str, limit: int = 5) -> list[MemoryEntry]:
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
            self._episodes,
            key=lambda m: (self._overlap(query, m.render()), m.step),
            reverse=True,
        )
        hits = [m for m in scored if self._overlap(query, m.render()) > 0][:limit]

        assert len(hits) <= limit, "query_episodic must respect the limit"
        return hits

    def recent(self, episode_id: str, limit: int) -> list[MemoryEntry]:
        """**这一局**最近几步，按时间顺序。判定器要的历史是这一份。

        和 `query_episodic()` 是两件事，不能互相替代：
        - `query_episodic` 按相似度找"以前遇到过的类似情形"，**跨 episode**，给的是经验。
        - 这一个按时间取"刚刚发生了什么"，**只限本局**，给的是证据。

        只限本局是关键的一条线：判定器需要历史（证据可能出现在三步以前那一帧的
        对话框里），但跨 episode 的历史会造出另一种错——上一局说过的那句话
        让它在**第 0 步**就判完成。
        """
        assert limit > 0, "recent() needs a positive limit"
        return [m for m in self._episodes if m.episode_id == episode_id][-limit:]

    def write_episodic(self, entry: MemoryEntry) -> None:
        assert entry.rationale, "write_episodic() got an entry without a rationale"
        self._episodes.append(entry)

    @property
    def episodic_size(self) -> int:
        """库里有多少条情景记忆。**它是 A/B 实验的自变量本身**，要能被记进 EPISODE_START。"""
        return len(self._episodes)

    @staticmethod
    def _overlap(query: str, content: str) -> int:
        return len(set(query) & set(content))

    # ---- 语义记忆：object ----

    def known_here(self, obs: Observation) -> str:
        """这张地图上，我互动过的那些格子分别给了什么，拼成 `known_objects` 的文字。

        **只筛当前地图，不筛当前屏幕**：地图内的条目一共也没几条，而"屏幕外那扇门
        我进去过"恰恰是它规划路线时最需要的一条。筛屏幕反而把最有用的滤掉了。

        坐标和 `landmarks` 是同一套（全局 `x= y=`），所以模型不需要做任何换算就能
        把两边对上——**它做不好的正是换算**。
        """
        if obs.place is None:
            return ""
        lines = [fact.render() for fact in self._objects.query_map(obs.place.map_id)]
        return "\n".join(sorted(lines))

    def knowledge_base(self) -> str:
        """通用游戏先验，原样返回——**不按任何东西筛**，见 `memory/knowledge/store.py`。"""
        return self._knowledge

    def see_objects(self, obs: Observation, stamp: str) -> None:
        """把这一帧看到的地标全部记进语义记忆（没互动过的也记）。

        前置条件：**一步只调一次**——`seen` 是"进过几次视野"，调两次这个数
        就没有意义了。调用方是 `Harness._observe()`，那里本来就是全项目唯一
        一步产出一次观测的地方。

        ## 为什么没互动过的也要建档

        这份档案最有价值的一类条目正是"**这里有一扇门，我见过 7 次，一次都没进去过**"。
        没有它，agent 只能从 `landmarks` 看到那里有扇门，
        **分不出哪扇是探索过的、哪扇是新的**——而那正是它规划下一步要去哪的依据。
        """
        self._objects.see(parse_landmarks(obs), stamp)

    def note_step(
        self, before: Observation, action: Action, after: Observation
    ) -> list[ObjectFact]:
        """这一步碰到了什么，记进语义记忆。返回被更新的条目（可能为空）。

        几件事各记各的，合成一个方法是因为它们**共用同一个触发点**（走完一步之后）：

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

        ## 什么情况下不记

        - 面朝的不是人/招牌/门：对着空地按 `a` 什么也不会发生。
        - 朝向未知（开局、过场之后）：算不出面朝哪一格，宁可不记也不能记错格子。
        - **连按方向键**（`times > 1`）：中途经过哪些格子算不出来，
          结果挂不到确定的一格上。
        - **原地转身**：宝可梦里朝向不同时按方向键，第一帧只转向不移动，
          所以只有**本来就朝着那个方向**时才把 `RESULT_NONE` 记下来。
        - **两个候选同时存在且换了图**：算不出是哪一个把地图换掉的，整步作废。
        """
        # **按方向键时，朝向是这一次按键决定的，不是上一帧那个。**
        # `before.facts["facing"]` 是走这一步**之前**的朝向——用它去算"我走到了哪格"
        # 会指向完全无关的一格。`a` 则相反：它作用在**当前**朝向上，所以用 before 的那个。
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
            fact = self._objects.touch(ahead, kind, text)
            self._objects.record_attempt(
                ahead, kind, key_desc, RESULT_DIALOG if text.strip() else RESULT_NONE
            )
            return [fact]

        if action.args.get("times", "1") != "1":
            return []
        moved = self._outcome(before, after, facing)
        if not moved:
            return []

        # **查脚下 + 周围一圈，不只查面朝的那一格**：这一次按键可能碰到的候选
        # 不只是 `ahead`。脚下这格尤其要留：人物精灵盖住了它，当帧的 `landmarks`
        # 已经不再报告那里有扇门（踩在门上朝外按是室内出口唯一的走法）。
        candidates = [
            (place, self._kind_at(before, place))
            for place in surrounding_cells(before.place)
        ]
        known = [kind for _, kind in candidates if kind is not None]
        changed = before.place.map_id != after.place.map_id
        if changed and len(known) > 1:
            return []

        result = f"{RESULT_WARP_PREFIX}{after.place.map_id}" if changed else RESULT_NONE
        touched: list[ObjectFact] = []
        for place, kind in candidates:
            if kind is None:
                continue
            touched.append(self._objects.record_attempt(place, kind, key_desc, result))
        return touched

    def _kind_at(self, obs: Observation, place: Place) -> str | None:
        """那一格上是什么。当帧的 `landmarks` 优先，认不出来再查语义记忆。

        两个来源不是冗余：`landmarks` 是内存给的当帧真相，但它**看不见被主角
        踩住的那一格**；语义记忆里存的是"我以前见过那里有什么"，正好补上这个盲区。
        """
        kind = kind_in_frame(obs, place, INTERACTIVE)
        if kind is not None:
            return kind
        fact = self._objects.query(place)
        if fact is not None and fact.landmark.kind in INTERACTIVE:
            return fact.landmark.kind
        return None

    @staticmethod
    def _outcome(before: Observation, after: Observation, facing: str) -> str:
        """这一步动没动：`warp` / `moved` / `stay`；算不准返回空串（整步不记）。

        早一版这里返回的是给模型看的字，而那句字是"过去了"——实测直接把 agent 卡死：
        它站在 `x=2 y=7` 的门上，档案写着「站在上面按right→过去了」，
        于是按 right 走到 `x=3 y=7` 的另一扇门上，那扇门也写着
        「站在上面按left→过去了」，于是按 left 走回去——**两格之间来回踱步**。

        现在这个歧义在**渲染层**解决：门的成功判据是固定的（`map_id` 变了），
        所以 `ObjectFact.leads_to` 直接把"哪次尝试换了图"算出来，
        剩下的一律归进 `RESULT_NONE`。这里只要如实报"动没动"就够了。

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
