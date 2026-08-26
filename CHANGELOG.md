## 2026-08-26 —— 帧哈希跟着 `PerceptionResult` 走，删掉 `ToolPort.last_frame_sha`

**改了什么**：`PerceptionResult` 加 `frame_sha` 字段；`PyBoyWorld._perceive()` 把 sha
作为返回值的第一项交出去，`observe()` 填进结果；删掉 `GameTools.last_frame_sha`
（property + `@require_permission("read:game:last_frame_sha")`）与 `ToolPort` 上的声明；
`harness._observe` 改用 `perceived.frame_sha`；`permissions.json` 删掉那条权限串。

**为什么这么改**：

1. **那个权限守不住任何东西**。`GameTools` 自己在 `get_action_space()` 和 `execute()`
   里直接读 `self._world.last_frame_sha` 做动作空间的过期检查，绕过守卫。
   同一个文件里能随手绕过的检查不是边界。
2. **它是 `drain_calls()` 的同一个形状**。`_observe()` 在 `perceive()` 之后再调一次
   去取哈希，而值属于刚刚产生的那一帧 —— `PerceptionResult` 的 docstring 早就把这个
   教训写下来了：让产生它的地方直接当返回值交出来。
3. **前提不成立**。这个字段的全部意义是「这条观测是哪一帧」，用第二次读取的结果去
   回答第一次读取的归属，逻辑上就不对。单线程下现在不会错，但那是调用顺序碰巧保证的，
   不是结构保证的。

**取舍**：`WorldPort.last_frame_sha` **保留**。动作空间的过期检查要它，那是工具层
内部的用途，和「交给 Harness 记账」是两件事。属性和返回值各管一头。

**顺带清掉 `write:harness:trace`**：两个角色里都有它，但全项目没有任何
`@require_permission("write:harness:trace")` —— 是个悬空的权限串。悬空的授权比缺失的
授权更坏：它让人以为 trace 写入被守着，实际上一行检查都没有。要给 trace 加守卫，
该是先加装饰器再加这条串。

**影响面**：`ToolPort` 少一个成员（契约变更，实现方要跟）；`PerceptionResult` 多一个
有默认值的字段（旧数据反序列化不受影响，`frame_sha` 为空串）；`read:game:last_frame_sha`
与 `write:harness:trace` 从权限清单消失。行为不变 —— OBSERVE 事件里那个 sha 的值和
从前一样，两条权限串本来也没有守着任何东西。

## 2026-08-25 —— docs/spec 全量同步：十份 SPEC 追上代码
**改了什么**：`docs/spec/` 下十份文档全部对着代码校了一遍，
+1036 / -552 行。今天所有变更的痕迹（动作链、一链一感知、`summary` → `status`、
`ToolResult.message` 删除、朝向读 RAM、细看整条删除、记忆一族改名、trace payload
变化、`--repeat`、观测台单例）都落进了对应的 SPEC；顺带修了**今天之前就已经漂了**
的一批：`MemoryToolPort` 整张签名表（`query_episodic`/`known_here`/`knowledge_base`/
`note_step`/`see_objects` 一个都不剩）、知识库从"全量拼接、每次读盘"改成混合检索 +
mtime 增量索引、`MockTrace` → `LocalTrace`、`memory/port.py` 这个不存在的路径、
`probe/run_episode.py` 已搬到 `pokemon_agent/experiment/`、`save_state` 从来没进过
签名表。
**为什么这么改**：文档漂了不会有任何症状——直到有人照着它改代码。这一轮里
`repeat_hint.md` 就是活的证据：它一个字没改，于是模型同时收到两套互相矛盾的说明。
SPEC 比 prompt 更隐蔽，因为它不进模型的上下文，只进人的上下文。
**取舍**：删掉的东西**不是抹掉，是改写成「这里曾经有一个 X …… 为什么删」**——
`inspect` 那条"细看和 observe 的区别不在再看一次、而在问的是不同的问题"、
`query_episodic` 那条"打分对着的必须和喂进 prompt 的是同一份文本"、
知识库那条"要能一边跑一边改 .md"，都是踩出来的判断，删了代码不等于删了理由。
`build/SPEC.md` 第 5 节描述的旧入口（`probe/run_episode.py`）没有逐节重写，
只在节首标明它已搬走、下面按旧文件读——那几节讲的 `_summary()` 统计逻辑仍有参考价值。
**怎么做的**：五份用 subagent 并行改（world/schemas/tools/interfaces/brain），
其余六份手工改。中途撞上会话额度上限，四个 agent 被腰斩，后半程改回手工。
**影响面**：只动文档，一行代码没碰；`pytest tests` 仍是 15 passed + 1 skipped。

## 2026-08-25 —— 同步 repeat hint 的方向键规则
**改了什么**：在 `repeat_hint.md` 中明确废弃旧的“多段链只能上下、right 必须换步”说明，改为允许四个方向键组成多段链。
**为什么这么改**：仅修改 `decide_action.md` 会让 `repeat_hint.md` 继续向模型提供相互矛盾的路径规划规则。
**取舍**：保留旧文字作为历史说明并追加覆盖规则，避免破坏 prompt 文件的既有结构。
**影响面**：统一 `repeat_hint.md` 与执行器对方向键链的约束。

## 2026-08-25 —— 允许四个方向键组成多段链
**改了什么**：将多段 `sequence` 的允许按键从 `up/down` 扩展为 `up/down/left/right`。
**为什么这么改**：多段按键链表达的是移动路径，四个方向键都属于移动指令，不能只限制上下移动。
**取舍**：`a` 等非方向键仍只能出现在长度为 1 的 sequence 中，避免把交互动作混入移动链。
**影响面**：同步更新决策解析、执行校验和 prompt 规则。

## 2026-08-25 —— 蒸馏 prompt 并入统一加载路径；NPC 说明去重；补上 `tests/test_prompts.py`
**改了什么**：
1. `episode_summary.md` 从 jinja2（`{{ }}`）改成 `$` 占位符，`EpisodeMemoryGenerator`
   不再自己 `jinja2.Template(open(...))`，改用 `prompts.load`；`success` 那个条件表达式
   挪进代码（传 `result="成功完成"/"未能完成"`）；`with_prompts` 里加上它。
   顺带把通篇的"情景记忆"改成"跨局摘要记忆"，并点明它和 `StepMemory` 不是一回事。
2. NPC 那段说明只留 `map_hint.md` 一份，`decide_action.md` 里删掉，
   `decide_action` 独有的那句"只是重复固定台词就换一个"并进 map_hint。
3. 新增 `tests/test_prompts.py`（原来是个 0 字节的空文件）。
**为什么这么改**：
自己读文件的代价不是多几行代码，是这份 prompt **没有 sha、进不了 manifest**——
那一局的蒸馏用的是哪一版说明，事后查不出来，而 manifest 存在的全部意义就是回答这个。
两套模板引擎并存还意味着 `$` 和 `{{ }}` 两种语法在同一个目录里，改错一个不会报错。
NPC 说明重复两份、两份都每步进 prompt，改一处漏一处是迟早的事。
**最要紧的是第 3 条**：`schemas/observation.py` 里 `describe_scene_fields()` /
`json_output_examples()` 的注释一直写着"漂移由 `test_prompts.py` 挡"，
而那个文件是**空的**——**声称存在的锁不存在，比没有锁更糟**：那两个函数因此
零调用方（看起来像死代码），而 prompt 和 `SCENE_FIELDS` 真漂了也没人知道。
现在它测三件事：每份 prompt 的 `$占位符` 和调用方实参双向吻合（漏传当场 KeyError、
多传静默丢内容）、字段清单逐字一致、六个 JSON 样例按解析后的 dict 一致。
实测当前全部吻合，没有存量漂移。
**取舍**：`CALLERS` 那张表是**手写**的，就是"调用方的契约"。从代码里自动扒
`render(...)` 的实参等于两边同源，那就什么都测不出来了。
**影响面**：新 run 的 manifest 会多一份 `episode_summary` 原文；测试从 1 个涨到 12 个。

## 2026-08-25 —— 全部 prompt 过了一遍，清掉两条已经不成立的说法
**改了什么**：`repeat_hint.md` 里的 `?` 地形符改掉——`TERRAIN_MEANING` 只有
`. G D S N # @` 七个字符，**没有 `?`**，那是上一版地图的遗留；改成按真实图例说
"数到 `#`、`D`、`S`、`N` 或转弯处为止"，"什么时候别拉长链"也从"目标格是 `?`"
改成"路上要穿过 `G`"（会遇野生宝可梦，这才是真会中途出事的那种格子）。
`map_hint.md` 末尾"本例中 `x=1,y=5` 的 `N` 就属于这种情况"删掉——**prompt 里
没有这个例子**，那句话指向空气。
**为什么这么改**：prompt 里指向不存在的符号和不存在的例子，模型只能自己编一个
去匹配，而编出来的东西读日志的人分辨不出是它读错了还是我们说错了。
**顺带加的检查**：写了个小脚本把每个模板里的 `$占位符` 和调用方实际传的参数对了一遍
（`Template.substitute` 漏传会当场抛 KeyError，而 prompt 是最常改的文件）——
七个模板全部吻合，没有多也没有少。
**没改但要记一笔**：
1. `episode_summary.md` 走的是**另一套模板引擎**（`episode_summarizer` 自己
   `jinja2.Template`，`{{ }}` 语法），不经过 `prompts.load`，因此**没有 sha、
   也不进 manifest**——这一局用的是哪一版蒸馏 prompt，事后查不出来。
2. NPC 那段说明在 `decide_action.md` 和 `map_hint.md` 里各写了一遍，内容重复；
   两份都在每步的 prompt 里，改一处漏一处是迟早的事。
3. `episode_summary.md` 通篇管跨局摘要叫"情景记忆"，和刚定下的
   step_memory / episode_memory 词汇对不上。

## 2026-08-25 —— prompt 跟上动作链：`repeat_hint` 还在教已经废掉的 `args.times`
**改了什么**：`repeat_hint.md` 整篇重写（它每步都进决策 prompt，挂在动作空间的 note 上）；
`decide_action.md` 开头从"选出下一个动作"改成"选出这一步要按的按键链"，
`sequence` 那条说明拆成三条规则并写清楚拐弯怎么办。
**为什么这么改**：`repeat_hint.md` 一个字都没改过，还在教
`用 "args": {"times": "N"} 连按同一个键`——**那个格式现在直接 ParseFailure**。
它还在教"把开头那段同方向的一次走完，下一步再转弯"，那是一步一个键时代的战术。
两份说明打架的结果在 trace 里看得很清楚：模型规划出 `down×2 → right×3 → up`，
然后卡在"sequence 长度>1 只能 up/down"上，自我说服成"当前只需输出下一步"。
**它不是不会用链，是我们同时给了它两套互相矛盾的说明。**
**取舍**：把"`right×3` 自己单独成一步完全合法"写成显式的一条——多段链只能 up/down
这条规则本身容易被读成"拐弯的方向不能连按"，而那是错的。
`a` 的措辞从"会被夹成 1"改成"会被改成 1"，因为夹的位置已经从执行层挪到了解析期。
**影响面**：只动 prompt。`manifest` 存的是 `decide_action` / `judge_success` 的原文，
这次改动会体现在新的 run 里。
**没做**：多段链只能 up/down 这条规则本身没动——那是你定的边界，我只是把它说清楚。

## 2026-08-25 —— 修：`--repeat` 第二局起观测台不再更新（每局都新起一台服务抢同一个端口）
**改了什么**：`trace/browser.py` 加进程级单例 `shared_server()`，`build_session()`
改成用它，不再每次建会话都 `BrowserTraceServer()`。页面在 `run_id` 变化时打一条
`===== RUN <id> =====` 分隔线。
**为什么这么改**：`BrowserTraceServer.__init__` 就地 bind 固定端口 8765。一个进程里
跑第二局时再 new 一台，Linux 上直接 `EADDRINUSE`，而 **Windows 上更坏**：
`allow_reuse_address` 让第二次 bind 也成功，同一端口上于是有两台服务，
而浏览器那个标签页还挂在**第一台**的 SSE 连接上——第二局的事件全推给了第二台，
页面从此一个字都不再更新。日志和落盘全都正常，所以从终端完全看不出来。
**取舍**：进程级单例（模块级可变状态）。端口本来就是进程级资源，谁先拿到谁就是它；
把服务做成每会话一个，等于假装这个资源可以有多份。多局共用一条 SSE，
靠 RUN 分隔线区分，标签页不用重开。
**影响面**：`--repeat N` 现在整轮都能在同一个页面上看完。
**怎么验的**：起一条真的 SSE 连接，同一进程里连着建两个 `LocalTrace`（run-A / run-B）
各推两条事件，四条**都到了同一条连接**上。

## 2026-08-25 —— 修：观测台整页空白（JS 字符串被 Python 转义打断）
**改了什么**：`browser.py` 里 `facts.walk_map.split('\\n')` 的换行符改成写两个反斜杠。
**为什么这么改**：那段 JS 住在 Python 的三引号字符串里。写 `\n` 的话 **Python**
先把它变成一个真换行，送到浏览器的就是断成两行的字符串字面量，`script` 整段
语法错误——症状不是"walk_map 那一块不对"，而是**观测台一个字都不显示**。
上一条改动就是这么把整页打没的。
**取舍**：这类"字符串里的字符串"没有类型系统看着，只能靠一条规则记住：
`browser.py` 的 HTML 块里，任何要交给 JS 的反斜杠都得写两遍。注释就写在那一行上面。
**怎么防**：现在可以用 `node --check` 验——把那段 HTML 里的 `<script>` 抠出来
喂给它，语法错误当场就报。这次改完验过了，另外拿一条真的 observe 事件跑了一遍
渲染函数，九行 walk_map 逐行输出正常。

## 2026-08-25 —— 观测台的 observe 块补齐：朝向、四邻、地标各占一行，walk_map 逐行打
**改了什么**：`browser.py` 的 observe 块加 `facing`（并进 where 那行，读不到时显示
`朝向 ?`）、`neighbors` 和 `landmarks` 各自成行；`walk_map` 按 `\n` 拆开逐行输出。
**为什么这么改**：`walk_map` 原来整段丢给一个 `line()`，虽然 CSS 是 `pre-wrap`，
但实际读起来仍是一坨——**这张图的全部用处就是看形状**（往那边走得通吗、哪边是死路），
挤成一段就什么都看不出来。`facing` 是新读出来的字段（精灵表 +9），
而它决定 `a` 作用在哪一格，观测台上看不到就没法判断"它为什么对着空气按 a"。
`朝向 ?` 而不是省略：读不出来是要查的事，静默省略会让人以为这一帧没有朝向概念。
**取舍**：observe 块从 5 行涨到十几行。可接受——这本来就是"它当时看到了什么"
唯一的展示位，而终端那边已经完全不打这类事件了。
**影响面**：只动观测台的渲染，事件和 payload 不变。

## 2026-08-25 —— 朝向改为读内存；细看（inspect）整条链路删除
**改了什么**：
新增 `ram.read_facing()`（精灵表 `+9`，`0/4/8/12` → south/north/west/east），
`TerrainMap` 加 `facing` 字段，`facts["facing"]` 从它来。`PyBoyWorld._facing`
连同 `step()` 里的更新一起删除。
细看整条链路删除：`PyBoyWorld.inspect()` / `_note()` / `_notes` / `MAX_NOTES` /
`facts["inspected"]`、`WorldPort.inspect`、`trace.inspect()`、`JUDGE_BLIND` 里的
`inspected`、`prompts/inspect_focus.md`（移到 `_to_delete/`，这台机器上删不掉文件）。
**为什么这么改**：
朝向——`+9` 那个字节的含义**这个文件自己的注释里早就写着**（`ram.py` 的精灵表说明），
只是从来没读。推的那一版有两个洞：开局和过场之后朝向未知（没按过键），
而且它不进存档，checkpoint 恢复不回来（`docs/spec/harness/SPEC.md` 1.4 记的就是它）。
读内存两个洞一起消失。
细看——**没有任何调用方**。`brain` 和 `harness` 里一处都没有，最近几局 trace 里
一条 INSPECT 事件都没有。它带着一份 prompt、一个 4 条上限的缓存、一条 `facts` 键、
一条判定器黑名单，全是维护成本却没有执行路径。
**取舍**：`EventType.INSPECT` 保留——旧 trace 文件里有这类事件，删掉枚举成员
replay 会在校验那一步炸；观测台的 inspect 分支同理保留。两处都标了"没有生产者了"。
`BUTTON_FACING` 保留但改了说明：它现在只回答"这一步往哪按"（工具层算 attempts 键要用），
不再是"现在面朝哪"的来源。
**影响面**：`facts["facing"]` 从此开局就有值（以前要按过一次方向键才出现）；
`Observation.facts` 少了 `inspected` 键；`WorldPort` 少一个方法。
**要验证**：`+9` 的地址和取值靠的是文件里的既有注释，我没有 ROM 可跑。
实跑第一局时看一眼 `facts["facing"]` 和画面里主角朝向对不对得上。

## 2026-08-25 —— `Observation.summary` 改名 `status`；`ToolResult.message` 删除
**改了什么**：`Observation.summary` → `Observation.status`（`_summarize()` →
`_status_line()`，OBSERVE 事件的 payload 键、`decide_action.md` 的 `$summary`
占位符一起改）。`ToolResult.message` 字段删除，`trace.act()` 不再收 message 参数，
ACT 事件只剩动作链。
**为什么这么改**：那个字段不是摘要。它是 `scene` + `overlay` 机械拼出来的一行
（`你在野外。对话框：「…」`），prompt 里对应的小标题正是「当前状态」；而这一帧
真正被看到的东西是视觉模型写的 `facts["overview"]`。叫 summary 会让人以为
"这一帧的信息都在这句里了"，于是观测台只印它、ACT 又复读一遍它——**信息看起来
到齐了，其实一直藏着**。
`message` 更直接：它的字段描述写着"给 LLM 读的结果描述"，而没有任何一条路径把它
交给 LLM，全仓库唯一的消费方是 ACT 事件，内容就是 `status` 本身。动作之后世界
变成什么样，答案是**下一条完整的 OBSERVE**，不是一句转述。
**取舍**：`status` 这个名字对应 prompt 里的小标题，不再暗示它是全部信息。
ACT 事件从此只回答"按了什么"，OBSERVE 回答"变成了什么样"，两件事不再混在一条里。
**影响面**：`Observation` 是跨层 schema，改名波及 brain / world / trace / prompt；
旧 JSONL 里的 `summary` 键不迁移，观测台读 `p.status||p.summary` 兼容旧数据。
`WorldPort.step` 的返回值少一个字段。

## 2026-08-25 —— 「a 只按一次」挪到解析期；world 收到什么按什么
**改了什么**：`Brain._parse` 里遇到 `a` 直接把 `times` 定死为 1。
`PyBoyWorld` 的 `_clamped()` / `_dialog_is_open()` 整段删除，`step()` 现在
逐段按 `segment.times` 执行、不改写任何东西，`message` 也不再拼"被夹成 N 次"的说明。
`MAX_TIMES` 从 `world` 搬到 `schemas/action.py`，成为 `ActionSegment.times` 和
`Brain._parse_times` 的**同一个来源**（原来三处各写一个 8，且 world 那个已无人使用）。
观测台的 observe 块补上 `overview` / `dialog_text` / `where+neighbors`。
**为什么这么改**：动作合法性是解析期的事。执行层再悄悄夹一次，**大脑交出去的链
和真正发生的链就对不上**——它以为自己按了三次 `a`，实际只按了一次，下一步的推理
建立在错的前提上。原来的补救是把"被夹了"写进 `message`，而 `message` 只进 trace，
大脑根本看不见。现在解析期定死，交给 world 的链就是真正会发生的那条链。
另一条「对话框开着时方向键连按夹到 1」直接没了也不亏：`OVERLAY_ACTIONS[DIALOG]`
本来就只有 `a`，对话框开着时方向键连动作空间都进不去。
**取舍**：`a×5` 被静默改成 `a×1`，不重试——动作名是对的，只是次数不合规范，
为它跑一轮重试不划算（判据同 ```json 包裹）。观测台从此能看到 `overview` 那一整段，
代价是每步多几行；`summary` 那句缩写留着，它是 prompt 的上下文开头。
**影响面**：`world.step()` 不再有任何改写行为，`WorldPort` 的契约随之变干净。

## 2026-08-25 —— 一次决策 = 一次感知：整条动作链交给 world 执行，结尾只感知一次
**改了什么**：`GameTools.execute()` 不再拆链，直接 `world.step(action)` 一次。
`PyBoyWorld.step()` 改成遍历 `action.segments()`，段与段之间不感知，跑完整条链
才 `observe()` 一次；夹连按的逻辑抽成 `_clamped(segment)`，按段判。
`WorldPort.step` 的契约文档同步成"执行整条链、结尾感知一次"。
删掉 `_times()`（从 `args["times"]` 抠字符串的那条通道，已无调用方——次数现在
由 `ActionSegment.times` 在解析期校验）。观测台的行动行不再复读 message。
**为什么这么改**：感知是每步花钱的那一项。展开成一次一按时 `up×4` 是**四次视觉调用**
（实测 17k input token、6.6 秒）；改成一段一次仍然是两次。而多段链按规则只能是
移动键，中间那几帧没有任何会被用到的信息。`up×4 -> down×2` 现在是 1 次感知。
message 那行「你在野外。你在野外。你在野外。你在野外。」也随之消失——它本来就是
四段拼的，而且和紧随其后的 OBSERVE summary 是同一句话，观测台上纯属复读。
**取舍**：链中途的画面彻底看不到，所以链**不能**包含会产出证据的按键——这正是
「多段链只能是 up/down」那条规则的理由，现在它从"约定"变成了"不这样就会丢证据"。
`a` 仍由 world 夹回一次一按：它的收益全在中间帧上。
**影响面**：`execute()` 从 20 行变成 1 行调用；trace 里一步的 perception 事件数
从 `press_count` 降到 1。`WorldPort` 的实现方（目前只有 `PyBoyWorld`）要按新契约走。
**没做**：链的中途中止（野生宝可梦在第二按跳出来，剩下两按仍会打进去）——
本轮明确不做，动作合法性由解析期保证就够了。

## 2026-08-25 —— 动作链每段只感知一次（原来一段 N 次按键 = N 次视觉调用）
**改了什么**：`GameTools.execute()` 不再把 `up×4` 展开成 4 次 `step(times=1)`，
改成一段一次 `step(times=4)`，连按次数交回给 `world`。
**为什么这么改**：`world.step()` 每次结尾必定感知一次。展开之后 `right×4` 在真实
trace 里产生了**四条 perception 事件**（4×~4300 input token、6.6 秒），而那四帧里
有用的只有最后一帧。返回的 message 也是四段拼起来的，控制台上就是
「你在野外。 你在野外。 你在野外。 你在野外。」。更隐蔽的是：`world.step()` 里
连按 N 次再感知一次的那段逻辑（`WITHIN_ACTION_FRAMES`）被架空成了死代码，
连带「`a` 连按夹到 1」「对话框开着时夹到 1」两条保护一起失效——它们判的是
`times > 1`，而展开之后永远是 1。
**取舍**：中间帧看不到了，这正是 world 里那两条夹逻辑存在的理由——方向键的中间帧
没有证据，`a` 的中间帧全是证据，所以 `a` 由 world 夹回一次一按。
`up×4 -> down×2` 现在是 2 次感知，不是 6 次。
**影响面**：只动 `execute()` 的循环；trace 里一步的 perception 事件数会从
`press_count` 降到 `segment_count`。
**还没解决**：**动作链没有中途中止条件**。`execute()` 只在链的开头校验一次
frame sha 和 action space，之后整条链跑完。实测有一局野生宝可梦在 `right×4` 的
最后一按才跳出来——要是它在第二按跳出来，剩下两下会打进一个按"野外"算出来的
动作空间里。廉价的做法是每按一次从 RAM 读 map_id/坐标（不调视觉模型），
变了就丢掉剩余按键；需要给 `ram.py` 加一个战斗标志地址。

## 2026-08-25 —— schemas 里的记忆一族按检索单元重命名
**改了什么**：
`memory_episodic.py` → `step_memory.py`（`MemoryEntry` → `StepMemory`，`Snapshot` 不动）、
`memory_episode.py` → `episode_memory.py`、
`memory_episode_summary.py` → `episode_summary_io.py`、
`memory_semantic.py` → `object_fact.py`。26 个文件里的 import、docstring、
docs/spec 与 CLAUDE.md 的目录说明一起改。**只改名字，一行行为都没动。**
**为什么这么改**：`episodic` 和 `episode` 靠一个词尾区分"一条=一步"和"一条=一整局"——
那是英语的语法差别，不是概念差别，读的人没有任何线索去猜哪个是哪个（这三个文件的
检索单元完全不同，选错就是把一整局的经验当成一步喂进去）。`MemoryEntry` 的
「Entry」等于什么都没说，而这个类的全部要点恰恰是"一条 = 一步"。
`memory_episode_summary.py` 里**根本没有记忆**，全是蒸馏那次 LLM 调用的请求/响应契约，
挂着 `memory_` 前缀会被当成第三种记忆。
**取舍**：`Snapshot` 留着不改——它在 `StepMemory` 的上下文里意思很清楚，
换成 `ObservationDigest` 只是更长。`episode_summary_io` 的 `_io` 是必要的：文件里
`EpisodeSummaryRequest` 和 `EpisodeSummaryResponse` 各占一半，只叫 `..._request`
会和住在同一个文件里的 response 直接打架；"summary" 保留是因为它已经是这条链路上
大家在用的词，换成 `distill_*` 的收益不抵重新建立词汇的成本。
一个文件一个主类的对应关系现在是硬的：读 `schemas/` 的目录就知道有几种记忆。
**影响面**：纯重命名，无行为变更；旧的落盘数据不受影响（存的是字段，不是类名）。
外部若有脚本 `from pokemon_agent.schemas.memory_episodic import MemoryEntry` 要跟着改。

## 2026-08-25 —— 删掉测试里那个接管审批的 fixture
**改了什么**：`tests/test_run_experiment.py` 的 `approved` fixture 及其 `sys.stdin` 接管删除，
文件头的说明改成现状。
**为什么这么改**：`execute:game:save_state` 在 `config/permissions.json` 里已经是
`approval_required: false`，`pokemon_agent/` 里也不再有任何审批调用点——那个 fixture
在替一条不会触发的链路做准备，而它的 docstring 还在断言"挂着 approval_required"，
读的人会照着这句去理解批量跑实验的约束。**过时的注释比没有注释更贵。**
**取舍**：真要把审批打开时得连它一起想清楚（每局开局都存一次档，批量跑就是每局按一次），
所以这句话留在文件头，只是从"现在如此"改成了"哪天打开要注意"。
**影响面**：只动测试，`--repeat` 现在可以无人值守跑。

## 2026-08-25 —— run_experiment 支持 `--repeat`：同一个任务连跑 N 遍
**改了什么**：`--repeat N`（默认 1）。跑一条链的那段从 `main()` 里抽成
`run_chain(chain, run_id, state, watch)`，`main()` 只负责解析参数、编 run_id、循环、
最后报一行「跑了 N 遍，成功 M 遍（X%）」。
**为什么这么改**：成功率是这个项目要产出的数字，而单跑一遍出来的成功率是 0 或 1，
不是成功率。以前想跑 10 遍只能在 shell 里手写循环，每遍的 run_id 还得自己编。
**取舍**：每一遍都**新建又关掉一整套 world/harness**，不复用——复用的话第 2 遍会从
第 1 遍结束的画面开始，测的就不是同一件事了；代价是每遍多一次模拟器启动。
`--repeat 1` 时 run_id 保持原样不加后缀（`--run-id` 是拿来指名道姓找这一跑数据的，
测试就这么用），大于 1 时才加 `-r1`/`-r2`。异常不吞：环境崩了就整轮终止，
不带着坏环境把剩下的跑成假数据——已跑完那几遍的统计每局都落过盘，不会白跑。
`--repeat` 的合法性走 `parser.error` 而不是 assert：命令行是外部输入，
而 assert 在 `python -O` 下会被删掉。
**影响面**：新增参数，默认行为与之前完全一致；`tests/test_run_experiment.py` 不受影响。
**没做**：多遍之间没有并行，也没有"失败自动重试"——前者要先解决模拟器实例互相抢
存档路径的问题，后者会污染成功率。

## 2026-08-25 —— 删掉 `sse()` 里那七类事件的死打印分支
**改了什么**：`store.py` 里 OBSERVE / MEMORY_READ / THINK / ACT / INSPECT /
MEMORY_WRITE / OBJECT_NOTE 七个打印分支整段删除，连同只被它们用到的 `_facts()`
和 `_chain()`；那句裸的提前 `return` 换成模块级的 `BROWSER_ONLY` 集合，带上
"终端看什么、观测台看什么"的分工说明。
**为什么这么改**：`sse()` 一进来就对这七类 `return`，下面却留着它们的完整打印代码——
**永远执行不到**。这种死代码的代价不是几十行，是读的人对整个文件的信任：改了它们、
跑一遍、终端毫无变化，只能怀疑是自己改错了（这一轮就真的在这上面绕了一圈）。
**取舍**：分工本身不动——终端留给"跑得对不对"（账单、错误、目标出栈、episode 起止），
观测台留给"它当时看到了什么"。想让某一类回终端，从 `BROWSER_ONLY` 里删掉它再写分支，
名单是唯一的事实来源。提前 return 仍放在表头之前：只有观测台事件的那一步，
终端不该冒出一个空的 STEP 表头。
**影响面**：只删控制台输出，`append()` 的落盘与推流是同一条事件，payload 一个字段没少——
replay、观测台、成本统计都不受影响。上一条日志里"发现但没改"的那项就是这个。

## 2026-08-25 —— known_objects 改成多行档案，日志不再只存 80 字符的半截标签
**改了什么**：`ObjectFact.render()` 从"一行三种 `→`"改成「抬头 + 缩进明细」的多行形状，
尝试记录渲染成「站在 x=3 y=4 按 a → 无效果」；`query_objects` 改用空行分隔条目；
`memory_read` 事件改存全文 `known_objects_text` + `known_object_count`（删掉
`known_object_names` 和那个 80 字符截断）；控制台与观测台跟着改成整段打印。
`walk_map` 的表头从「x 从 2 到 11，y 从 1 到 9」改成「10 列 × 9 行：最左一列 x=2…」。
`prompts/map_hint.md` / `inspect_focus.md` 的示例同步。新增 `tests/test_trace.py`。
**为什么这么改**：老那一行里 `→` 出现三次、三次意思都不同，而 `x=3 y=4`（角色按键时
站的格）紧挨着对象自己的 `x=3 y=3`，读起来像同一个东西的两个坐标——**这是会让模型
误判"这条尝试是在哪按的"的歧义**，不只是难看。日志那边更直接：只存首行截 80 字符，
而 `query_objects` 当时用单换行拼接，于是整段被当成一条，观测台上实际只显示了
第一条档案的前 80 个字符（`…x=3 y=4→dow`）。决策模型读到的原文没进日志，
replay 就回答不了"它当时看到了什么"。
**取舍**：档案变长（每条 2-5 行），每帧都要进 prompt，token 成本上升——换的是
坐标不再有歧义。走通的门只留成功那一条碰法，失败的不再列：门开过之后待办清单就没用了。
attempts 的存储键仍是 `x=3 y=4→a`，只在渲染层翻译，**不动落盘格式**，否则已有存档全部失配。
**影响面**：`known_objects` 的文本形状变了（prompt 和日志同时变）；下游若按
`known_object_names` 读观测台字段要改读 `known_objects_text`。旧 JSONL 不迁移。
**顺带修的**：`store_objects_interactions` 遇到多段动作链直接不记——链的 `before`/`after`
是整条链的两头，把它记成"在起点按了一次 up"会往档案里写一条**假的尝试**。
**发现但没改**：`LocalTrace.sse()` 开头对 OBSERVE / MEMORY_READ / THINK / ACT /
INSPECT / MEMORY_WRITE 直接 `return`，下面那些分支在控制台上**全是死代码**——
这几类现在只有浏览器观测台看得到。要么删，要么把 return 去掉，需要先定一下控制台该看什么。

## 2026-08-25 —— trace 跟上动作链：payload 记结构化 sequence，控制台不再恒印 `[无 times]`
**改了什么**：`trace/utils.py` 新增 `action_chain()`，`think`/`act` 共用它，payload 里
记 `action`（`up×4 -> down×2` 渲染文本）+ `sequence`（结构化 JSON）+ `segment_count` +
`press_count`，删掉顶层 `args`。`store.py` 的 `_times()` 换成 `_chain()`，只在多段链时
补一段「N 段 / M 次按键」；观测台 `browser.py` 的行动行同步。
**为什么这么改**：`act` 的 `args` 已经从 `{"times": n}` 变成段数组，而 `_times()` 还在
判 `"times" not in args`——这个判断对 list 恒成立，于是控制台**每一行**都印 ` [无 times]`，
一个恒真的提示比没有更糟。同时聚合需要的是结构化的链，靠反解析 `describe()` 的措辞
早晚会静默算错。
**取舍**：payload 里渲染文本和结构化字段各存一份，略有冗余——但一份给人读、一份给
统计读，合成一份就要有人去解析另一份。`args` 直接删而不是留空：留一个恒为空的字段
会让读日志的人以为"模型没给参数"。旧 JSONL 里的 `args` 不迁移，读取端全是 `.get()`。
**影响面**：只动 trace 三个文件，事件类型与 `event_id` 语义不变；下游若有按 `args`
统计连按次数的脚本要改读 `press_count`。
**仍未跟上（未改）**：`tools/memory_tool.py` 的语义记忆仍按 `action.name` / `action.args["times"]`
记 attempts——链的情况下 `name` 只是第一段，会把 `up×4 -> down×2` 记成一次 `up`。

## 2026-08-25 —— 统一所有动作使用 sequence
**改了什么**：取消顶层 `action`/`args` 格式，所有动作统一使用 `sequence`；单元素 sequence 可包含任意按键，多元素 sequence 只能包含 `up/down`。
**为什么这么改**：让单次互动与连续移动共享同一个结构，同时保留“动作链只能是移动”的边界。
**取舍**：单次 `a` 也需要写成一个 sequence 元素，但动作 schema 更统一，解析分支更少。
**影响面**：更新决策解析、执行校验和 prompt；旧的顶层 action 格式不再接受。

## 2026-08-25 —— 移除旧单动作参数兼容
**改了什么**：取消 `action + args.times` 的旧格式兼容；移动使用 `sequence`，非移动单次动作只使用 `action`。
**为什么这么改**：两种动作形态的边界需要明确，避免模型继续生成旧的 `args.times`，并确保按键链永远只表达上下移动。
**取舍**：旧 JSON 输出会被解析失败并触发重试；单次 `a` 等动作的格式变为更短的 `{"action": "a"}`。
**影响面**：更新决策解析和 prompt；`Action` 内部保留 `args` 字段以避免影响 trace/schema 的其他调用方，但入口不再接受旧参数。

## 2026-08-25 —— 限定按键链只包含上下移动
**改了什么**：将 `sequence` 限定为只允许 `up` 和 `down`；互动和其他方向键继续使用单动作格式。
**为什么这么改**：按键链用于表达连续移动路径，不应把 `a` 等会改变交互状态的按键混入连续执行序列。
**取舍**：无法用一条 sequence 表达“移动→互动→移动”，互动必须结束一次移动链后由下一轮决策单独发出。
**影响面**：收紧决策解析、工具执行校验和 prompt 示例，避免模型生成非法混合按键链。

## 2026-08-25 —— 支持受限按键链
**改了什么**：动作现在支持 `sequence` 按键链；只有 `up`/`down` 可以重复，`a`、`left`、`right` 等按键只能单次出现。执行器按链顺序逐段推进世界。
**为什么这么改**：移动路径需要表达“上移若干格、互动一次、再下移若干格”，单一 `action + times` 无法表达这种组合。
**取舍**：动作链中途仍不重新请求 LLM；每个段落实际逐次调用 world，返回最后一帧，避免把交互键误连按。
**影响面**：更新动作 schema、决策 prompt、world 执行、trace 和情景记忆的动作表示；旧格式仍可解析。

## 2026-08-25 —— 移除 trace 控制台 debug 开关
**改了什么**：移除 `LocalTrace` 的 debug 参数和 `POKEMON_AGENT_TRACE_DEBUG` 环境变量；`object_note` 永久不在控制台打印，但继续写入 trace 和推流。
**为什么这么改**：对象记忆明细属于离线调试数据，不应成为普通运行日志的一部分，也不需要额外运行模式切换。
**取舍**：需要查看对象记忆时直接读取 JSONL/SSE 数据，不再通过控制台开关查看。
**影响面**：所有运行模式的控制台输出统一，`LocalTrace` 构造接口更简单。

## 2026-08-25 —— 默认隐藏调试型 object note 日志
**改了什么**：`LocalTrace` 默认不在控制台打印 `object_note`，但仍完整写入内存、JSONL 和 SSE；设置 `POKEMON_AGENT_TRACE_DEBUG=1` 后恢复打印。
**为什么这么改**：普通运行主要需要观察成本、动作和 episode 结果，逐条对象记忆会淹没决策过程。
**取舍**：调试信息没有删除，只把默认展示关闭，因此 replay 和离线分析不受影响。
**影响面**：减少默认 trace 控制台噪声；需要排查对象记忆时显式打开 debug 环境变量。

## 2026-08-25 —— 修正隔障碍物 NPC 交互规则
**改了什么**：修正 NPC prompt：`#` 只限制移动，不再被当作 NPC 交互的阻断条件；补充柜台式隔障碍物交互示例。
**为什么这么改**：实际地图中 `x=1,y=5` 的店员与主角之间有 `#`，但仍可面朝按 `a` 对话，之前的“四邻格可通行”规则过于严格。
**取舍**：改为先按 `a` 验证交互，再根据无反应结果调整路径或目标，可能多消耗一次动作，但避免漏掉真实可交互 NPC。
**影响面**：更新 `map_hint.md` 与 `decide_action.md`，改善商店柜台、货架等障碍物场景的 NPC 选择。

## 2026-08-25 —— 明确障碍物不阻止 NPC 相邻互动
**改了什么**：更新 `map_hint.md` 和 `decide_action.md`，要求 agent 将 NPC 本身的不可通行格与 NPC 的可对话性分开判断，并优先寻找四个相邻可通行格绕行互动。
**为什么这么改**：实际观测中 agent 已识别出店员，却因柜台等障碍物无法直线接近而错误判定为不可对话。
**取舍**：增加“连续重复固定回应后检查其他 NPC”的启发，避免对同一个缺货店员无限重复按 `a`，但不在 prompt 中硬编码某个地图的坐标。
**影响面**：改善商店和其他有障碍物场景下的 NPC 路径规划与交互选择，不改变工具接口。

## 2026-08-25 —— 增加 env 全权限免审批角色
**改了什么**：在权限配置中新增拥有当前全部声明权限的 `env` role，将运行时 context 切换到该角色，并关闭 `execute:game:save_state` 的审批要求。
**为什么这么改**：当前实验阶段需要无人值守地连续执行任务链，保存游戏状态不应在每个 episode 开始时阻塞等待人工确认。
**取舍**：`env` 是开发实验专用的全权限角色，不适用于生产或不受控环境。
**影响面**：实验运行不再因保存 state 请求审批而暂停；原有 `trusted-agent` 角色仍保留。

## 2026-08-25 —— 使用 manifest 允许的任务链实验类型
**改了什么**：将任务链的 `experiment_kind` 从自定义的 `task_chain` 改为 manifest 已支持的 `sequential_episodes`。
**为什么这么改**：`RunManifest.validate_design()` 对实验类型有明确白名单，任务链本质上就是多个连续 episode。
**取舍**：不扩展 manifest 协议，避免让已有结果读取逻辑认识新的类型名称。
**影响面**：修复任务链启动阶段的 `AssertionError`，manifest 结构保持兼容。

## 2026-08-25 —— 统一 knowledge 任务链接口
**改了什么**：将 `knowledge_recall_task_chains()` 合并进 `knowledge_recall_tasks()`，该函数现在只返回 `TaskChain`，原有单任务作为单节点链返回。
**为什么这么改**：实验入口不需要区分短任务和任务链，统一的数据形态能让后续增加链式任务时不再扩展编排分支。
**取舍**：改变了 `knowledge_recall_tasks()` 的返回类型；调用方必须通过 `chain.tasks` 访问子任务。
**影响面**：更新 `run_experiment.py` 的任务发现逻辑，不影响任务内容和已有 CLI 的单任务 ID。

## 2026-08-25 —— 实验入口支持任务链
**改了什么**：新增 `TaskChain` 和 knowledge 任务链定义；`run_experiment.py` 现在会在同一个游戏 session 中按顺序执行链内任务，并分别记录子任务与整条链的统计。
**为什么这么改**：长程实验需要让前一个任务留下的游戏状态和记忆成为后一个任务的输入，单次只运行一个短任务无法验证这种跨任务复用。
**取舍**：任务链仍以每个子任务为一个 episode，失败后停止后续任务；这样保留现有 trace 和成功率语义，也避免把多个目标混成一个不可解释的结果。
**影响面**：新增实验编排能力，现有单任务 CLI 用法继续可用。

> 最新在最上。每条固定四段：改了什么 / 为什么这么改 / 取舍 / 影响面。
> 这是给人读的决策记录，不是 git log 的复制品。

## 2026-08-25 —— trace 落盘只留下最后一条事件（真 bug），测试收敛成一个端到端

**改了什么**：

- **修 `LocalTrace._save_event`**：改成直接追加，不再"写临时文件再原子重命名"。
- 删掉全部旧测试，新增 `tests/test_run_experiment.py` ——从 `run_experiment.main()`
  在**真实环境**里跑一整局：真 DashScope、真 fastembed、真 PyBoy、真权限配置、
  真落盘，一个替身都没有。没有 `DASHSCOPE_API_KEY` 时 skip。
- 顺带修 `agent_permission` 的 `AuditService`：写 `log/audit.jsonl` 前先建目录。

**为什么这么改**：那个 bug 是写测试时撞出来的，**而且它已经静默毁掉了全部历史数据**。

`_save_event` 往 `<ep>.jsonl.tmp` 追加一行，然后 `os.replace(temp, path)`。
"原子重命名"这个模式只对**整份文件重写**成立：把完整内容写进 temp、再一次性换过去。
这里是追加——每次都用"只含这一条事件的临时文件"把已有的整份覆盖掉，
所以**磁盘上永远只剩最后一条**。内存里的 `self._events` 是全的，控制台打印也正常，
所以它完全无声。实测：`trace_data/` 下每一个 episode 的 `.jsonl` 都只有 1 行，
剩的那条还都是 `EPISODE_END`。

replay、checkpoint、离线成功率统计、失败模式分布——四件事共同的底座，
一直是空的。这也解释了为什么"trace 是唯一的事实来源"这条主张从来没被真正验证过：
没人读过落盘的那份。

测试收敛成一个，是因为**旧的七个里有九个用例已经红了**（`MemoryTool` 的签名早就变了，
而 `tests/` 在 `.gitignore` 里，没有任何东西会告诉你）。与其修一批各自只覆盖
一小块的单元测试，不如留一个真正走完整条链路的：命令行入口 → manifest → 权限 →
装配 → LangGraph 循环 → 四类记忆 → trace 落盘 → 统计文件。
**这条路上没有替身**，除了会花钱的那几个。

**取舍**：**一个替身都不留，跑真的。** 先写过一版把四个模型换成脚本化假实现的，
理由是"确定、免费、不联网"；但那样每换掉一个真实现，就放弃了一条集成路径上的覆盖，
而这个测试的全部价值恰恰在于**它是唯一一条端到端走完的路径**。
代价接受下来：跑一次花钱、要网、非确定。

非确定带来的约束是**断言什么**：一个字都不断言模型说了什么，只断言
"不管模型怎么答都必须成立"的结构性不变量。把模型答得对不对写进断言，
这个测试就会因为换型号、调温度而变红——那时红的是测试，不是代码。
**成功率是拿实验数据报的，不是拿测试断言报的。**

同理，真模型连着几次吐不出合法动作（`MaxRetriesExceeded`）时测试**不红**，
只要求它别失败得无声无息：有 ERROR 说明白为什么、有 END 说明这一局收了尾。
写成硬断言就是在赌模型今天的手感。

唯一自动化掉的是**控制台审批**（测试替那个"真人"答 approve）。它走的仍是真实
审批流程，只是没法让 CI 等一个人。这里顺带暴露一件事：
`execute:game:save_state` 挂着 `approval_required`，而每局开局都存档——
**批量跑实验时每一局开头都要一个真人按一下**。要无人值守跑多局，
得先决定这条权限到底该不该要审批。

副作用是真的：它往仓库的 `trace_data/` 和 `experiment_results/` 里写真实数据，
和手跑一次入口完全一样。**重定向到临时目录就等于没测落盘**——
而落盘正是这次修掉的那个 bug 所在的地方。`run_id` 带 `test-` 前缀便于事后清理。

**影响面**：`trace_data/` 里已有的数据**救不回来**，那些 run 只能重跑。
`_save_event` 的修复不改任何接口。

## 2026-08-25 —— 注释分层：代码只说"是什么"，docs/spec 独占"为什么"

**改了什么**：全仓 65 个文件、286 个函数走了一遍。

- 每个模块 docstring 压到 ~400–600 字，只留"这个文件干什么"和读代码当场用得上的
  几条硬约束；长论证搬去 `docs/spec/`。`harness.py` 3784 → 714 字，
  `brain.py` 1256 → 697，其余同比例。
- **每个函数 docstring 的最后一句是一句 30 词以内的"它干什么"**，前面才是契约与取舍。
  原先缺 docstring 的 46 个函数（`errors.py` 的六个 `__init__`、`trace/browser.py`
  的十个方法、`memory_tool.py` 的十二个方法……）全部补上。
- 行内注释按同一把尺子收：`harness.py` 110 → 40 行、`brain.py` 47 → 21 行，
  全仓 392 行。删掉的都是已经进了 spec 的长段论证，留下的是"读这几行代码时
  当场需要知道"的那种。

**为什么这么改**：论证有两个读者，需求不一样。**读代码的人**要在三秒内知道
"这个函数是干嘛的"，然后回到他自己的问题上；**读设计的人**要知道"为什么不是
另一种做法"。把两者压在同一段 docstring 里，第一个读者每次都要先跳过五十行
才找得到答案——而他一天要跳几十次。

结尾句放在**最后**而不是开头，是刻意的：docstring 的开头是契约（前置条件、
后置条件、失败语义），那是**调用前必须读**的；"它干什么"是读完契约之后的收束，
也是只想扫一眼的人直接跳到底就能拿到的那一行。

**取舍**：**先补 spec，再删代码里的论证。** 顺序反过来就会丢东西——
上一条 CHANGELOG 那次 spec 重写就是为这一步做的准备。凡是 spec 里没有对应
落点的论证，这次一律没删（比如 `_judge` 的早退分支为什么为 resume 保留、
`ValidationError` 不是 `AgentError` 子类那段）。

不给 `__init__.py` 之外的每个文件强行凑满 200 词——**短文件就该短**。
`schemas/action.py` 的模块 docstring 只有 67 字，够了。

**影响面**：纯注释。`py_compile` 全仓通过，没有一行可执行代码变动。

## 2026-08-25 —— docs/spec 追上代码

**改了什么**：`harness/SPEC.md` 整篇重写；`schemas/SPEC.md` 删 `Intent` 一节、
新增 `completion.py` 一节；`brain`/`prompts`/`interfaces`/`tools` 四份按实际接口订正；
`build/SPEC.md` 新增「3b. `agent_permission` —— 横切的权限层」并更新 manifest 现状；
`README.md` 的循环流程、不变量、过渡态三节重写。

**为什么这么改**：spec 的漂移**不止这次改动造成的**。清点下来，代码里已经不存在、
spec 里还在描述的名字有：`_inspect`（7 处）、`_dispatch`、`_push_goal`、`_nodes`、
`see_objects`、`recent`、`Intent`（26 处）、`MAX_GOAL_DEPTH`；此外
`known_here`/`knowledge_base`/`write_episodic`/`note_step`/`query_episodic` 这批
`MemoryToolPort` 的旧方法名在 spec 里出现 60 多次，代码里早就改成了
`query_objects`/`query_knowledge`/`store_episode_step`/`store_objects_interactions`/
`query_episode_steps`。一份指着不存在的方法讲设计的文档，比没有文档更费时间——
读的人会先花半小时确认自己没找错地方。

**取舍**：**删掉的东西留"墓碑"而不是直接抹去。** `Intent`、`INTENT_HELP`、
`intent_help.md`、`_judge_all` 各自保留一节，写清楚它是什么、为什么删、
以及**重写时要捡回来的那几条论证**（多层判定的隔离与可标定性、判据不能省、
`SCREEN_COORD` 拦的是哪个具体教训、代价不对称要让模型知道）。
这些论证是踩出来的，代码里删干净了就只剩这一处载体。

**不再标注行号。** 上一版每节都挂着 `harness.py:295-334`，一次重构之后全部失效，
而失效的坐标比没有坐标更糟——它会把人带到错误的地方。改成按方法名索引。

**没做**：`world`/`providers`/`memory` 三份没动，`MemoryToolPort` 旧方法名那 60 多处
也没改——那些是这次改动之前就欠下的，混进来会让这条记录说不清是哪一半的锅。
`README.md` 的「已知的过渡态」里记了三条待办：`inspect` 半死链路、
拆子目标机制待重写、`tests/` 被 gitignore。

**影响面**：纯文档。

## 2026-08-25 —— outcome 只在 run() 的出口算一次，`LoopState.outcome` 删掉

**改了什么**：`_outcome()` 这个方法删了，内容内联进 `run()` 的出口；
`LoopState.outcome` 字段删了；`_look` 的终止分支不再多带字段；
`_summarize` 的 `success` / `steps` 直接从 `state.observation` 读。

**为什么这么改**：两条，第二条是真的会咬人。

一是位置不对：`_outcome()` 挂在 `_look` 里，一个叫"看一眼"的节点顺手把这一局的
最终结论下了。和上一版把蒸馏、`EPISODE_END` 从它里面搬走是同一类毛病，只是轻一些。

二是**同一份信息算了两遍**：`EpisodeOutcome` 和 `EPISODE_END` 的 payload
逐字段对应（success / steps / reason）。算在两个地方，迟早不一致——
而不一致时**没有任何东西会报错**：返回值说成功、事件流说失败，
离线统计和调用方各信一半，而且要等到对账的时候才发现。
搬到一起之后它们从同一个 `obs` 派生，不一致这件事在结构上就不可能。

**取舍**：不包成方法。它只有一个调用方，而且是三行纯翻译（三个 if 选一个字符串），
包起来只会让"这个数是怎么来的"多隔一跳。做成图节点更不行——
图上的格子代表"发生了一件事"（调模型、推世界、写库），
`_outcome` 不花钱不改世界不写记忆，给它一格会稀释"读图 = 看这一局做了哪些真事"。

顺带解掉一个隐患：`space` 和 `outcome` 以前互斥填充，`LoopState` 里任何时刻
都有一个是上一轮的陈值，靠调用图保证下游不会读错——不是靠类型。
`outcome` 没了之后这个形状本身消失了。

`run()` 的出口断言也跟着换了：从"某个字段被填了"（`outcome is not None`）
换成"图不该在这一局跑完之前结束"（`obs is not None and obs.done`）——
后者才是真正要保的那条。

**影响面**：`Harness.run()` 的签名与返回值不变。`LoopState` 少一个字段，
自建 `LoopState` 的地方（只有 `_begin`）不受影响。

## 2026-08-25 —— 图拉直：删掉 intent 分派与多层判定，收尾拆成 summarize + run

**改了什么**：

- 删 `Intent` 枚举、`Action.intent` / `Action.goal`、`ActionSpace.intents`、
  `_fields_must_match_the_intent`；`Action.name` 从可选变必填。
- 删 `_dispatch` / `_push_goal` / `_nodes` / `_space` / `MAX_GOAL_DEPTH`
  / `EventType.GOAL_PUSH` / `trace_utils.goal_push()`；`harness/utils.py` 清空。
- 删 `_judge_all`（线程池并发判每一层）。`_judge` 改成只判栈顶 `goals[-1]`，
  完成就出栈，栈空 = 任务完成。
- 图新增 `summarize` 节点：`look --done--> summarize --> END`。
  `_summarize_episode` 从 `_outcome()` 里搬进去，并与节点函数合并成一个 `_summarize(state)`
  ——`result` 是从 `state.outcome` 取出来又传回去的同一个对象，去掉参数之后
  两者签名一模一样、其中一个只剩一行转调，那就是一个方法多了；
  节点函数额外收一份自己就能读到的状态，还会让人以为它可以被喂进一个和 `state`
  不一致的 outcome。`_outcome()` 变成纯构造。
- `EPISODE_END` 从 `_outcome()` 搬到 `run()`，和异常路径共用一个出口。
- brain 侧跟着删 `_parse_intent`、intent 校验、`$intents` 渲染、`INTENT_HELP`、
  `SCREEN_COORD`；`decide_action.md` 去掉 intent 段落和 push_goal / inspect 两个例子。

**为什么这么改**：拆子目标的机制要**换个地方重写**，所以先把当前这套接线拆干净。

拆一半最坏：`Intent` 留在 schema 里、图上却没有 `push_goal` 的去处，
模型照样能输出 `intent: "push_goal"`（prompt 里还写着），然后在分派处炸——
一个只在特定输出下才出现的崩溃。要么两头都留，要么两头都删。

`_judge_all` 跟着删是因为它的前提没了。它存在的理由是"中间层完成时，上面那些
当初为它拆出来的一起作废"，而压栈的唯一途径已经删了、栈恒为一层。
对一层的栈来说"每层各判一次"和"判栈顶"是同一件事，只是前者还额外背着一个线程池、
一段并发写 trace 的注意事项、一个恒为 0 的 `depth`。

`summarize` 独立成节点，是因为它**要调一次模型**。藏在 `_outcome()` 里的时候，
图上看不到"这一局结束时还额外烧了一次调用"，读图的人会以为一局的开销就是
`steps × (感知 + 决策 + 判定)`。图上看得见的东西才会被算进成本。

`EPISODE_END` 搬进 `run()`，是为了让正常结束和异常终止共用同一个出口。
分散到图内图外各写一次，迟早有一条路径漏掉——而漏掉的那些局会直接从
成功率的分母上消失，正是上一条改动刚修完的那类问题。

**取舍**：

`goals` 保留成**栈**而不是压成单个 `goal`，当前目标恒为栈顶。栈恒为一层，
所以 `if not remaining`（栈空才写 success）在今天永远成立——留着它不是为了当下分支，
而是把"只有任务目标本身完成才算成功"写成代码：子目标回来之后，agent 自己压的那些
完成了只该弹栈，不该给自己发奖状。这是唯一刻意保留的"占位"，因为它是一条**规则**，
不是一个抽象。

反过来，多层判定那份权衡（判定之间的隔离、单目标判定的可标定性 vs 合成一次省 token）
**只记在这里，不留在代码里占位**。占位的抽象会把下一版往旧形状上带，
而拆解机制在别处重写时，多层判定要不要回来、以什么形状回来，是那时的决定。

`goal_pop` 的 `reason` 字段留着（现在只有 `done` 一个取值，`superseded` 没了）：
拆解回来时"完成"和"白拆"仍然必须分得开，而那是判断目标栈到底帮没帮上忙的那个数。

**影响面**：`Action` / `ActionSpace` 的形状变了，所有构造点已扫过（测试里的
`Action(name=..., thought=..., rationale=[...])` 本来就没传 intent，不受影响）。
`Harness` 与 `BrainPort` 的对外签名不变。
`prompts/intent_help.md` 和 `harness/utils.py` 已清空但**还需要手动删除文件**；
`prompts.load_sections()` 随之变成零调用方，留着还是删掉见该函数的说明。

## 2026-08-25 —— `Completion` / `VisionCompletion` 从 interfaces 挪进 schemas

**改了什么**：新增 `schemas/completion.py`，把 `interfaces/llm.py` 的 `Completion`
和 `interfaces/vision.py` 的 `VisionCompletion` 搬进去；两个接口文件改成从
`schemas` 引入，各自的模块 docstring 说明"这里只放 Protocol"；
`providers/dashscope.py` 和三个测试文件的 import 跟着改；
目录说明那一行补上 `Completion`。

**为什么这么改**：目录分工写的是 `schemas/` 放 Pydantic 数据模型、`interfaces/`
放 Protocol（第四节）。这两个类长在接口文件里读起来顺——就在用它们的 Protocol 旁边——
但那让 `interfaces/` 同时承担了两件事。代价不是洁癖：接口先行那条规矩说
「光读 `interfaces/` 就能看懂整个系统怎么运转」，数据模型混在里面，
读的人分不清哪些是**契约**、哪些是**契约里流的东西**。

**取舍**：两个类放同一个文件，不各建一个。它们回答同一个问题（"一次模型调用回来了什么"），
而且都带着一个不是记账、而是正确性证据的字段（`truncated` / `input_tokens`）——
这个共同点是踩出来的，分成两个文件就没地方写。
字段名仍然不统一（`prompt_tokens` vs `input_tokens`），跟各自网关返回的名字走：
中间再翻译一层，排查"网关到底报了什么"时就得反查映射表。
**没有留 re-export 兼容层**——留了等于 `interfaces/` 还在导出数据模型，这次改动就白做。

**影响面**：纯搬家，没有行为变化。`from pokemon_agent.interfaces.llm import Completion`
这种写法会断，仓库内的引用点已全部改完（4 处）。

## 2026-08-25 —— 一局无论怎么死，trace 里都留下完整的 START…END

**改了什么**：`_begin()` 挪进 `run()` 的 `try`；`EPISODE_START` 挪到 `_begin()` 的
第一行（`reset()`/`save_state()` **之前**）；删掉专门捕获权限异常的那个 `except`；
`RunManifest` 新增 `permissions` 字段与 `with_permissions()`，`validate_design()`
断言它非空，`run_experiment.py` 的装配链上加一环；新增
`tests/test_harness_episode_boundary.py`。

**为什么这么改**：三件事其实是同一件——**"这一局到底发生了什么"必须能被事后重建**。

`_begin()` 在 `try` 外面是真 bug：它调 `save_state()`，而 `execute:game:save_state`
是配置里唯一 `approval_required` 的权限。人类拒批或审批超时抛出来的异常从这里逃走，
这一局连 `EPISODE_END` 都没有，正好撞上那段注释要防的"从分母上消失"。
`EPISODE_START` 也一样：它原本写在 `reset()`/`save_state()` 之后，注释却声称
"episode 的边界应该是这一局在事件流里看到的第一条事件"——那句话只在这两步都成功时成立。

权限那个 `except` 的函数体和兜底逐字相同，删掉它程序行为一个字节不变。留着的坏处是
它**看起来**已经把权限失败单独处理过了，于是这件事不会再有人回来做。

manifest 记权限配置是 prompt 那条论证的同一个应用：`permissions.json` 里角色少一条
`read:memory:knowledge`，这批 run 跑的其实是"无知识库"那个消融组，而 trace 里
**没有任何字段说得出这件事**。它全程不变、又不在版本库里，所以既要 sha 也要原文。

**取舍**：`EPISODE_START` 提前写，代价是可能出现"一步没跑就结束"的 episode，
但那本来就是事实，`EPISODE_END` 的 `reason` 会说清楚。
权限失败仍然不单独成一类失败模式——真要按权限名聚合时，改的地方是
`trace_utils.episode_error()` 内部（翻译异常是那个纯函数的职责），不是控制流。
`validate_design()` 断言 `permissions` 非空会让**任何**没走 `with_permissions()`
的装配当场失败，这是故意的：宁可开跑前炸，也不要事后拿到一批无法归因的数据。

**影响面**：`Harness` 的对外签名不变。`RunManifest` 多一个必填约束——
自建 manifest 的调用方（目前只有 `run_experiment.py`）必须补 `.with_permissions()`。
测试新增一个文件，不动已有测试。

## 2026-08-25 —— 抬到 Python 3.11，并把 agent-permission 写进依赖

**改了什么**：`requires-python` 从 `>=3.10` 改为 `>=3.11`，ruff `target-version`
跟着改成 `py311`；`agent-permission` 补进 `dependencies`；CLAUDE.md / AGENTS.md
第七节的"Python 3.10"同步改掉。

**为什么这么改**：`agent_permission.audit` 用了 `enum.StrEnum`，那是 3.11 才有的。
声明 `>=3.10` 是一句**假的**承诺——照着它建 3.10 环境，装完在 import 权限库时就炸，
而报错指向 `enum`，离病因隔了两层。依赖漏写是同一类问题的另一半：这个库一直靠开发机上
恰好装过才跑得起来，干净环境 clone 下来根本起不来，而那正是复现实验的起点环境。

**取舍**：抬版本而不是给库降级（把 `StrEnum` 换成 `class X(str, Enum)` 也能跑 3.10）。
理由是这个项目没有任何跑在 3.10 上的理由，而降级要改的是**另一个仓库**，
为了迁就一个我们自己都不需要的下限去改上游，方向反了。
依赖用 git URL 而不是版本号，是因为权限库还没发到 PyPI；发了之后换成版本号，
届时要能锁版本——`permissions.json` 的语义变化会静默改变实验条件。

**影响面**：只动构建元数据和规范文档，不动运行代码。已有的 3.10 环境需要重建。

## 2026-08-23 —— 记忆观测改为显示名称和标题

**改了什么**：`known_object` 改为显示物体名称，`knowledge` 改为显示知识标题，
`episode_level` 保持只显示数量；新增短标签字段，限制每类最多显示 5 项、每项 80 字符。

**为什么这么改**：布尔值“有/无”无法回答具体召回了什么，而完整正文又会让 SSE 页面失去
可读性；展示短标签能保留可解释性而不传输大段文本。

**取舍**：标签从渲染文本的首行提取，当前不引入新的知识元数据模型；标题格式变化时，
提取结果会随内容变化。

**影响面**：仅影响浏览器/控制台的记忆展示和新增 trace payload 字段，不影响检索排序。

## 2026-08-23 —— 明确四类记忆的观测名称

**改了什么**：浏览器和控制台统一显示 `step_memory`、`known_object`、`knowledge`、
`episode_level`，并在 `memory_read` payload 中增加对应的明确计数字段。

**为什么这么改**：`episodic` 和 `episode` 容易混淆单步记忆与跨局经验，无法直接看出
当前检索结果属于哪一层。

**取舍**：保留旧字段 `count`、`known_objects`、`episode_memory_count`，保证历史事件和
旧消费者仍可读取；新观测使用明确字段。

**影响面**：仅改变 trace 展示和新增 payload 字段，不改变记忆检索结果。

## 2026-08-23 —— 将本地 trace 实现重命名为 LocalTrace

**改了什么**：`pokemon_agent.trace.store.MockTrace` 正式更名为 `LocalTrace`，同步更新
装配代码、运行脚本和当前文档；保留 `MockTrace` 兼容别名，避免旧测试和外部脚本立即失效。

**为什么这么改**：该实现已经负责 JSONL 落盘、replay、控制台输出和浏览器 SSE 推送，
不再是测试替身，`MockTrace` 这个名字会误导调用方。

**取舍**：暂不删除兼容别名，等旧调用方迁移后再移除。

**影响面**：新代码应使用 `LocalTrace`；TracePort、事件格式和运行行为不变。

## 2026-08-23 —— 增加最小浏览器 SSE 观测台

**改了什么**：新增标准库实现的本地 `BrowserTraceServer`。`run_episode_loop.py` 启动
 session 时自动监听本机端口并打开浏览器，`LocalTrace.sse()` 将信息事件推送到页面；
控制台保留 episode、模型调用、错误等控制流输出。

**为什么这么改**：浏览器更适合展示 observe / retrieve_memory / think / act 这样的信息流，
控制台继续承担运行控制和成本/错误诊断，避免两边输出互相干扰。

**取舍**：页面只做文字展示，不做历史回放、筛选或鉴权；无浏览器连接时事件直接丢弃，
完整事件仍然写入 JSONL trace。

**影响面**：通过 `python -m probe.run_episode_loop ...` 启动时自动打开本地观测页；
Harness 和 `TracePort` 调用方式不变。

## 2026-08-23 —— trace 增加 phase 并压缩记忆读取输出

**改了什么**：`TraceEvent` 增加 `phase` 字段，由 trace 实现根据事件类型推导；控制台
step 输出增加 `----- STEP -----` 和 `--- MEMORY RETRIEVAL ---` 分隔符。记忆读取事件
不再把完整知识文本塞进 trace 展示 payload，只记录是否命中及字符数，跨局经验保留引用。

**为什么这么改**：浏览器信息流需要按 `episode_id + step + phase` 聚合，读者需要看到
清晰的阶段边界，而不是被完整知识文本淹没；控制流仍留在控制台。

**取舍**：暂不增加冗余的 `turn_id`，也不重构完整生命周期事件；当前环境尚无独立浏览器
SSE 端点，后续只替换 `TracePort.sse()` 的输出实现。

**影响面**：trace JSONL 和控制台观测格式变化；Harness 的事件调用方式不变，事件仍由
`event_id` 单调排序，episode memory 的检索逻辑不变。

## 2026-08-23 —— 知识库检索粒度改为按文件

**改了什么**：`knowledge/store.py::load_chunks()` 不再按空行拆分，而是把每个非空
`.md` 文件作为一个知识 chunk；同步更新了相关说明和缓存注释。

**为什么这么改**：同一文件中的标题、规则和示例通常共同描述一个主题，按段落拆分
容易让召回结果丢失上下文；按文件检索更符合当前知识库的组织方式。

**取舍**：单个文件过大时召回粒度会偏粗，后续如果某个攻略文件明显超过上下文预算，
再针对该文件引入带标题的层级分块。

**影响面**：知识库的 BM25、embedding 和 reranker 都以文件为单位工作；episode memory
仍保持一条 `EpisodeMemory` 一个 chunk，`query_episodic()` 不受影响。

## 2026-08-23 —— 跨局摘要记忆/知识库换成 embedding + reranker 混合检索；query_episodic 改回全包

**改了什么**
上一条刚落地的字符 bigram TF-IDF 被这一条整体替换：新增 `interfaces/embedding.py`
（`EmbeddingProvider`）、`interfaces/rerank.py`（`RerankerProvider`）两个 Protocol，
`providers/local_embedding.py`/`providers/local_reranker.py` 分别用 `fastembed`
（ONNX Runtime，不依赖 torch）接入 `BAAI/bge-small-zh-v1.5`（embedding）和
`BAAI/bge-reranker-base`（reranker），全项目只有这两个文件直连模型。
`memory/retrieval.py` 新增 `bm25_rank`（关键词，`rank-bm25`）+ `embedding_rank`（向量余弦）
两路召回，用 `reciprocal_rank_fusion`（RRF，k=60）融合，再交给 reranker 精排——
标准的"广召回 + 精排"两阶段检索。`MemoryTool` 的 `query_episode_memories()` 和
`knowledge_base()` 都改用 `hybrid_retrieve()`；reranker 分数是无界 logit，
先做 min-max 归一化再和质量/成功权重相加。`knowledge/store.py` 从"整份读入不筛选"
换成 `load_chunks()`（按空行分段）+ `mtime()`（改文件即失效缓存），因为知识库接下来
会塞进克制关系表、攻略这类会长大的内容，不能再指望全塞进 prompt。

顺带把 `query_episodic()` 改回"全包"：签名从 `(query, limit)` 变成 `(episode_id)`，
不再做任何相关性排序或截断，只按 `episode_id` 过滤、按 `step` 升序返回。单步情景记忆
本来就该是"这一局发生过的事"，不该被检索式的相关性打分筛掉——上一条把它和跨局摘要
记忆混在一起打分是设计错误，这里改正。

`harness.py::_retrieve_memory()` 和 `build.py::build_real()` 同步更新签名/装配
（`MemoryTool` 新增 `embedding_provider`/`reranker_provider` 两个必填构造参数）。

**为什么这么改**
用户明确要求"正常的 RAG 那套"——真实 embedding + reranker + 关键词混合检索，
而不是上一条的字符重叠近似。模型来源选本地离线下载（不走 dashscope 这类远程 API），
避免每次检索都产生网络调用和额外计费。BM25 分数和余弦相似度量纲不同、不能直接相加，
RRF 只看排名不看分数量级，天然绕开这个问题。

**取舍**
- `fastembed` 而不是 `sentence-transformers`：后者依赖 `torch`，体积和安装成本都高得多；
  `fastembed` 走 ONNX Runtime，本项目已经因为 `magika` 间接依赖它，零增量。
- embedding 只在写入时算一次并缓存（`_episode_memory_vectors`），不是每次检索都对全库
  重新编码——避免检索延迟随记忆库增长线性变差。知识库的向量缓存按 `mtime` 失效，
  保留了原设计"改 `.md` 文件不用重启进程"的性质。
- reranker 的候选集上限（`fuse_top_k`，默认 `max(limit*3, 10)`）是个经验值，
  不是精确算出来的——候选太少精排没有意义，太多则拖慢每一步的决策延迟。
- 没有做端到端的真实模型推理验证：开发环境的沙箱出于安全策略屏蔽了 HuggingFace Hub，
  模型权重下载不了。逻辑本身（BM25/RRF/融合/归一化）用假的确定性 embedding/reranker
  在测试里验证过，`FastEmbedText`/`FastEmbedReranker` 的调用方式对照 `fastembed`
  源码里的真实签名核对过，但没有在这次改动里真的跑过一次下载+推理。
- 测试文件里已经存在的 `MemoryTool()` 零参调用（`test_poses.py` 九处，另外
  `test_goals.py`/`test_judge.py` 里也有类似的旧调用）在这条改动前就是坏的
  （构造函数早改了）——这次多了两个必填参数，它们仍然是坏的，没有顺手修，
  留给后续单独处理。

**影响面**
`MemoryTool` 的构造函数签名（新增两个必填参数）、`query_episodic`/`knowledge_base`
的调用签名，波及 `harness.py`、`build.py`、`tests/test_episode_memory.py`。
`pyproject.toml` 新增依赖 `fastembed`、`rank-bm25`。`memory/vector.py` 的
`tokenize()` 仍在用（`bm25_rank` 依赖它分词），但 `tfidf_vector`/`cosine_similarity`
不再被业务代码调用，只剩 `test_vector.py` 覆盖，暂不删除。

## 2026-08-23 —— 跨局摘要记忆检索换成轻量向量相似度（字符 bigram TF-IDF + 余弦）

**改了什么**：新增 `memory/vector.py`——四个纯函数（`tokenize`/`build_idf`/
`tfidf_vector`/`cosine_similarity`），零新增依赖，标准库 `math` 之外什么都
没引入。`MemoryTool.query_episode_memories` 的排序从字符集合重叠计数换成
这一套：场景过滤剩下的候选集现算一次 IDF，查询词和每条候选各自转成 TF-IDF
向量，用余弦相似度当"文本相关性"这一项，再按老规矩叠加质量分和成败权重
（`EPISODE_RELEVANCE_WEIGHT`/`EPISODE_QUALITY_WEIGHT`/`EPISODE_SUCCESS_WEIGHT`）。
新增 `tests/test_vector.py`（纯函数各一个用法示范）和
`test_relevance_ranks_topically_close_memories_above_unrelated_ones`
（`test_episode_memory.py` 里新增，验证质量分打平时题材相关的记忆确实排前面
——这是换向量相似度真正要验证的行为，字符重叠那版做不到这一点）。

**为什么这么改**：用户直接要求"现在就做轻度的向量相似度"。选字符 bigram 而不是
分词：项目文本是中文，标准库没有分词器，而且这个阶段明确"零新增依赖"
（用户原始设计文档里的取舍，CLAUDE.md 第六节同样的态度）；bigram 比
`MemoryTool._overlap` 原来用的单字符集合多留住一点点词序信息（"前进"和"后退"
的单字符集合会互相污染，bigram 不会），复杂度增量却几乎为零。IDF 现算、
不缓存：语料（候选集文本）随每次写入变化，量级还是个位数到几十条，现算的
成本远低于维护一份缓存失效逻辑，和 `knowledge/store.py` 的 `load_all()`
不缓存是同一个理由。相关性权重定得比质量/成功权重大，是因为"这条经验到底
切不切题"应该是排序的第一道判据，质量/成功只用来在相关性接近时挑更可信的
那条——不然一条题材完全不相关但质量分拉满的摘要会排到题材相关但质量普通的
摘要前面，那就是"按质量排序"而不是"检索"了。

**取舍**：只接了跨局摘要记忆（`query_episode_memories`）这一条检索路径，
单步情景记忆（`query_episodic`）还是原来的字符集合重叠，**没有动**——那条
路径查的是"哪一步画面和现在最像"，`MemoryEntry.render()` 的内容（位置/四邻/
对话框）比自然语言摘要短得多、结构化程度更高，字符重叠在那种场景下没有明显
短板，这次没有必要跟着换，等真的观察到排序不准再说。向量不落盘、每次检索
现算，没有为"语料涨到几百条之后现算太贵"这个还没到来的问题预留缓存接口。

**影响面**：`query_episode_memories` 的排序结果会变（同样的输入，相关性算法
换了，具体名次可能不一样），但方法签名和调用方（`Harness._retrieve_memory`）
不用改一行。`_episode_score` 的签名变了（从接收 `query: str` 改成接收算好的
`query_vec`/`idf`），这是 `MemoryTool` 内部私有方法，不影响任何外部调用方。

## 2026-08-23 —— 把跨局摘要记忆接进循环：retrieve 查、episode 结束才落盘

**改了什么**：`Harness._retrieve_memory()` 现在除了单步情景记忆
（`query_episodic`）和语义记忆（`known_here`/`knowledge_base`），也调
`MemoryTool.query_episode_memories(scene, query, limit)`——查询词用
`state.task.goal`（"和当前任务相关"），场景用 `obs.place.map_id`，命中的话
折进 `obs.facts["episode_memories"]`，走的是和 `known_objects`/`knowledge`
一样的路径（同一条 `MEMORY_READ` trace 事件，`trace/utils.py` 的
`memory_read()` 加了 `episode_memories` 参数）。`Harness._outcome()` 新增
`_summarize_episode()`，在 `EPISODE_END` 之前调恰好一次
`MemoryTool.summarize_episode(...)`——这是这一局唯一一处跨局摘要记忆的落盘点；
单步记忆和 object 语义记忆继续在 `_remember()` 里逐步落盘，两条落盘路径互不干扰。
`Harness.__init__` 新增 `run_id` 参数（默认 `"local"`，和 `MockTrace` 的默认值
对齐），`build.py` 的 `build_real()` 同步加了 `run_id`/`memory_model` 两个参数，
并把 `MemoryTool()`（零参数，一调用就会 `TypeError`）改成正确传入
`trace_port`/`llm_provider`——这是装配路径上此前就存在、但从来没被跑到过的断链，
不修的话这次接入的两条新路径在真实环境里根本启动不了。`MemoryToolPort` 协议
补上 `summarize_episode` 的声明（Harness 只依赖接口，不该调协议里没有的方法）。

**为什么这么改**：讨论里定下来的分工——retrieve 时把 episode 级和 semantic
级记忆都查出来喂给决策，落盘只在两个时机发生：单步记忆和 object 语义记忆每步
落（"remember"），跨局摘要记忆只在 look 判定这一局结束时落一次（"look 到 end
之间"）。查询词特意不用 `Snapshot.of(obs).render()`（那是给单步记忆用的画面
相似度检索）——`EpisodeMemory.render()` 里没有位置/地标这些字段，两边词汇不
重叠，拿快照去查会一条都选不中；跨局摘要记忆问的是"这类任务别的局怎么打"，
天然该用任务目标去匹配。蒸馏失败（LLM 解析不出合法 JSON）在 `_summarize_episode`
里只吞 `ValueError` 这一种、有名字的失败——`generate_summary` 内部已经为它
留了一条 `ERROR` trace，这里不该让它拖累这一局本该正常记录的 `EPISODE_END`。

**取舍**：`run_id` 没有单一真相来源——`TracePort` 的实现自己持有一份、不对外
暴露 getter，`Harness` 只能另外存一份，传自定义 `trace` 时要记得让两处
`run_id` 对上，这次没有花力气把 `TracePort` 协议改成能对外暴露 `run_id`（那是
更大的改动，超出这次的范围）。`memory_model` 默认复用 `text_model`，没有像
判定器那样强制建议单独选型，先能跑起来，调优留到有真实数据之后。

**影响面**：`MemoryToolPort` 新增一个协议方法；`trace_utils.memory_read()` 新增
一个可选参数，向后兼容旧调用点；`build_real()` 新增两个带默认值的可选参数，
不改变现有调用方式。仍未修：`tests/test_goals.py`/`test_judge.py`/
`test_poses.py` 里一共 12 处 `MemoryTool()` 零参数构造，和 `test_poses.py`
那处一样，是更早就存在、和这次改动无关的断链——这些测试全部因为没有
`assets/rom` 被跳过，从没被真正跑到过，所以现在都不遇到（会在有 ROM 的机器上
`TypeError`），值得单独找时间批量修一次。

## 2026-08-23 —— 跨局摘要记忆（EpisodeMemory）：场景硬过滤 + 质量/成功加权检索

**改了什么**：新增 `schemas/memory_episode.py`（`EpisodeMemory`，含
`matches_scene()` 的场景通配判定）；`MemoryTool` 新增
`query_episode_memories`/`write_episode_memory`/`episode_memory_size`/
`summarize_episode`，`interfaces/tools.py` 的 `MemoryToolPort` 同步加了这三个
协议方法；顺手修掉了这条链路上此前就存在、但从未被跑到过的几处断链：
`memory/utils.py` 的 `_create_memory_entry` 硬凑 `MemoryEntry` 字段导致
一调用就会 `ValidationError`（现在是 `_create_episode_memory`，产出正确类型）；
`EpisodeMemoryGenerator.__init__` 签名和 `MemoryTool` 里的调用点参数个数对不上；
`Source.MEMORY` 在枚举里根本不存在（现已补上，见 `schemas/trace.py`）。
新增 `tests/test_episode_memory.py`，覆盖场景过滤、通配、排序、蒸馏全链路。

**为什么这么改**：讨论 RAG 检索设计时定下来的结论——检索单元是**一整局**蒸馏出的
经验，不是单步记忆，两者不该共用同一套存储和检索路径（同一局内的单步记忆不该被
跨局检索拿走）。场景过滤按 `map_id` 硬匹配，但允许 `applicable_scenes` 留空或标
`SCENE_ANY` 表示"任何场景都适用"，避免通用经验（"进草丛要连按"）被过滤误杀；
排序在文本相关性之外叠加质量分和成败两个信号，量级刻意选得比文本重叠分大，让
"质量高/成功过"的摘要能压过"文本刚好多重叠几个字但质量很差"的摘要，具体权重
留到接了真实数据再调。之所以顺手修了那几处断链：不修的话新功能就是在一段
`ValidationError` 必现的死代码上继续搭，测试根本跑不起来。

**取舍**：没有把这条检索路径接进 `harness.py` 的主循环——什么时候调
`summarize_episode`、检索结果该塞进 prompt 的哪个位置，这是编排层的决定，
不是这次要解决的问题，留给下一步。排序权重（`EPISODE_QUALITY_WEIGHT`/
`EPISODE_SUCCESS_WEIGHT`）先拍了两个常数，没有接真实回放数据调过。

**影响面**：新增两个类型（`EpisodeMemory`）和三个协议方法，不改动任何已有的
单步情景记忆（`MemoryEntry`/`query_episodic`/`write_episodic`）行为。
另外发现 `tools/memory_tool.py` 里 `note_step()` 调用的 `_should_note_step()`
在 HEAD 上从未被定义过（`tests/test_memory.py` 里练到它的用例因为没有
`assets/rom` 一直被跳过，没人抓到）；这次顺手给了一个保守的默认实现（有
`before.place`/`after.place`/非空 `action.name` 才继续判），但没有深入验证是否
就是原意——这处修复没有测试覆盖，值得单独找一次真机会话确认。
`tests/test_poses.py` 里 `MemoryTool()` 零参数构造也和当前构造函数签名对不上，
是另一处独立的既有断链，这次没有动它，一并记在这里以免下次以为是这次改坏的。

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
## 2026-08-24 —— 建立 experiment 实验环境与从头 replay
**改了什么**：新增 experiment 入口、实验任务定义、manifest 实验元数据、episode 起点存档和从头 replay 约束，并补充野生遭遇知识实验提示。
**为什么这么改**：短程/长程、知识召回和情景记忆实验必须能从 manifest 解释实验自变量；每个 episode 还必须有独立起点，避免连续运行状态无法复现。
**取舍**：experiment 入口先复用 probe 实现，减少原型阶段分叉；暂不实现从中间事件续播，因为它会把不完整上下文误当成可复现 replay。
**影响面**：新增实验层能力；probe 每局额外保存起点存档；已有 trace 的 partial replay 调用会显式失败。
## 2026-08-24 —— 将 episode runner 正式移入 experiment
**改了什么**：`run_episode.py` 与 `run_episode_loop.py` 从 `probe/` 移到 `pokemon_agent/experiment/`；Harness 在 reset 后、第一步观测前保存真实 episode 起点 state；补充 World/GameTool 的 save_state 接口。
**为什么这么改**：probe 是探索脚本，实验 runner 应属于可复现实验环境；起点存档必须在 episode 开始边界生成，不能在结束后推测。
**取舍**：暂时不实现全局长期记忆；`memory_policy` 仅记录摘要经验作用域，当前支持 session_local，未来预留 cross_run_import。
**影响面**：启动命令路径改变为 `python -m pokemon_agent.experiment.run_episode_loop`；旧 probe runner 不再保留。
## 2026-08-24 —— 固定短程入口与摘要经验作用域
**改了什么**：明确短程任务由 `experiment/run_episode.py` 启动；`memory_policy` 固定为 `session_local`，移除跨 run 导入语义。
**为什么这么改**：短程与长程的启动边界必须和实验定义一致；摘要经验本来就是当前 session/run 的内部变量，不能让 manifest 暗示存在跨 run 实验。
**取舍**：暂不支持跨 run 摘要迁移，也不把它作为实验变量。
**影响面**：短程命令路径和 manifest 校验语义更新，长程仍由 `run_episode_loop.py` 负责。
## 2026-08-24 —— 整理 memory 目录边界
**改了什么**：将语义检索、向量、语义接口与对象工具移入 `memory/semantic/`；将 episode 摘要和 episode 工具移入 `memory/episode/`；删除旧路径。
**为什么这么改**：semantic knowledge 与 episode 经验的生命周期、检索条件和实验含义不同，目录边界应直接表达这一设计。
**取舍**：原型阶段不保留兼容入口，强制所有调用方使用唯一的新目录结构。
**影响面**：`MemoryTool` 和测试统一使用新路径，旧 import 将直接失败。
## 2026-08-24 —— 分离 semantic protocol 与检索实现
**改了什么**：将 `SemanticObjectStore` 移到 `interfaces/semantic_memory.py`；更新 `MemoryTool` 的接口引用；明确 `semantic/vector.py` 是 TF-IDF 词法工具而非 embedding 模型。
**为什么这么改**：Protocol 属于跨层契约，应位于 interfaces；具体 semantic 实现只依赖接口，不应拥有接口定义。
**取舍**：保留 TF-IDF 作为混合检索中的轻量词法组件，不把它误命名成神经 embedding。
**影响面**：`MemoryTool` 的接口 import 路径改变；运行时模型配置不变。
## 2026-08-24 —— 删除重复的 TF-IDF vector 实现
**改了什么**：删除未被生产代码使用的 `semantic/vector.py` 和对应测试；将 BM25 所需的字符 bigram tokenizer 收回 `semantic/retrieval.py`。
**为什么这么改**：当前检索已经使用 `rank_bm25.BM25Okapi`，额外保留一套 TF-IDF/余弦相似度既不参与运行又重复表达词法检索。
**取舍**：保留字符 bigram 分词，因为 BM25 仍需要它；不保留第二套本地 TF-IDF 排序器。
**影响面**：semantic 检索实现更单一，删除死代码和对应测试。
## 2026-08-24 —— 增加宝可梦红 knowledge 主题与短程任务
**改了什么**：新增门与地图切换、NPC 对话、战斗确认、移动阻挡四个 knowledge 文件，并将 knowledge 短程任务扩展为五个主题任务。
**为什么这么改**：这些经验是跨坐标、可在单帧证据上验证、且会直接改变动作策略的宝可梦红通用规则，适合测试 semantic knowledge 召回。
**取舍**：暂不加入道具菜单、属性克制等需要更复杂起点和判定器的主题，先保证任务能在当前 harness 中解释成功或失败。
**影响面**：新增 semantic knowledge 内容；`knowledge_recall_tasks()` 返回的任务数量从三项扩展为五项。
## 2026-08-24 —— 扩展到十个常见短场景并记录起点要求
**改了什么**：为 `Task` 增加 `initial_state_hint`，将 knowledge 短程任务扩展到十个，并新增道具拾取、菜单选项、商店/宝可梦中心知识。
**为什么这么改**：任务不仅需要目标和成功判据，还必须告诉实验采集者应该准备什么起点 state；十个短场景覆盖野外、室内、对话、选择、菜单、商店和战斗等常见状态。
**取舍**：state hint 是人工采集说明，不进入 agent prompt，也不假装由代码自动验证地图坐标。
**影响面**：Task schema 向后兼容；`knowledge_recall_tasks()` 现在返回十个任务。
## 2026-08-24 —— 细分战斗与商店短场景
**改了什么**：新增战斗行动、招式选择、宝可梦切换、道具使用、逃跑，以及商店购买菜单、选商品、确认购买、取消购买九个任务；新增 `battle_actions.md` 与 `shop_purchase.md`。
**为什么这么改**：战斗和购买不是单一场景，而是多个有不同动作空间和成功证据的状态转移；拆开后每个 state 才能独立采集、独立统计。
**取舍**：购买任务要求准备足够金钱或专门的买不起商品 state；战斗任务不要求一定获胜，重点测行动分支的 knowledge 召回。
**影响面**：knowledge 短程任务从十个扩展到十九个。
## 2026-08-24 —— 将 knowledge 任务调整为 5-15 步微任务
**改了什么**：重写过于单步的目标，使门、对话、菜单、战斗和购买任务包含移动、读取、选择、确认或返回等连续环节；默认步数上限调整为 15。
**为什么这么改**：单次打开菜单或一次确认不能检验 knowledge 是否改善了短程规划；实验需要观察 5-15 步内的连续策略。
**取舍**：5-15 步是自然完成区间而非硬性延迟条件，不强行让 agent 为凑步数执行无意义动作。
**影响面**：`knowledge_recall_tasks()` 默认 `max_steps` 从 12 改为 15，state 采集应把起点放在目标前的准备位置。
## 2026-08-24 —— 增加捕捉与宝可梦中心场景
**改了什么**：删除重复的战斗确认任务；新增削弱目标、投掷精灵球、确认捕捉结果、进入宝可梦中心、完成治疗、离开中心六个任务，并增加对应 knowledge。
**为什么这么改**：捕捉和治疗是宝可梦红最常见的核心循环，且每个流程都包含不同的状态和成功证据，不能由普通战斗或进门任务代替。
**取舍**：捕捉任务需要准备有精灵球和可控伤害的战斗 state；治疗任务需要准备至少一只受伤宝可梦。
**影响面**：knowledge 短程任务现在覆盖战斗、捕捉、购物、治疗和地图交互等核心流程。
## 2026-08-24 —— 按现有 state 提供实验入口
**改了什么**：允许 `experiment/run_episode.py` 作为真正的短程入口；新增 `experiment/run_experiment.py`，按任务类别选择现有 `rom_field.state`、`rom_fight.state`、`rom_indoor.state` 或 `rom.state`，自动生成 manifest 并运行任务。
**为什么这么改**：实验必须基于仓库当前真实存在的 state，不能要求尚未采集的专用 state 才能启动。
**取舍**：当前多个任务共享同一个基础 state，state hint 仍用于后续判断是否需要更精确的采集版；本入口先运行一个 episode，不伪装成批量统计器。
**影响面**：新增可执行实验入口；短程入口不再要求外部预设 `CLAUDE_RUN_ID`。
## 2026-08-24 —— 以 experiment_states/knowledge 为唯一 task 输入
**改了什么**：将 knowledge task catalog 限定为当前已有的 19 个 state，并让实验入口按完全相同的 task id 从 `pokemon_agent/experiment/experiment_states/knowledge/` 加载 state。
**为什么这么改**：实验任务必须和实际可复现的起点一一对应，不能再用 assets 下的基础 state 猜测替代。
**取舍**：没有对应 state 的菜单、选项和捕捉结果任务暂不进入当前 catalog，待 state 收集后再加入。
**影响面**：knowledge task 数量从 24 调整为当前 state 文件对应的 19 个；`run_experiment.py` 不再读取 `assets/rom_*.state`。
## 2026-08-24 —— knowledge 实验默认按运行时间生成 run_id
**改了什么**：`run_experiment.py` 在未传 `--run-id` 时按时间加随机短后缀生成 run_id。
**为什么这么改**：task_id 用于任务归类，run_id 用于区分每次实际运行；同一 task 的重复实验必须拥有独立数据目录。
**取舍**：需要复现实验或手动归档时可通过 `--run-id` 指定固定名称。
**影响面**：默认数据目录恢复为每次运行独立的 `trace_data/<timestamp>-<suffix>/`。
## 2026-08-24 —— 记录 provider manifest 并按 task_id 聚合成功率
**改了什么**：为本地 embedding/reranker 增加 config；实验 manifest 写入 vision/text/judge/embedding/reranker 配置；新增 `trace_data/task_stats/<task_id>.json` 聚合多次 run 的尝试数、成功数和成功率。
**为什么这么改**：run_id 区分一次运行，task_id 才是实验统计单位；两者不能混用。
**取舍**：聚合文件先采用简单 JSON 累积，后续再从 trace 离线重建以增强抗中断能力。
**影响面**：每次 `run_experiment` 完成后更新对应 task 的统计文件。
## 2026-08-24 —— 将实验元数据与统计移出 trace_data
**改了什么**：manifest 改存到 `experiment_results/<run_id>/manifest.json`，按 task_id 的聚合统计改存到 `experiment_results/task_stats/<task_id>.json`。
**为什么这么改**：trace_data 只表达逐事件事实流和 episode 起点；实验条件与统计结果属于实验产物，不能混入 trace 存储。
**取舍**：episode JSONL 和起点 state 仍留在 trace_data，便于 replay；manifest 与统计通过 run_id/task_id 关联，不复制事件流。
**影响面**：新运行不再把 manifest 或 task_stats 写入 trace_data。
## 2026-08-24 —— 修复 episode 摘要模板路径
**改了什么**：将 `episode_summarizer.py` 的模板路径改为基于文件绝对位置解析 `pokemon_agent/prompts/episode_summary.md`。
**为什么这么改**：文件从 `memory/` 移到 `memory/episode/` 后，旧的 `..\prompts` 相对层级少了一层，导致实验启动时直接找不到模板。
**取舍**：使用包内文件的绝对解析路径，不依赖当前工作目录。
**影响面**：修复 `run_experiment` 初始化 `MemoryTool` 时的 `FileNotFoundError`。
## 2026-08-24 —— knowledge 召回展示改为文件名
**改了什么**：新增 knowledge 来源文件名追踪；MEMORY_READ 和控制台只展示命中的 `.md` 文件名，不再展示 knowledge 正文或标题摘要。
**为什么这么改**：当前实验只需确认召回了哪份知识文件，正文已经进入 agent prompt，不应在观测台重复输出。
**取舍**：检索正文仍完整传给 agent；展示层和模型上下文保持分离。
**影响面**：新增 `knowledge_sources` trace 字段，控制台和浏览器观测台都只显示文件名；旧 trace 没有该字段时显示为空。
## 2026-08-24 —— 完善观测台状态展示
**改了什么**：浏览器观测台的 observe 事件增加 `scene`、`overlay` 和 `walk_map` 展示；known_object 继续只显示地图与坐标等短定位信息。
**为什么这么改**：这三个字段是判断当前动作空间和路线状态的核心事实，只显示 summary 不足以检查 agent 的决策依据。
**取舍**：不展开 known_object 正文，也不重复显示 knowledge 正文；观测台保持检查用的紧凑格式。
**影响面**：只改浏览器展示，不改变 trace payload 和模型输入。
## 2026-08-24 —— 精简 episode_memory_write 事件
**改了什么**：从 `episode_memory_write` payload 删除 `input_tokens` 和 `output_tokens`。
**为什么这么改**：摘要记忆写入事件只需要记录摘要内容与适用范围，模型调用成本应由独立的模型调用账单事件承担。
**取舍**：历史 JSONL 中已有的 token 字段不回写；新生成事件不再包含它们。
**影响面**：新 trace 的 `episode_memory_write` 只保留 summary、quality_score、applicable_scenes。
## 2026-08-24 —— 将 episode 摘要逐条落盘为 LLM 生成的 Markdown
**改了什么**：恢复摘要事件 token 记录；扩展摘要输出为 LLM 生成的 `filename` 与 `markdown`，每个 episode 单独保存到 `pokemon_agent/memory/episode/memory/`；收紧 `applicable_scenes` 为稳定标签。
**为什么这么改**：当前先保留每局原始摘要，后续可以离线聚类合并；场景标签必须可检索、可比较，不能使用长段自然语言。
**取舍**：文件名冲突时追加 episode_id 保证一局一个文件；程序检索仍使用结构化 EpisodeMemory，Markdown 是落盘归档。
**影响面**：新增摘要文件写入；`episode_memory_write` 同时恢复 input/output token 字段。
## 2026-08-24 —— 让 applicable_scenes 标签参与实际匹配
**改了什么**：`applicable_scenes` 支持 `map:<id>`、`scene:<name>`、`overlay:<name>` 等稳定标签；Harness 查询时传入当前地图、scene 和 overlay 的组合键。
**为什么这么改**：原来模型生成的场景描述即使写进摘要，也无法和查询侧的纯数字 map_id 匹配，导致摘要经验被错误过滤。
**取舍**：保留旧的纯数字 map_id 兼容匹配；新摘要统一使用带前缀标签。
**影响面**：episode 摘要召回的场景过滤更可解释，旧摘要仍可继续使用。
## 2026-08-25 —— 补齐 AgentPermission 运行配置
**改了什么**：为 `player-agent` 增加游戏执行权限，为保存游戏状态增加高风险确认策略；将 `context.json` 改为由 episode 初始化覆盖的运行时模板。
**为什么这么改**：宝可梦 agent 需要读取游戏状态并执行动作，原配置只有读取权限；`context.json` 中固定的 episode 标识会在多 episode session 中失真。
**取舍**：保留 `trusted-agent` 角色和兼容的 `execute:game:save` 策略，不在本次改动中修改库的权限命名协议。
**影响面**：只影响 AgentPermission 的配置加载；尚未接入 Python 装饰器或改变游戏执行代码。

## 2026-08-25 —— 细分 agent 游戏与记忆权限
**改了什么**：把 `player-agent` 从宽泛的 `read:game:*` / `execute:game:*` 拆成观测、动作空间、按键、存档边界以及情景/跨局/对象/知识记忆权限。
**为什么这么改**：权限配置应该反映工具接口的真实能力；通配执行权限会让 agent 无法区分读取、推进世界和写入记忆的风险。
**取舍**：保留 `trusted-agent` 的全量权限作为调试角色；`save`/`save_state` 继续由高风险策略单独控制。
**影响面**：仅修改 `config/permissions.json` 和变更日志，不改变运行代码。

## 2026-08-25 —— 移除未绑定的示例权限
**改了什么**：删除 `agent_permission.examples.pokemon:inspect`。
**为什么这么改**：它指向 AgentPermission 包中的示例函数，不是 `pokemon_agent.tools.game_tools.GameTools.inspect()`；保留它不会给本项目函数增加任何保护，反而会造成权限配置与实际执行路径不一致。
**取舍**：先使用项目自己的资源名，待装饰器接入时再让装饰器声明和配置逐项对齐。
**影响面**：仅影响 `player-agent` 的权限配置，不改变游戏行为。

## 2026-08-25 —— 增加模型调用权限
**改了什么**：为决策模型、目标判定模型、视觉感知模型和跨局记忆摘要模型增加独立的 `execute:llm:*` 权限。
**为什么这么改**：这些调用会产生网络访问和模型成本，且四条链路职责不同；不应让游戏按键权限隐含获得所有模型调用能力。
**取舍**：本地 embedding 和 reranker 暂不归入远程 LLM 权限，因为它们不调用远程模型服务；是否需要单独限制留到接入权限装饰器时再决定。
**影响面**：只修改 AgentPermission 配置，不改变 provider 实现。

## 2026-08-25 —— 将按键权限收敛为 press
**改了什么**：把动态的 `execute:game:button:*` 改为固定的 `execute:game:press`。
**为什么这么改**：项目所有按键都经过 `GameTools.execute(action)` 这一条统一边界；具体按键名已在 `Action.name` 和 `act` trace 事件中记录，不需要把每个按键扩展成权限资源。
**取舍**：权限层只判断“是否允许推进游戏”，不在配置层限制某个具体按键；动作空间和 `execute()` 的现有契约继续负责非法按键拦截。
**影响面**：只修改 AgentPermission 配置；按键级审计仍通过 trace 保留。

## 2026-08-25 —— 完整配置 trusted-agent 权限
**改了什么**：将此前讨论的游戏、LLM、记忆、Harness 和存档权限全部写入 `trusted-agent`。
**为什么这么改**：`trusted-agent` 作为调试和受信任运行角色，应明确拥有项目实际使用的全部能力；逐项列出也便于和装饰器绑定关系对照。
**取舍**：保留存档的高风险确认策略，即使角色拥有对应权限，保存动作仍按策略确认。
**影响面**：只修改 AgentPermission 配置和变更日志，不改变 Python 运行逻辑。
## 2026-08-25 —— 移除 inspect 动作分支
**改了什么**：从 `GameToolPort`、`GameTools`、`Action.Intent` 和 Harness 图中移除 `inspect` 函数与 `INSPECT` 节点，并删除对应权限；解析器不再接受 `inspect` 动作。
**为什么这么改**：当前原型只保留常规观测和按键推进，细查会引入额外视觉调用、动作分支和同帧状态，超出本阶段最小闭环。
**取舍**：底层 `WorldPort.inspect()` 及相关历史测试/展示代码暂未删除，避免把世界实现和 trace 兼容清理扩大到本次接口变更之外；它们已不再从 Harness 工具路径可达。
**影响面**：Brain 可选动作从 `PRESS/PUSH_GOAL/INSPECT` 收敛为 `PRESS/PUSH_GOAL`；现有依赖 inspect 的旧测试需要同步移除或改写。
## 2026-08-25 —— 收敛 MemoryTool 公开接口
**改了什么**：将单步记忆、跨局摘要、对象记忆和知识检索改为统一的 `query_*` / `store_*` 命名；知识查询改为一次返回内容与来源；移除每帧 `see_objects()` 登记路径。
**为什么这么改**：旧接口混用了 `query`、`recent`、`write`、`note`、`known` 等动词，且知识内容与来源分别检索，无法保证属于同一次命中结果；每帧登记对象也和观察数据重复。
**取舍**：不保留旧方法别名，强制调用方迁移到新契约；`store_episode_summary()` 暂时同时负责摘要生成和保存，因为当前没有独立保存已生成摘要的调用场景。
**影响面**：修改 `MemoryToolPort`、`MemoryTool` 和 Harness 记忆节点；旧测试与文档引用需要同步迁移。

## 2026-08-25 —— 删除旧 MemoryTool 与 inspect 测试
**改了什么**：删除直接依赖旧 MemoryTool 方法名和 `inspect` 图分支的 `test_memory.py`、`test_episode_memory.py`、`test_poses.py`、`test_goals.py`、`test_subgoals.py`。
**为什么这么改**：这些测试验证的接口已经被本次设计收敛移除，继续保留会把旧契约伪装成当前行为。
**取舍**：保留未直接依赖旧接口的世界、提示词、检索和判定测试；新 MemoryTool 契约测试后续按新接口补回。
**影响面**：删除 5 个旧测试文件，不改变生产代码。
## 2026-08-25 —— 收敛为单角色完整权限边界
**改了什么**：将 `trusted-agent` 定义为 Brain + Harness 的统一角色；为所有 `GameToolPort` / `MemoryToolPort` 公开能力配置权限，并加入 `Brain.reflect()` 未来 LLM 修饰所需的 `execute:llm:memory_reflection`。
**为什么这么改**：当前权限系统只支持单角色，继续拆分角色只会制造无法执行的配置复杂度；工具能力和 Brain 直接发起的模型调用是两条清晰的权限边界。
**取舍**：保留 `last_frame_sha` 和 trace 权限作为工具/运行审计能力；删除不存在的 `execute:game:save` 以及不属于工具接口的 Harness 生命周期权限。
**影响面**：只修改 AgentPermission 配置和变更日志，不改变 Brain/Harness 运行逻辑。
## 2026-08-25 —— 接入 AgentPermission 装饰器
**改了什么**：在 `Brain`、`GameTools`、`MemoryTool` 和 `Harness.run()` 的具体实现方法上加入显式权限装饰器；将运行时 context 角色切换为 `trusted-agent`。
**为什么这么改**：权限系统实际检查的是被调用的具体函数，接口声明不会自动继承装饰器；在实现边界执行检查才能阻止未授权调用真正发生。
**取舍**：`Harness.run()` 负责 episode 开始时执行 `initialize`；多权限方法使用多个装饰器逐项检查；`Brain.reflect()` 当前仍是本地逻辑，但预先纳入记忆反思权限以约束未来 LLM 化。
**影响面**：受保护函数在权限上下文未初始化、权限不足或审批拒绝时不会执行；配置和运行 context 已同步更新。
## 2026-08-25 —— 明确无权限错误处理
**改了什么**：Harness 对 `PermissionDenied`、`ApprovalExpired` 和 `ApprovalRejected` 增加显式捕获并写入 episode error trace；移除 `Harness.run()` 自身的 trace 权限门。
**为什么这么改**：权限拒绝是预期内的运行时失败，不应重试或静默吞掉；如果先拦截 `Harness.run()`，连拒绝事件都无法写入 trace。
**取舍**：记录后继续向上抛出，让 episode 调用方决定结束或展示错误；不把权限失败伪装成模型解析失败或非法动作。
**影响面**：只改变权限错误的记录与传播方式，不改变允许调用的执行路径。
