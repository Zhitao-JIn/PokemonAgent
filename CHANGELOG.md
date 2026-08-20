# 变更日志

> 最新在最上。每条固定四段：改了什么 / 为什么这么改 / 取舍 / 影响面。
> 这是给人读的决策记录，不是 git log 的复制品。

## 2026-08-20 —— 判定器的两处：过期的坐标说明；对话框下连按会吃掉证据帧

**判定器不看历史是有意的，而且不会因此漏判**：每走一步都判一次，
所以"他刚才和某人说过话"这种事，会在**那句话还在对话框里的那一帧**被抓到。
判据永远只回答"就现在这一帧而言，成立吗"。这条现在明写进了 prompt——
早先没写，模型就自己去脑补历史。

**一、`judge_success.md` 里那句坐标说明是过期的。**

它写着「`walk_map` 的行列号**和 `landmarks` 的坐标**是屏幕格」——
而地标那次改动之后 `landmarks` 已经是**全局坐标**了，我漏了这一处。

后果实测可见：判定器把 `walk_map` 的行号当成全局 y，
得出"@ 在 y=4 行，其下方 y=7 是墙，说明尚未穿过门进入房屋"——
而同一份 facts 里 `map_id: 37`、`scene: indoor` 明明白白写着他在屋里。
**结论侥幸没错（任务确实没完成），但 `why` 全是编的**，而 `why` 是每一个
`True` 都要留档的东西。

改法不是补一句说明，是**把整件事禁掉**：「不要做坐标换算。判据里提到位置就直接读
`where`，它已经是答案了。**坐标推理不是证据**——证据是对话框的文字、`scene`、
`overview` 这些画面里直接写着的东西。」

顺带把这一节挪到 `$observation` **前面**：固定文本放前面才吃得到前缀缓存，
放后面等于白设。

**二、对话框开着时，连按被夹成 1 次。**

这条这局还没撞上，但一定会撞，而且**撞上了不报错**：

我们只在一步走完之后感知一次，所以连按会把中间那几帧整个吃掉。而对话框恰恰是判据
最常用的证据来源（"对话框里出现母亲说的话"）——连按三次 `a` 推完整段对话，
那几句话的每一帧都没被看到，最后一次按键还把对话框关掉，判定器看到的是一个
**没有对话框的画面**。一局本该成功的 episode 就这样被记成失败。

夹在 world 而不是靠 prompt 劝：劝它"预期有对话就别连按"，前提是它得先知道会有对话；
而对话框**已经开着**这件事我们是确定知道的（缓存里的 `ScreenState.overlay`）。

夹了要在 `message` 里说明——否则大脑以为自己按了 3 次，下一步的推理就建立在
错的前提上。**只夹对话框这一种情况**：连按是省钱的主要手段（一条直线拆成五步
就是把感知成本乘五），为一个只在对话框下成立的问题把它整个关掉，代价太大。

**影响面**：`prompts/judge_success.md`、`world/pyboy_world.py`；
`tests/test_world_smoke.py` 新增 2 条。88 个测试通过，ruff 干净。

## 2026-08-20 —— 交互记忆扩成「地标档案」：见过几次、通往哪、说过什么

**改了什么**：`ObjectNote` 从「互动过的对象」扩成**每一个见过的地标都有一条档案**。
新增字段 `seen` / `touched` / `first_seen` / `last_seen` / `leads_to`；
`note_interaction()` 并成 `note_step()`（互动 + 穿门两件事同一个触发点）；
新增 `note_seen()`，由 `Harness._observe()` 每步调一次。

**字段按「来源」分档，不按「字段好听」分**：

| 字段 | 门 | 招牌 | 人 | 来源 | 会不会错 |
|---|:-:|:-:|:-:|---|---|
| `map_id / x / y`、`kind` | ● | ● | ● | 内存 | 不会 |
| `seen` / `touched` / `first_seen` / `last_seen` | ● | ● | ● | 计数 | 不会 |
| `lines` 互动时的文字 | ○ | ● | ● | 抄 `dialog_text` | 抄错=感知错 |
| **`leads_to` 通往哪张地图** | ● | — | — | **前后 map_id 相减** | **不会** |
| ~~`identity` 这是谁~~ | — | — | ✗ | 模型推 | **会错，不存** |

**前四行一个模型调用都不需要。**

**`leads_to` 是这次最大的收获。** 早先"这扇门是哪"只有三个来源：内存的 warp 表
（精确，但那是"世界怎么连起来"，白送等于把这个项目要证明的事删掉）、视觉模型
（三轮实测全在编）、或者走进去看。现在是第三个——`before.map_id != after.map_id` 时
答案就是 `after` 的那个数，**纯算术，不会错，而且是它自己走进去换来的**。

**`identity` 不存**（用户拍的板，我也同意）：它必须由模型从 `lines` 推，
而一旦固化，错的身份会被反复当成事实——**那正是这次死循环的成因**
（它把自己写的"确认为母亲"当成了已知）。而 `lines` 本身就带着身份
（`OAK:` 有前缀、`BLUE is out at GrandPa's lab.` 内容自明）。
让模型每次读原文自己判断，比把一次判断钉死安全。

**没互动过的也建档**，这是档案最有用的一类条目：

    地图0 x=13 y=5 的「门」 → **还没互动过**（见过 7 次，互动 0 次）

没有它，agent 只能从 `landmarks` 看到那里有扇门，**分不出哪扇是探索过的、
哪扇是新的**——而那正是它规划下一步要去哪的依据。现在这行字就是它的待办清单。

**踩到并修掉的一个 bug**：`note_step` 原来一律用 `before.facts["facing"]` 算
"我碰到了哪一格"。按方向键时那是**走这一步之前**的朝向——往东走三步再往北进门，
算出来的是东边那格，于是那扇门永远学不到 `leads_to`。
改成方向键用 `BUTTON_FACING[action.name]`（这一次按键决定的），`a` 才用 before 的
（它作用在当前朝向上）。顺带把那张表从 `world` 提到 `schemas/core.py`——
**两处必须用同一张表**。

**写明的限制**：

- 键是 `(map, x, y)`，而 Gen1 有会走动的 NPC。它一动就会在新位置产生第二条记录，
  旧的变成幽灵。真新镇和屋内的 NPC 基本不动，先把机制跑起来；
  等看到幽灵条目真的多了再治（sprite 的 `picture_id` 我们读位置时已经拿到了）。
- **连按穿门（`times > 1`）故意不记 `leads_to`**：门可能在中途任意一格，算不准是哪一扇。
  宁可漏记一次，也不能把它挂到错的门上——错的那条会被当成事实反复使用。

**影响面**：`schemas/core.py`、`world/pyboy_world.py`、`tools/game_tools.py`、
`interfaces/tools.py`、`harness/harness.py`；`tests/test_memory.py` 新增 2 条。
86 个测试通过，ruff 干净。

## 2026-08-20 —— 交互记忆：跟哪一格互动过、它给了什么

**改了什么**：新增第二种记忆。`ObjectNote` 按 `(map_id, x, y)` 索引，
记「那一格的东西跟我说过什么」，每帧作为 `facts["known_objects"]` 发出去。
新增 `Place` / `Landmark` 两个模型、`Observation.place`、`EventType.OBJECT_NOTE`、
`ToolPort.note_interaction()`。

**为什么这么改**：实测的死循环——

    step 11  对着 NPC 按 a，dialog 是 "BLUE is out at GrandPa's lab."
             它在 rationale 里写下 "landmarks 中『人 x=2 y=3』…**确认为母亲**"
    step 12  取回那条记忆，照着自己的断言又按一次 a
    step 13  同上 …

三处叠在一起才有这个循环：

1. **它凭空断言了一个身份。** 和之前编招牌名字是同一个病：画面里没有可以支撑
   "这是母亲"的证据，它按先验补了一个。
2. **那句断言进了情景记忆的 `rationale`，下一步被取回。** 于是它把**自己上一步的
   猜测**当成了已知事实——`rationale` 是记忆里最像"结论"的那一栏，它读它就像读权威。
3. **判定器每一步都在说真话**（"这是 'BLUE is out at GrandPa's lab.'，不是母亲说的话"），
   但**判定器的话到不了决策模型手里**。这条隔离是有意的、也不打算放开：
   让被评价者看见评价者的理由，它就会开始朝着评价者的措辞优化，那是奖励黑客。

所以补的是第四条通道：**它自己验证过的事实**。

这也正好落在之前定的长期记忆范式上：**自带作用域 + 域内恒真 + 域会再现**。
`(map_id, x, y)` 就是那个作用域——同一张地图的同一格，下一步、下一局、下周都是它。

**几个设计点**：

- **面朝哪一格是算出来的，不是认的。** `place`（内存读的全局坐标）
  + `facing`（我们自己的动作历史推的）→ `place.step_toward(facing)`。
  两个输入都是确定量。键要是靠模型认"我刚才在跟谁说话"，整套记忆立刻失去意义。
- **可不可交互也不问模型**：判据取自 `landmarks`，那是内存给的穷尽列表。
  对着空地按 `a` 不记——这些条目每帧都要发，记了就是灌噪声。
- **没有文字也记。** 对着一扇门按 `a` 通常什么都不弹，而"我试过，没反应"本身有用：
  它下次就不会再对着同一扇门按第二次。
- **只筛当前地图，不筛当前屏幕。** "屏幕外那扇门我进去过"恰恰是规划路线时最需要的
  一条，筛屏幕反而把最有用的滤掉。
- **和 `MEMORY_WRITE` 分开成 `OBJECT_NOTE` 事件**：两种记忆的寿命和用途都不同，
  混成一类就数不出"它认识了多少个东西"——而那正是这个机制有没有用的直接指标。
- `Place` 做成模型而不是三个散字段：它现在**承载记忆的键**，三个数必须整体传递。
  散着传总有一天会漏掉 `map_id`，而漏掉之后两张地图上的同一坐标会撞在一起，
  记忆开始张冠李戴，且不报错。

`MAP_HINT` 相应加了一条硬话：**没在 `known_objects` 里的东西，你就是不知道它是谁**；
不要在 `rationale` 里写没验证过的身份，因为那会进记忆、下一步被你自己当成事实。

**实测**：走到招牌前按一次 `a`，下一帧起
`known_objects: 全局坐标 地图0 x=11 y=5 的「招牌」→ PALLET TOWN  RED 的老家`。
按第二次不会重复记（同一句去重）。

**还没做的**：门的目标地图仍然不给（那是"世界怎么连起来"，要靠走进去学），
但现在走进去之后**有地方记了**——`ObjectNote` 的 `lines` 就是那个落点。
下一步是让它进门时把"这扇门通向哪"也记上。

**影响面**：`schemas/core.py`、`world/pyboy_world.py`、`tools/game_tools.py`、
`interfaces/tools.py`、`harness/harness.py`；`tests/test_memory.py` 新增 2 条、
`tests/test_screen.py` 改 1 条。84 个测试通过，ruff 干净。

## 2026-08-20 —— dialog_text 从来没进过 facts；假对话框；同帧重复感知；记忆不说"没变"

一局实测暴露的四处，其中第一处是这个项目到目前为止最严重的一个 bug。

**1. `dialog_text` 从来没有进过 `facts`。**

视觉模型读出来了，存进 `ScreenState.dialog_text`，然后 `observe()` 组装 facts 时
**漏掉了它**。后果：

- **判定器看不到对话内容**，「对话框里出现母亲说的话」这类判据
  **永远不可能被判成立**——任务从一开始就注定失败，而没有任何地方报错。
- **决策模型看不到**，于是按先验编一句当成自己读到的。实测编出了
  `OAK: Hello there! Welcome to the world of POKéMON!`。

判定器自己把根因说出来了：`{"done": false, "why": "对话框内容未提供，无法确认是否为母亲说的话"}`。
**它是对的，而我们四处找别的原因。**

修：`facts["dialog_text"]` 排在 overlay 之后、其余一切之前；`Snapshot` 也加上
（对话跨步骤成立——那句话说过就是说过了）。

**2. 地图黑边被认成对话框。**

室内地图下方那一整片纯黑是**地图边界**，被判成了 `overlay=dialog`——
而同一帧（frame sha 一模一样）上一步它还判的是 `none`。

两处一起修：

- prompt 里给出唯一可靠的判据：**对话框是白底黑框有黑字**，黑边没有白底、没有边框、
  里面没有字；并加一条自检——"你能从里面抄出文字吗？抄不出来就不是对话框"。
- 代码里加交叉检验：`overlay=dialog` 而 `dialog_text` 为空 → **降级成 `none`**，
  并记 `perception_warning=dialog_without_text`。这不需要任何新输入，
  **只是拿模型自己的两个输出对账**。要紧在于 `overlay` 决定动作掩码：
  判错一次大脑就会拿到一组按不出效果的动作，然后照着它按好几步。

**3. 同一帧被反复感知。** `step()` 原来无条件清缓存，于是"对着空地按 a"这种
什么都没发生的一步照样花一次感知调用。实测连着四步 frame sha 一模一样，模型却给出了
三种不同的 `overview`，其中一步就是上面那个假对话框。

修：`step()` 不再清缓存，交给 `_perceive()` 的帧哈希判——画面真变了一定会重新调，
没变就直接返回。**同一帧只问一次，这类抖动直接消失，顺带省钱。**
实测连按 4 步 `a` 撞空气，感知调用从 4 次降到 1 次。

**4. 记忆没说"什么都没发生"。** 实测：

    step 7   按 a（对着空地）→ 什么都没变
    step 8   取回 step 7 的记忆，照着自己上一步那句"站在门格上按 a 是开门的标准操作"，
             **再按一次 a**
    step 9   同上        step 10  同上

记忆忠实记下了"没变化"，但那个事实藏在两块结构相同的文本里没被读出来——
**它把过去的 `rationale` 当成了权威，而权威说的话恰恰是错的**。

修：`MemoryEntry.render()` 直接写「**之后变成：什么都没变**（位置、四邻、对话框
全部相同——这个动作没有效果）」。判定是纯比较，我们做得又快又准，不该留给它。
比较**不含 `overview`**：那是模型每次重写的自然语言，同一帧也会给出不同措辞，
拿它比会把"没变"误判成"变了"。

**影响面**：`world/pyboy_world.py`、`schemas/core.py`、`prompts/perceive_screen.md`；
`tests/test_world_smoke.py` 新增 3 条、`tests/test_memory.py` 新增 1 条。
82 个测试通过，ruff 干净。

## 2026-08-20 —— max_tokens 提到 25600；MAP_HINT 补换算公式和数字符的规矩

**改了什么**：`QwenText` 的 `max_tokens` 从 3072 提到 25600，`build_real` 和
`probe.run_episode` 加 `--max-tokens` 透传。`MAP_HINT` 重写两节。

**为什么提 max_tokens**：实测单步 `thought` 到过 2235 token，离 3072 只剩八百，
而那还是它在**和自己的记忆吵架**的情况下——真正需要长推理的局面还没出现。
**这是上限不是预算**，只在模型自己想说这么多时才花得掉；判定那条链路每次输出
二三十个 token，抬高上限对它没有任何影响。真正控成本的是 `max_steps` 和 prompt 长度。
（各家模型对 `max_tokens` 有硬上限，qwen-plus 一档通常是 8192，被 API 拒了用
`--max-tokens` 调低，别改默认值。）

**为什么改 MAP_HINT**：一局实测里模型花了 1938 token / 43 秒，全用在"这两套坐标
对不上"的自我拉扯上。查下来**我们给的数据是对的，它自己推的换算公式也是对的**，
错的只有两处纯机械操作：

- `##...S#D##` 里 `##...` 是三个点，它数成两个，于是断定 `S` 在列 4（正确是 5）。
  同一句话里它又说 `D` 在列 7——S 在 4 的话 D 就该在 6，句子本身自相矛盾。
  拿这个错值去反推偏移，和 `landmarks` 的 `x=11` 对不上，
  于是**认定是我们的数据矛盾**，开始反复重数。
- 同一段推理里把 `(列,行)` 和 `(行,列)` 混着用：门在 `(7,7)`，它写"南邻是 `(8,7)`"
  ——按我们的写法那是第 7 行第 8 列，是墙。

所以补的不是"再强调一遍"，是三样具体的东西：

1. **直接给换算公式**（`c = 4 + (x - X)`，`r = 4 + (y - Y)`），并写明"照抄，不要自己推"。
   它每步都在重新推导同一个常量公式，推对了也白花几百 token。
2. **怎么数字符**：对着列号表头竖着看，别在心里从左往右数；直接把
   `##...S#D##` 那个例子和正确答案写进去。
3. **一条自检**：算出来的和 `landmarks` 对不上时，**是你数错了，不是数据错了**——
   两者同一帧来自同一份内存，不可能矛盾；重数，不要花篇幅论证哪边可信。

**取舍**：讨论过是否把寻路整个拿走（对每个地标做 BFS，直接给方向串）。
那不会增加任何信息——`walk_map` 里本来就全有，只是替它做那步算术。
但那样导航就不再是 agent 的能力，实验里"它会不会走路"这一维会消失。
**决定保留**，先只把说明写硬，看这三条能不能压住。

**影响面**：`providers/dashscope.py`、`build.py`、`probe/run_episode.py`、
`tools/game_tools.py`。78 个测试通过，ruff 干净。

## 2026-08-20 —— 地标改成「内存出的类型 + 全局坐标，没有名字」

**改了什么**：删掉 `ScreenState.labels` 和感知 prompt 里那一整节；
`facts["landmarks"]` 改由 `TerrainMap.landmarks()` 产出，形如
`门 x=13 y=5; 招牌 x=11 y=5`。新增 `facts["neighbors"]`（`北 . 南 G 西 # 东 .`）。
`Snapshot` 去掉 `walk_map`、加上 `neighbors`。

**为什么这么改**：真跑一局暴露了两个问题，根因不同，但都是**我们给了模型一个
它没法正确使用的东西**。

### 一、名字是编的，而且**不可能不编**

实测输出：`写着「POKéMON CENTER」的招牌 (1,7); 写着「POKé MART」的招牌 (5,3)`。
**真新镇既没有宝可梦中心也没有商店。**

根因不是 prompt 不够严——前两轮已经收紧过两次了。是**总览画面里没有可以支撑那个
名字的证据**：招牌上的字根本没渲染（要走过去按 A 才弹对话框），所有的门都是同一个
深色矩形。它没有输入，只能按先验补，而先验里"宝可梦小镇"就该有中心和商店。

名字只有三个可能来源：

- **内存**：warp 表里带着目标地图编号，精确。**但那是"世界怎么连起来"，
  正是长程记忆要学的东西**——白送给 agent，等于把这个项目要证明的事删掉。
  （`walk_map` 读内存是另一回事：它替代的是"这一格能不能走"，游戏自己每帧都在算，
  属于低层控制。这条线要划清楚。）
- **视觉模型**：三轮实测全在编。
- **经验**：走进去看见了什么，然后记住。**只有这一个是对的**，而它还没做。

所以现在只给类型和位置，名字留空。`MAP_HINT` 里明写："想知道招牌写什么，走过去按 a；
想知道门后面是什么，走进去。看到过什么就记进 rationale。"

### 二、屏幕格坐标进了记忆，模型花两千 token 和自己吵架

`MAP_HINT` 里我们自己写着屏幕格"**不能跨步骤引用**"，然后把带屏幕格的 landmarks
和整张 `walk_map` 存进记忆、下一步又喂回去。

实测：step 1 取回 step 0 的「民宅的门 (7,7)」，对照当前地图发现 `(7,7)` 是 `#`，
于是花了 **2235 个 output token、49 秒**反复重数那一行字符串，试图判断是记忆错了
还是地图错了。**两边都没错，是我们给的数据自相矛盾。**

修法：地标改用全局坐标（纯算术：`全局 = 主角全局 + (屏幕格 - PLAYER_CELL)`，
不读新内存），跨步骤永远成立。`walk_map` 从 `Snapshot` 里删掉——它的原点跟着人走，
没有稳定的坐标系可以承载。

**取舍：那"这一下改变了什么"靠什么看？** 靠 `position`（全局坐标）和
`neighbors`（相对"我"的四邻）：撞墙 → 前后 position 一模一样；进门 → 地图编号变了；
"我以为西边能走" → `neighbors["left"]` 白纸黑字写着当时是什么。四邻不依赖屏幕原点，
所以跨步骤成立；整张图能多告诉你的只是"当时周围什么形状"，而那个信息没法安全地存。

**影响面**：`schemas/core.py`（删 `labels` 及其校验器、改 `Snapshot`、
`named_cells`→`landmarks`）、`world/pyboy_world.py`、`tools/game_tools.py`
（`MAP_HINT` 重写两节）、`prompts/perceive_screen.md`（删「写 labels」整节）；
`tests/test_screen.py`、`tests/test_prompts.py`、`tests/test_world_smoke.py` 跟着改。
78 个测试通过，ruff 干净。

实测效果：`门 x=13 y=5` 在第 0 步的记忆里和第 1 步的当前帧里**是同一个坐标**，
不可能再矛盾；走到 x=9 y=6 时 `门 x=5 y=5` 进入视野——那才是通往家的那扇门。

## 2026-08-20 —— 删掉 `Observation.goal`（目标栈接进来之后它就没有消费方了）

**改了什么**：`Observation` 去掉 `goal` 字段；`PyBoyWorld.observe()` 不再填它；
`Harness._observe()` 的盖章不再写它。

**为什么这么改**：顺着"每一次 `model_copy` 盖的章，谁在读"查了一遍，
发现 `Observation.goal` **一个读者都没有**：

- `Brain.choose` 原来 `assert obs.goal`，目标栈接进来之后改成了 `assert goals`；
- prompt 走 `_render_goals(goals)`，不读 `obs.goal`；
- `Brain.judge` 读的是 `Goal.goal`（栈上某一层），也不读它；
- `Snapshot.of()` 只取 facts 里的 overview / where / walk_map / landmarks。

留着不只是浪费一次赋值，**它是有误导性的**：字段说明写着"当前任务目标"，
而 agent 当下在做的是**栈顶**那条，任务目标只是栈底。谁顺手拿 `obs.goal`
去渲染点什么，拿到的就是错的那一条，而且不会报错。

顺带确认了一件分层上的事：**world 根本不需要知道任务目标**。
`reset(task)` 里的 `task` 现在只用于断言 `max_steps > 0`，以及将来按不同任务
选不同起始存档。三个接口文档里"后置条件 goal == task.goal"那句一并改掉。

**影响面**：`schemas/core.py`、`world/pyboy_world.py`、`harness/harness.py`、
`interfaces/{world,tools}.py` 的文档。78 个测试通过，ruff 干净。

## 2026-08-20 —— 过一遍 run_episode 整条链路，修 4 处

用假 provider 把 `probe.run_episode.main()` 原封不动跑了一整局（含一次故意的解析失败），
盯输出发现的：

**1. `task_id` 写死成 `"explore-pallet"`。** 而 goal 从命令行来。
**`task_id` 是成功率的分组键**——写死意味着换个目标跑出来的两批数据会被当成同一个
任务聚合，算出来的成功率没有意义。改成从目标文本派生（同一目标 = 同一 id，跨进程稳定），
可用 `--task-id` 覆盖。

**2. `remember` 那块在控制台被压成一行。** `_wrapped()` 直接 `textwrap.wrap(text)`，
它把换行当空白吃掉——于是记忆里那张 10x9 的 walk_map 变成一条横着的字符串，
**正好是这一步最该看清的东西**。改成先按原有换行拆、再对每行折行。
顺带去掉重复的 `(episode_id, step)` 前缀（`MemoryEntry.render()` 开头本来就是它）。

**3. `GameTools._last_space` 现在连帧哈希一起存。** 上一轮审查里我标了"目前无害"
就没修，这是偷懒——那条断言的全部意义就是拦住将来的错误。
原来只检查按键名在不在上一轮清单里，而 `a` 在野外 / 对话框 / 选择框下都可用：
**名字对得上不代表语境对得上**。只要将来有一类"不经过 look 直接 press"的路径
（重试、宏动作、skill library），断言就会放行一个按旧语境选的键。
现在换帧即失效，当场炸。

**4. 汇总加了「动作」一行**：按键 / 细看 / 拆子目标（完成 N / 作废 N）。
这是目标栈和细看这两个机制唯一的直接证据——拆十条弹十条看着很好看，
但如果八条是 `superseded`，说明它在乱拆不是在规划。
同时标明 `perception` 那一行**含细看**（走的是同一个视觉模型、另一份 prompt）。

顺带在 `--criteria` 的默认值上写明：那句"画面上出现能直接证明这个目标已达成的证据"
是**同义反复**，只够跑通链路；真做实验必须给一句只看一帧就能判真假的话，
否则判定器只能凭"看起来差不多了"回答。

**影响面**：`probe/run_episode.py`、`probe/echo_trace.py`、`tools/game_tools.py`。
78 个测试通过，ruff 干净。

## 2026-08-20 —— 审查修一批：记账、异常边界、细看的堆积

**改了什么**：两轮独立审查（一轮盯 harness 循环，一轮盯 world / tools）跑出来的问题，
按严重程度修完。

**1. `last_calls` 改成 `drain_calls()`** —— 这是最要紧的一条，而且**两个方向都错过**：

- 原来由**生产方**在下一次感知时清空，但**缓存命中时不清**。于是不推进世界的那些
  轮次（`inspect` / `push_goal`）会把上一轮的账**再记一遍**。实测一局 3 次真实
  VLM 调用、trace 里 4 条 MODEL_CALL，其中两条逐字节相同。更糟的是 `inspect` 的账
  （`prompt_sha` 是 `inspect_focus`）被当成"产生这一帧观测的感知调用"记进
  `Source.PERCEPTION`——**prompt 归因跟着错乱**。
- 改成"进门就清"之后翻到另一边：`reset()` 里那次真实调用的账，被紧接着那次
  命中缓存的 `perceive()` 冲掉，**钱花了但没有记录**（实测 4 次调用只记了 2 条）。

两个方向都错，说明问题不在时机而在归属。改成由**记账的人取走**：
`WorldPort.drain_calls()` / `ToolHost.drain_calls()`，world 内部改成 `_pending_calls`
只追加。不变量变成**每次调用恰好记一次账**，由调用次数本身保证，不依赖调用顺序。
新增 `test_every_vision_call_is_billed_exactly_once` 钉住——成本不会自己报错，
多记少记只体现在月底账单和实验表格上。

**2. 异常逃出 `run()` 时补 `EPISODE_END`（`reason=error`）。** 不补的话这一局在
事件流里永远"没有结束"，离线统计时既不在成功也不在失败，**直接从分母上消失**——
而 `MaxRetriesExceeded` 恰恰是最该被记成失败的那一类。记完照常往外抛。

**3. `_notes` 改成按 focus 去重的 dict，加 `MAX_NOTES=4` 上限。** `inspect` 不推进
世界，所以 `step()` 里那次清空永远轮不到，一帧里能一直问。实测连问 6 次同一个问题，
`facts["inspected"]` 从 0 涨到 231 字符，**同一条答案被原样拼了 6 遍**。
重复的事实比过期的更糟（模型当成强证据），而这段文字**同时进决策 prompt 和判定 prompt**。

**4. 三处"契约说不抛异常，但失败点在 try 外面"：**
- `world.inspect()` 的取帧 / 读内存 / `render()` 全挪进 try（`render` 用的是
  `Template.substitute`，模板少一个占位符就抛 `KeyError`，而 prompt 是最常改的文件）。
- `Brain.judge()` 的 `render()` 同样挪进 try —— 它是被 `_judge_all` **并发**调用的，
  一个 worker 抛出来会穿过整个循环，把一次本该记成"判定失败"的事件变成一局丢失的数据。
- `Brain._parse` 的 `except` 加上 `ValidationError`：`Action` 的 model_validator 抛的是
  `ValueError`，pydantic 包成 `ValidationError`，**不是 `AgentError` 的子类**，
  不带上就会穿过重试直接崩掉一整局。当前不可达（`_parse` 自己先验了一遍），
  但那意味着同一套校验写了两遍且没有同步机制。

**5. 感知失败的重试现在会产出 `ERROR` 事件。** `_observe` 原来固定构造
`ModelCall(payload=call)`，`error_kind` 永远是空，于是「视觉模型输出解析失败」这一类
**永远不出现在失败模式分布里**——而 world 明明已经把 `ok=False` 标好了。

**6. `_judge` 的 `succeeded` 早退分支现在会打上 `done/success`。** 当前图里走不到，
但 resume 会：从 `succeeded=True` 的 checkpoint 恢复时，不打标记的话 `_look` 不出
outcome、转而进 `think`，而那时 `goals` 已经是空的，`brain.choose` 的断言当场崩。

**7. `_parse_intent` 的回退路径现在也过掩码。** 原来 `intent` 缺失但有 `action` 时
直接 `return Intent.PRESS`，跳过了 `intent not in space.intents` 检查。
今天 PRESS 恒可用所以安全，但真掩掉的那天症状会是 `AssertionError` 而不是可重试的
`IllegalAction`。

**8. 修正两处文档。** `perceive()` 的后置条件原来写"同一帧内多次调用返回相同内容"，
而 `inspect()` 之后 facts 会多一条——两条契约直接打架。改成"幂等只对模型调用成立"。
`_observe` 的 docstring 里"实测 3 步一局共 4 次感知"那个数字**就是从被重复计数的
trace 上读出来的**，删掉。

**影响面**：`interfaces/{world,tools}.py`、`world/pyboy_world.py`、`tools/game_tools.py`、
`brain/brain.py`、`harness/harness.py`；`tests/test_goals.py` 新增 3 条回归。
78 个测试通过，ruff 干净。

## 2026-08-20 —— 目标栈 + 三类意图（press / push_goal / inspect）

**改了什么**：大脑每一轮不再只会按键，而是从三类事里选一件（`Action.intent`）：

    press       按键，推进世界。**唯一不可逆的一类。**
    push_goal   把当前目标拆一层压进栈，带判据
    inspect     对同一帧再问一个具体问题（另一份 prompt），世界不动

图变成 `look → think → (press | push_goal | inspect) → look`。
**分派放在图的边上，不是节点里的 if**——加一类 = 加一个枚举值 + 一个节点 + 一条边。

`LoopState` 多一个 `goals: list[Goal]`。`goals[0]` 恒为任务目标。
`look` 每步判定，`Brain.judge(goal, obs)` 从 `(task, obs)` 改成收一条 `Goal`
（目标 + 判据），任务目标和子目标走同一个方法、同一份 prompt。

新增：`Intent` / `Goal` / `ModelCall` 之外的 `EventType.INSPECT / GOAL_PUSH / GOAL_POP`；
`WorldPort.inspect()` 与 `prompts/inspect_focus.md`；`tests/test_goals.py`（5 条用法）。

**为什么这么改**：没有目标栈时，模型每一步都要从"走回家"重新推一遍完整路径，
中间结论（"先往北两格再往西"）走完一步就丢了，只在 `thought` 里躺着，进不了下一步的输入。
目标栈就是那层工作记忆——它有完成状态，所以不是知识，该由运行时状态保持。

**取舍与踩到的坑**：

- **每层各判一次（并发），最深的那条"已完成"连同它上面的全部出栈。** 一条规则，没有特例。
  中间写过两版都是错的：先是"只判栈顶"——那样栈上压着未完成的子目标时任务永远轮不到判，
  而任务完全可能顺手完成（压着"走到门口"往那边走，路上母亲先说话了），
  这类局会被记成 max_steps_exceeded，**成功率被系统性地压低**；
  改成"先判栈底，再从栈顶往下弹"之后是两段特殊逻辑，而且**判不到中间层**——
  `[任务, A, B]` 里 A 完成了发现不了，会继续做一个只为 A 存在的 B。
  现在的规则同时覆盖这两种情况。
- **判定并发发出，不合并成一次调用。** 一步最多 `MAX_GOAL_DEPTH` 次判定，串行的话
  墙钟就是它们的和。合并成一次能省调用，但会丢两样东西：**判定之间的隔离**
  （模型同时看到任务目标和子目标，会开始互相推理"子目标成了任务应该也快了"，
  污染源只是从决策模型换成了栈上的其他目标）和**可标定性**（单目标判定是干净的
  二分类 `(目标, 判据, 帧) → 0/1`，合并后输出是长度可变的向量，
  而且同一份 prompt 在栈深 1 和栈深 4 下不是同一个东西，误差不再独立）。
  而这几次调用天然独立，**并发就够了**：延迟是 `max` 不是 `sum`，和合成一次一样快。
  实测 18 次 × 0.3s 的假判定，串行 5.4s，并发 2.0s。
  代价是没有提前退出了（顺序版判到第一条完成的就停），用 token 换墙钟。
  token 那一头由 prompt 字段顺序解决：`judge_success.md` 改成
  「固定说明 → 画面 → 目标+判据」，同一步内的几次调用共享一大段前缀，
  重复的 input 基本免费；原来是目标在最前面，**前缀缓存一点都吃不到**。
- **模型调用并发，写 trace 不并发。** `event_id` 必须单调，那是 SSE 断线补发的
  唯一依据；多线程写进去会乱序甚至重号。所以只并发拿结果，记账回主线程按 depth 顺序做。
- **出栈理由分 `done` 和 `superseded`。** 上面那些不是完成的，是失去意义的。
  不分开就算不出**拆出来的子目标有多少是白拆的**——而那是判断目标栈帮没帮上忙的那个数。
- **子目标完成只弹栈，绝不写 `success`。** 子目标是 agent 自己定的；能写 success 的话
  它可以压一个"我已经到家了"的子目标让判定器判它完成，成功率变成它自己发的奖状。
  这条落在 `_judge` 的 `while len(goals) > 1` 上，不是一句注释。
- **`inspect` 必须带 `focus`。** 不带就是把同一帧原样再看一遍——`perceive()` 帧内缓存，
  返回的字节完全一样，零新信息，而模型拿不准时一定会选它，然后下一轮看到同样的画面
  再选一次。带上具体问题、走 `inspect_focus.md`，才真的产出新事实。
  答案并进 `facts["inspected"]`，`step()` 之后清空（它只对那一帧有效）。
- **`push_goal` / `inspect` 也算一步。** 它们同样烧一次决策调用；不算的话
  `max_steps` 管不住"一直拆、从不走"。代价是"走了几格"和"想了几次"混在一个数里。
- **栈深上限靠掩码，不靠 prompt 劝。** 到 `MAX_GOAL_DEPTH`（4）之后 `push_goal`
  从 `space.intents` 里掉出去。说明和可选项必须一致——只在 prompt 里劝的话，
  模型照样会选，白花一轮再吃一条 IllegalAction。
- **记忆只在 `press` 时写。** 另外两类世界没变，`after` 和 `before` 是同一帧，
  写进去就是一堆"结果：什么都没发生"，会稀释检索。
- 第一版 `inspect()` 里清了帧缓存想让 facts 重组装，结果 `_perceive()` 重跑了一遍
  正常感知：**多花一次钱，还把 `last_calls` 覆盖成那次调用的账**，细看的账丢了。
  实际上 `observe()` 每次都从缓存重新组装 facts，根本不用清。测试抓到的。

**影响面**：`schemas/core.py`、`interfaces/{brain,tools,world}.py`、`brain/brain.py`、
`tools/game_tools.py`、`world/pyboy_world.py`、`harness/harness.py`、
`prompts/decide_action.md`（重写输出格式）、新增 `prompts/inspect_focus.md`、
`probe/echo_trace.py`（新事件类型的显示）。74 个测试通过，ruff 干净。

旧格式（只有 `action` 没有 `intent`）仍然被当作 `press` 接受——语义无歧义，
为它跑一轮重试不划算，判据同 ```json 包裹。

## 2026-08-20 —— episode 状态整体上移进 LoopState，Harness 变成无状态

**改了什么**：`Harness` 的五个实例字段（`_episode_id` / `_task` / `_step` /
`_succeeded` / `_why`）全部挪进 `LoopState`。现在 `Harness` 只剩三个协作者
（tools / brain / trace）和一张编译好的图——**它自己没有任何状态**。
`_observe` / `_judge` / `_outcome` / `_record_call` 改成收 state 参数。

**为什么这么改**：判据从「它活多久」换成了**「它会不会影响下一个 prompt」**。

原先那条只对活对象成立：world / tools / brain / trace 确实序列化不了，不能进 state。
但 episode 的身份是**纯数据**，而且恰恰是 checkpoint 唯一需要的那部分。
放在实例字段里，等于把"跑到哪了"存在了一个 checkpointer 看不见的地方——
接上 LangGraph 的 checkpointer 也恢复不出第几步、在跑哪个任务。

**取舍**：
- 方法签名变长（多一个 `state`），换来"跑到哪了"只有一个存放处，而且能 dump 成 JSON。
- `_observe()` 现在返回三元组 `(obs, succeeded, why)` 而不是一个 Observation。
  丑一点，但"判过成功就不再问"必须跨步存活，它就得写回 state。
- **没有一起加目标栈。** 先把存放处修对，再往里放新东西。

**光有 LoopState 仍然复现不了**，这一点写进了模块 docstring：
还差记忆库（`GameTools._memories`，进 prompt 但不在存档里）和 `world._facing`
（朝向是从我们自己的动作历史推的，pyboy 的 save state 里根本没有它）。
补法是阶段 2 的 `Checkpoint` = LoopState + 记忆库 + 模拟器存档 + world 推导状态 + manifest。

**影响面**：只动 `harness/harness.py`。69 个测试全过，ruff 干净。

## 2026-08-20 —— 重划 brain / tools / harness 三层

**改了什么**：三层全部重写并改名。

    以前                         现在
    harness/harness.py (工具)    tools/game_tools.py  `GameTools`
    graph/build.py (循环)        harness/harness.py   `Harness`
    brain/react.py               brain/brain.py       `Brain`
    harness/judge.py             并进 `Brain.judge()`
    —                            build.py（只做装配）
    —                            interfaces/brain.py  `BrainPort`
    ToolPort                     拆成 `ToolPort`（大脑看的）+ `ToolHost`（Harness 看的）

职责按一句话切：**Brain 管一切要 LLM 的判断，Tools 管碰环境，Harness 管循环。**
`step` / `done` / `success` 的所有权上移到 `Harness`——world 不再数步，
`Observation.step` 由 `Harness._stamp()` 盖章。`PyBoyWorld` 只保留一个终止权：
窗口被关（`_closed`），因为那时候世界真的没了。

`ReActBrain.remember()` 变成 `Brain.reflect()`：**只返回 `MemoryEntry`，不落库**，
落库由 Harness 调 `tools.memory_write`。

**观测只在 `look` 节点产生**：`Harness._observe()` 是全项目唯一给
`step` / `done` / `success` 赋值的地方，而它只有 `_look` 一个调用方，
所以"一步一次观测"是调用图的形状本身，不需要任何字段去保证。
（第一版曾拆成两个产出点——开局一次、`act` 里执行完再一次——为的是省一次
`perceive()`。那是错的：world 按帧缓存，`look` 里再读一次不产生任何模型调用，
而拆成两处的代价是"每步观测一次"在代码里看不出来。实测 3 步一局共 4 次感知调用。）

分支只有一个，在 `look` 出口：**看完才知道这一局还要不要继续**。
放在 `act` 出口的话，"步数用尽"和"任务达成"要在两个地方各判一次。

**为什么这么改**：按步去重（`_traced_step` / `_judged_step`）是个补丁，
它在补的是一个信息缺口——"新的一步开始了"这件事调用方知道，harness 只能靠
`obs.step` 去猜。而 step 有三个主人（world 数、harness 猜、图决定一轮），
才需要互相对账。实测症状是步号 1 → 0 回退、判定每步跑两次（成本翻倍且不报错）。

根因是命名：叫 harness 的那个类其实是工具层，真正控制循环的是图。
名字盖住了职责，职责就没法归位。改名之后每件事只发生在一处，
两个去重字段不是被修好的，是被消掉的。

**取舍**：
- `Brain` 现在有三个方法、两个 provider，比单一职责的类"胖"。接受，因为
  "所有 LLM 调用的集合"本身就是一条有意义的边界（记账、换型、标定都按它切）。
  代价是 choose/judge 的隔离从类型层面降到约定层面，靠两条硬约束顶着：
  `judge()` 只收 `(task, obs)`；`judge_llm` 是独立实例。
- `Brain.reflect()` 目前**没有模型调用**，是纯格式化。「存入前的修饰」的挂载点
  留在那里，但现在开它就是每步第三次调用，而检索本身还是字符重叠——
  没有任何证据说明修饰过的条目检索得更准。等向量检索接上再开。
- 仍然用 LangGraph 而不是 while：转移条件是显式的边，将来插节点
  （状态归并、值回填、成本熔断）不用改循环体。

**Harness 是唯一写 trace 的人。** 全项目 `trace.append` 只出现在 `harness/harness.py`。
`Brain` 构造函数里没有 `TracePort` 了，三个方法也都不收 `episode_id` / `step`——
它把账（新增的 `ModelCall`）连同结果交出来，由 Harness 翻译成事件：

    brain.choose() -> Decision(action, calls, recalled)
                   -> MEMORY_READ + MODEL_CALL×N + ERROR×失败次数 + THINK
    brain.judge()  -> Verdict(done, why, call)   -> MODEL_CALL(judge) [+ ERROR]
    brain.reflect()-> MemoryEntry（episode_id 由 Harness 盖章）

`choose()` 重试用尽时**返回 `action=None` 而不是抛异常**——`MaxRetriesExceeded`
由 Harness 抛，因为"这一局是否因此终止"是循环的判断，大脑只如实汇报。

上一版的分布是：brain 写 MODEL_CALL / THINK / ERROR / MEMORY_READ，
harness 写 ACT / MEMORY_WRITE / OBSERVE / EPISODE_*，于是"某类事件归谁写"
要一条条记；更糟的是为了让判定器碰不到自己的账，还给 `judge` 开了个不写 trace 的
例外——**用例外弥补一条不统一的规则**。现在规则只有一句：**谁控制循环，谁记账。**
判定器碰不到自己的账不再是特权设计，而是所有大脑调用的共同处境。

顺带修正一处对称性：`MEMORY_READ` 和 `MEMORY_WRITE` 以前分属两个类，现在都在 Harness
（仍在不同节点，因为它们本来就发生在一步的两头）。

**影响面**：`probe/run_episode.py` 改成 `harness.run(episode_id, task)` 一行；
`tests/test_memory.py`、`tests/test_judge.py` 按新 API 重写；
`tests/test_world_smoke.py` 里两条断言 world 记 step 的改成断言它**不**记。
69 个测试通过，ruff 干净。

## 2026-08-18 —— 论据进记忆：Action 加 rationale，thought 只进 trace

**改了什么**
`Action` 新增 `rationale: list[str]`（1-`MAX_RATIONALE` 条，必填），`thought` 从
`default=""` 改为必填非空。`_parse` 拆出 `_parse_thought` / `_parse_rationale`，
两类缺失各自单列 reason。`remember()` 改用论据合成记忆内容，prompt 模板相应改写。
另修两处旧问题：ACT 事件的 step 改用执行前的值；删掉 `observe` 节点里不可达的
done 分支。测试 9 → 13，ruff 由 1 个 I001 转全绿。

**为什么这么改**

先是发现 `thought` 根本没跨步：它唯一的消费方是 `trace.append`，`remember()` 拼
记忆时不含它。推理产出后立刻被截断，再也不进入任何后续决策。这与本项目自称 ReAct
是矛盾的——ReAct 的分界线不是"先想后做"（那太平凡），而是**第 t 步的 thought 能不能
被第 t+k 步看见**。原论文的 HotpotQA 轨迹里 thought 与 action 本就是同一步给出的，
所以"thought 是不是独立动作"不构成判据，**能不能跨步**才是。

但这是实现没落地，不是设计选择——设计一直打算让推理跨步，走检索而不是拼接。
于是**保留 ReActBrain 这个名字**，把代码补上。

顺带纠正一个此前想反了的问题：**检索式 scratchpad 不是对机制三的妥协，是让
scratchpad 与 episodic control 共存的解法。** 原版 ReAct 的上下文随步数单调增长，
同一个状态在第 3 步和第 300 步面对的输入必然不同，这才是系统性破坏近似 Markov 性
的那个；而按状态相关性检索，相似状态取回相似记忆，被注入的内容近似是**状态的函数**，
反而维持了它。附带收益是上下文不随步数爆炸，长程任务上才跑得下去。

那么跨步的该是什么？不是完整推理，也不是结论：

- **结论**（"所以该捡药水"）可以从 `name` 反推，存进去等于把同一件事存两遍。
- **完整推理**里大部分是本次决策的中间步骤，对未来无用，还挤占检索名额与 token。
- **论据**（"地上有药水而我手上没有"）才是 `name` 里没有的信息，而且它是**适用条件**
  ——未来取回这条经验时可以检查它现在还成不成立。结论做不到这件事。

所以分工定为：`thought` 服务本次决策的质量（长度即算力，不设上限，只进 trace），
`rationale` 服务未来的迁移（短、可证伪、进 memory）。

还有一个白拿的性质：记忆条目由「模型出假设 + 世界出判决」拼成，天然**自带标签**
（"我以为 P，结果 R"）。一条错误论据被取回时反例就贴在同一行，不会被当成知识使用。
这让"记忆被无用内容污染"的风险比预想的低——脏东西是带标签的脏东西。

**取舍**

- **论据不区分时效性，一律按有时效处理。** 曾考虑给持久知识（"馆主是火属性"）单独
  开池 + 去重，因为它会被反复产出。放弃了：rationale 是**条目内部的字段**，重复只
  造成 token 膨胀，**不占检索名额**，危害远小于估计。代价是持久知识只能绑在发现它
  的那一步上，跨状态检索不到——那属于 skill library（机制二）的范围。
- **超上限打回重试，不截断。** 模型认为 N 条都承重，悄悄丢一条是替它做了个没有记录
  的决定。代价是这类重试要花 token；实测占比高再改成截断。
- **单条写成裸字符串则容忍**，不消耗重试。判据同 ```json 包裹：常见格式偏差、语义
  无歧义、为它跑一轮重试不划算。
- **`MAX_RATIONALE` 抽成常量**。它有两个执行点（`Action` 的字段约束 = 数据契约，
  `_parse` = 外部输入校验），写死两遍迟早漂成"解析器放行、构造时炸"。
- **缺失用 reason 字符串区分，不新增异常类型**。replay 按 reason 聚合就能把"格式坏"
  和"不肯给论据"拆开，够用了，不值得为它多一个异常类。
- **ACT 的 step 取自 `get_action_space()` 时缓存的值**，而不是执行后 `-1`，也不是
  重新 `observe()`。后者在真实模拟器上是「截图 + VLM」，为记一条日志再感知一次太贵；
  前者依赖 world 的后置条件做减法，且 observation 为 None 时无解。缓存复用的是
  `get_action_space()` 里已经取到的那次观测，免费且在两条路径下都正确。
- **`observe` 的 done 分支直接删，换成一条 assert**。它永远不执行（两条入边都保证
  未结束），而且返回 `action_space=None` 会让下一节点的 assert 崩在更远的地方——
  按第三节第 4 条的判据，不改变行为的"防御"不该存在。

**影响面**
`Action` 的构造点只有 `_parse` 一处，无其他调用方受影响。`MemoryEntry` 签名未动，
key 仍是 step 占位。`FakeLLM.scripted()` 自动把 thought 复制为 rationale，因此所有
只关心动作序列的既有测试一行未改。ACT 的 step 修正会改变 trace 的形状——阶段 2 的
按 step 聚合建立在这次修正之上，**先改再堆**。

## 2026-08-13 —— 更正：harness 与 trace 也是 mock，移进 mocks/

**改了什么**
`harness/harness.py` → `mocks/mock_harness.py`（类名 `Harness` → `MockHarness`），
`harness/trace.py` → `mocks/mock_trace.py`（`InMemoryTrace` → `MockTrace`）。
`harness/` 包不再使用（挂载盘不允许删除，其 `__init__.py` 已移到 `_to_delete/`，
请在本地删掉这个空目录和 `_to_delete/`）。两个模块的 docstring 重写，明确列出它们缺什么。

**为什么这么改**
上一条我用"是否完整实现契约"当判据，把 InMemoryTrace 归成了真实实现。判据用错了。
**这一阶段的范围是"只做大脑，其余全部 mock"**，harness 和 trace 都在"其余"里：

- MockHarness 的 masking 是写死的 if 分支（不是从状态表查）、记忆检索是字符集重叠
  （没有 state abstraction、没有值回填），六件套只有 trace 一件，
  缺权限确认、沙箱、成本控制、checkpoint、replay，动作空间不会增长。
- MockTrace 只是个内存列表，不落盘、不推流、不做 checkpoint 事件源、不按失败类型聚合。

它们后面是要被**重写**的，不是"换个存储介质"。放在 `harness/` 会让人以为那是成品，
导致后面接着往上堆而不是推倒重来。

**取舍**
保留"替身也严格遵守契约"这一点（MockTrace 的 event_id 仍然真的单调、
MockHarness 的 precondition 断言一个没少）。替身可以简陋，不能违约——
否则换成真实实现时上层会崩，mock 的意义就没了。这条写进了两个文件的 docstring。

`mocks/` 现在有四个文件（fake_llm / mock_world / mock_harness / mock_trace），
对照之下 `brain/` 只有一个 —— 这个比例恰好说明了当前阶段的范围。

**影响面**
纯搬迁与改名，9 个测试仍全绿，ruff 无告警。

## 2026-08-13 —— 最小闭环跑通（mock + harness + 图装配 + 测试）

**改了什么**
新增 `mocks/fake_llm.py`、`mocks/mock_world.py`、`harness/trace.py`（InMemoryTrace）、
`harness/harness.py`、`graph/build.py`，以及 `tests/test_react.py`（5 个单元测试）和
`tests/test_episode.py`（4 个集成测试）。9 个测试全绿，ruff 无告警。

**为什么这么改**
到这一步"最小闭环"才成立：一个任务从头跑到尾、全程有 trace、失败路径有计数。
几个位置的决定：

- **InMemoryTrace 放 `harness/` 而不是 `mocks/`**。判据：实现的是完整契约就进 harness，
  只为让流程跑通的替身才进 mocks。它的 event_id 真的单调、replay 真的能回放，
  和将来的 FileTrace 只差存储介质，而且测试会一直用它（测试不该往磁盘写东西）。
- **masking 在 harness，成败判定在 world**。掩码是策略（什么时候允许买东西是设计决定），
  判定是能力（只有世界知道状态是否满足判据）。这条边界写进了 Harness 的模块 docstring。
- **`execute()` 前要先 `get_action_space()`**，harness 记住最近一次给出的空间做 precondition，
  执行后立即置空——世界推进了，上一次的动作空间就失效了。
- **AgentState 只存流转数据，不存业务状态**。业务状态在 harness 里。
  因为图状态会被 LangGraph 复制、合并、快照，把记忆或世界塞进去会产生意料之外的副本。
- **FakeLLM 支持返回坏 JSON 和 loop 模式**。解析失败与重试是大脑最重要的一条分支，
  没有能制造失败的 mock 就测不到它。

**取舍**
- `memory_query` 用字符集重叠打分，粗糙。故意不上 embedding：
  换向量检索是机制一的事，现在上会掩盖"检索策略属于实现方"这个分层是否真的成立。
- `MockWorld` 的 DEMO_TASK 只有 12 步上限，**不满足 Task docstring 写的下界**
  （必须长到上下文装不下）。代码注释里标了这一点：它只是让闭环跑起来的脚手架，
  真实任务集要另行设计。
- `build_demo()` 返回 harness 和 trace 三元组，比只返回图啰嗦。
  但测试要读 trace 做断言，不返回就得从图里掏，那才是真的破坏封装。

**影响面**
全项目可运行。`pytest` 通过即表示：换真实模拟器只需换 `MockWorld`、
换真实模型只需换 `FakeLLM`，brain 和 harness 一行不动。

## 2026-08-13 —— episode 的边界从"通关"改成"一个任务"

**改了什么**
`schemas/core.py` 新增 `Task`（task_id / goal / success_criteria / max_steps）和
`EpisodeOutcome`；`Observation` 加 `goal` 与 `success` 两个字段。
`WorldPort.reset()` 改签名为 `reset(task)`，`step()` 的契约补上成败判定与终止条件。
`ToolPort.perceive()` 后置条件补 goal。`ReActBrain` 的 prompt 加"当前任务目标"一节，
`choose()` 入口增加两条 precondition（episode 未结束、goal 非空）。

**为什么这么改**
原来一个 episode = 一次通关，粒度太大，三处都出问题：

1. **机制三拿不到信号**。通关是几千步只产出一个 0/1 结果，
   MC 回填的折扣一路乘下去，回填到前期步骤上几乎是噪声。任务级几十到几百步才有梯度。
2. **评测只能报二值结果**。任务级能报成功率、失败模式分布、有记忆 vs 无记忆的对比——
   这才是"提升了多少"要的形态。
3. **迭代周期以小时计**，每改一行都要跑一次通关才有反馈。

**取舍**
- **"长程"这个卖点会被稀释**：任务缩得太小，一个上下文窗口就装下了，记忆架构失去存在理由。
  所以在 `Task` 的 docstring 里写死了下界：必须长到单靠上下文装不下、
  必须跨任务复用经验才做得好。这条判据要在设计任务集时守住。
- 采用两层结构：**episode = 一个任务**（回填与评测单位），**通关 = 一串 episode**（future work，不实现）。
  额外收益是 episodic 记忆有了清晰的作用域：**一条轨迹 = 一个 episode = 一次任务尝试**，
  MC 回填的边界与检索的相关性范围都由此确定。
  （注意别把"跨任务复用的经验"叫 semantic —— semantic 是外部领域知识，
  比如"水属性克制火属性"，来自攻略/图鉴而非自己跑出来的轨迹。
  跨任务复用的成功经验属于 episodic 的聚合，或晋升后进 skill library。）
- 成败判定放在 `WorldPort` 而不是 harness：只有世界知道游戏状态是否满足判据。
  代价是 mock world 要实现判定逻辑。

**影响面**
接口签名变更（`reset`），但尚无实现，无返工。`Task` 与 `EpisodeOutcome` 是新增，
`Observation` 的两个新字段有默认值，不破坏已有构造。

## 2026-08-13 —— 实现 ReActBrain（大脑，唯一的实现代码）

**改了什么**
新增 `brain/react.py`：`ReActBrain.choose()`（一轮 Thought → Action，含重试）、
`remember()`（写记忆）、三个私有方法（`_recall` / `_build_prompt` / `_parse`）。

**为什么这么改**
几个位置的决定：

- **重试放在大脑里，不放在 LLMProvider 里**。因为"什么算失败"是大脑的判断——
  解析不出来算失败、选了不存在的动作也算失败，这两件事 provider 都不知道。
- **ParseFailure 与 IllegalAction 分开抛**。它们在 replay 里是不同的失败模式：
  前者说明格式没学会（改 prompt 或上约束解码），后者说明模型在幻觉动作（改动作说明或收紧掩码）。
  合并成一类就丢掉了这个诊断信息。
- **每次重试重新调用 LLM 而不是复用上次输出**。模型的随机性本身就是重试有意义的原因。
- **`_build_prompt` 每次从参数完整组装，不留历史**。这是"大脑无状态"在代码层面的落点：
  想违反铁律 1 就必须在这里加一个实例变量，很显眼。
- **容忍 ```json 包裹**直接在解析里处理，不消耗一次重试——这是模型最常见的格式偏差，
  为它跑一整轮重试不划算。

**取舍**
- 大脑自己写 trace（COST / THINK / ERROR / MEMORY_READ / MEMORY_WRITE 五类），
  而不是由外层统一收集。代价是大脑多依赖一个 TracePort；
  收益是 token 成本只在 LLM 调用点拿得到，绕出去就要让成本模块认识 LLM 层，破坏分层。
- `choose()` 需要 `episode_id` 参数，签名比"只传 obs 和 space"啰嗦。
  但大脑无状态就意味着它不能自己记住当前是哪个 episode，只能由调用方每次传入。
- prompt 用字符串模板而非模板引擎：原型期够用，且模板内容一眼可见。

**契约落点（对应第三节第 4 条）**
构造函数 assert `max_retries >= 1`、`memory_limit >= 1`（pre）；
`choose()` 入口 assert 动作空间非空（pre）、出口 assert 返回动作在空间内（post）；
`_recall` assert 返回条数不超过 limit（对 ToolPort 后置条件的交叉验证）；
`remember()` assert result 非空（pre）。

**影响面**
新增。依赖四个 Protocol，不依赖任何实现。此时还跑不起来——缺 FakeLLM、MockWorld、
Harness、InMemoryTrace 和图装配。

## 2026-08-13 —— 接口层设计（只有 Protocol 和数据模型，无实现）

**改了什么**
新增 `schemas/core.py`（7 个 Pydantic 模型）、`errors.py`（3 类预期内失败）、
`interfaces/` 四个 Protocol：`LLMProvider` / `ToolPort` / `TracePort` / `WorldPort`。
所有方法只有 docstring 契约，方法体是 `...`。

**为什么这么改**
按"接口先行"，先让 `interfaces/` 成为可读的设计文档。几个关键决定：

- **ToolPort 与 WorldPort 分开**。ToolPort 是"大脑能做什么"（五个 MCP 工具），
  WorldPort 是"世界能做什么"（reset/observe/all_actions/step）。harness 用后者实现前者。
  换真实模拟器时只动 WorldPort 的实现，ToolPort 和大脑一行不改。
  masking 放在 harness 而不是 world，因为掩码是策略不是能力。
- **LLMProvider 做得极薄**，只有 complete()。重试是调用方策略、约束解码将来加新方法、
  对话历史由无状态的大脑每次组装——三样都不进这个接口。
- **TracePort 只有 append 和 replay，没有删改**。append 返回 event_id 而不是事件，
  是为了落盘实现能在这里分配序号；replay 带 after_event_id，直接对应 SSE 的 Last-Event-ID。
- **IllegalAction 异常与 execute() 入口 assert 并存**，针对两个责任方：
  前者是大脑内部发现模型幻觉（外部输入不合法 → 重试），后者防大脑没检查就把动作递出去（调用方 bug）。

**取舍**
- `Action` 里带 `thought` 字段：数据模型里混了调试信息，不够纯粹。
  但 replay 时只知道选了什么、不知道为什么选，价值折半，值这个代价。
- `ToolResult.observation` 可为 None，调用方需另行 perceive()：多一次调用，
  换来"推进世界"和"读取世界"两件事不被绑死。
- `MemoryEntry.key` 本阶段用 step 占位。机制一接进来时这里换成 state abstraction 的语义 key，
  **接口签名不变**——这是检验抽象对不对的试金石。

**影响面**
新增，无既有代码。下一步的实现与 mock 全部按这四个 Protocol 写。

## 2026-08-13 —— 明确 assert 的定位：契约（pre + post + invariant）

**改了什么**
`CLAUDE.md` 第三节第 4 条重写为契约式设计的完整三件套，给了 pre/post 的代码示例，
并补了"不做流程控制/兜底/外部输入校验"的判据。

**为什么这么改**
第一版把 assert 摊成"前置 + 后置 + 各种不变量"，边界糊；第二版矫枉过正只留 precondition，
把 postcondition 推给测试，这是错的——测试只覆盖想到的用例，出口 assert 覆盖所有实际执行。
本项目最核心的主张"大脑不会幻觉出不存在的动作"，最好的运行时证据就是 `choose()` 出口的
一行 postcondition assert。

关于边界，判据收敛成一条可机械判断的：`python -O` 会删掉所有 assert，
删掉后程序行为会改变的东西就不该是 assert。这一条同时排除了兜底、副作用和外部输入校验，
不需要三条独立规则去记。

**取舍**
出口 assert 有运行时开销，且在热路径上会重复检查。原型期不管这个——
真到了性能敏感的地方，`-O` 本来就是关掉它们的正规手段。

**影响面**
规范层面。尚无代码，无返工。

## 2026-08-13 —— 立项：定开发规范与工程配置

**改了什么**
新建 `CLAUDE.md`（开发规范）、`pyproject.toml`（ruff 行宽 100 + pytest）、`.gitignore`、本文件。
尚未写任何业务代码。

**为什么这么改**
项目的架构约束（大脑无状态、依赖单向、trace 是四件事的共同底座）如果不先写死，
原型期会以"先这样以后再改"的名义被逐条破坏，而这几条一旦破了，
后面的 replay / checkpoint / SSE 观测台全部要重做。规范先行的成本远低于返工。

**取舍**
- 上 LangGraph 而不是手写 while 循环：少一次重写，代价是一开始要和框架抽象磨合。
  但只让它承担循环调度，记忆与状态表自己实现，磨合面被限制住了。
- 输出格式先用 Pydantic + 解析重试，不上约束解码：原型期没有真实模型，
  约束解码会把实现和具体模型能力绑死。
- 不引入 mypy / pre-commit：原型期摩擦大于收益，ruff 的 ANN 规则已经强制了类型注解。

**影响面**
全项目。后续所有代码都受 `CLAUDE.md` 约束。
