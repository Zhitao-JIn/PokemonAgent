## 2026-09-16（140）—— 采集脚本扩容 RAM 字段 + 新增 id→文本解码脚本

**改了什么**：`capture_manual_play.py` 的 RAM 字段从 5 个（map_id/坐标/朝向/
walk_map）扩到 15 个——新增 `tileset_id`、`party_size`/`party_species`/
`party_levels`/`party_hp`/`party_max_hp`（各 6 槽）、`opponent_levels`（6 槽，
非零即"这一帧大概率在战斗"的信号，不下结论）、`badge_count`/`badge_bitmask`、
`money`。新增 `experiment/observation_check/decode_ids.py` + `id_tables/`
（species/items/moves/maps/tilesets 五张 json 表），把 manifest 里的数字 id
翻成文本，`python -m experiment.observation_check.decode_ids <manifest.jsonl>`
读一份 manifest、逐行加 `*_name` 字段、写到旁边的 `.decoded.jsonl`，不碰原文件。

**为什么这么改**：能拿的免费 RAM ground truth 不该只拿 5 个——上一版只顺手记了
`ram.py` 原有的那几项，实际上党内数据（等级/HP/金钱/徽章/tileset）同样是
"确定、不会读错"的那一类，多留一份不吃亏，standing 越广，后面挑分层抽样的
素材时可选的维度越多。id→文本单独成一个脚本（不揉进采集脚本）：采集时不该
依赖任何 id 表，跑得快、以后表要更新也不用碰采集逻辑。

**取舍**：新增地址**不是凭记忆写的**——从 `pret/pokered` 反汇编仓库的
`ram/wram.asm` 取字段名和相对顺序，具体十六进制地址交叉核对
`PWhiddy/PokemonRedExperiments`（一个被广泛使用的 Pokémon Red 强化学习项目）
的 `baselines/memory_addresses.py`，两个来源在 `wPartyCount`(0xD163)/
`wYCoord`(0xD361)/`wXCoord`(0xD362)/`wCurMap`(0xD35E) 上逐字对得上才采用。
唯一例外是 `CUR_MAP_TILESET`(0xD367)——这个是从 `wCurMap` 往后数字节偏移
推算出来的，没有第二个独立来源交叉验证，标注在两个脚本的 docstring 里，
建议采集后挑几帧现场核对。id 表本身也有已知不完整的地方：species 只到 154
号（155~189 是无官方常量名的残留槽位，查不到给 None，不瞎编）；map 表给的
是符号常量名（如 `ROUTE_1`），不是画面上那行确切文本。

**影响面**：只改 `experiment/observation_check/` 这个新包内部，不动任何
`pokemon_agent/` 下的接口；`decode_ids.py` 是新文件，`capture_manual_play.py`
是在制品阶段的自我修改（还没有人跑过产出数据，不存在旧格式 manifest 需要
迁移）。

## 2026-09-16（139）—— 新增 observation 准确性评测的独立工具包 + 人工采集脚本

**改了什么**：新增 `experiment/observation_check/` 包（`__init__.py` 说明与
`real_check/` 的边界），以及 `capture_manual_play.py`——从 ROM 开机（不加载
存档）、开一个真实可操作的 SDL2 窗口，每隔 `--interval`（缺省 2s）秒截一帧
画面存 PNG，同时用 `ram.read_terrain` 顺手记一份 map_id/坐标/朝向/地形图
落进 `manifest.jsonl`，scene/overlay/dialog_text/overview 等视觉字段先留空
等人工标注。

**为什么这么改**：`real_check/` 核的是链路结构对不对，明确不核 observation
里视觉字段的内容准不准（见 `docs/spec/experiment/SPEC.md` 第三节"能证/不能证"
那条边界）。现成的 20 个 `knowledge_*.state` 覆盖不够（无 `Scene.MENU`、每景
单帧、且很可能是当初调 prompt 时用来验收的样本，拿来测准确率有过拟合嫌疑），
所以需要一批独立于 20 个存档、覆盖更广的真实素材，第一步是人工玩一遍、
定时截图攒原始帧。

**取舍**：刻意不复用 `PyBoyWorld`（它构造时强制 `no_input=True` 防误触，
正好是这里要反过来的那一件事），直接用 `pyboy.PyBoy` + 借
`world/ram.py::read_terrain` 一个纯函数，不牵连视觉 provider / harness /
trace 任何一层。RAM 读取失败（开机动画等过场）不让整个采集会话崩掉，
该帧 RAM 字段记 `None`，采集继续。

**影响面**：新增，不动任何已有接口；`experiment/observation_check/` 是全新
独立包，不进 `real_check/` 的四个维度。

## 2026-09-16（139）—— trace 写口统一：删 `append_model_calls`，调用账一律 `append(calls=…)`

**改了什么**：调用账的两种写法并存（成功路径 `append(calls=…)` 一次交齐 / 失败路径
`append_model_calls` 逐条拆）→ **统一为前者，批量口整个删除**。

- **harness 七处调用点改形**：`think_action`（成功 + 失败）、`perceive_after_action`
  （成功 + 失败）、`judge._ask_judge`、`verify_and_summarize._report_link_failed`、
  `extract_knowledge._report_link_failed`——一律
  `append(kind=…, calls=list(…))`，`calls` 交**整条重试链**（`resp.calls` /
  `exc.calls`）。感知的空账（`ram_only` 的 `log=[]`）改为**调用方不写**。
- **删三件**：`tools/trace/model_calls.py`、`TraceToolPort.append_model_calls`
  （协议方法）、`schemas/harness/communication/FromHarnessToTraceToolAppendModelCallsReq.py`
  （批量信封）。`ModelCallLog`（`list[ModelCall]` 别名，`perceive_with_retry`
  的返回类型还在用）搬进 `communication/ModelCall.py`。
- **同步**：harness/tools/schemas 四层 docstring、四份活文档（`docs/spec/`
  的 tools / trace-API / harness / schemas）、两处测试
  （`test_extract_knowledge` 的 fake、`test_trace_store` 的拆账用例改走 `append`）。

**为什么这么改**：两套形状落盘效果**完全相同**——`render.model_call` 本来就对
`req.calls` 逐条摊（每条尝试一条 `*_call`、失败补 `call_failed`），
`append_model_calls` 只是把同样的拆分提前到 tool 层做了一遍。用户定调
「只要有发送就有账，每次尝试单独成账，全部统一」。真正的差别只剩一处：
**空账合法性**（批量口对空 `log` 合法、`append` 撞 `assert req.calls`）——
它只服务 `ram_only` 感知一个场景，改成调用方判断"没发送就不写"更直白：
`append` 的前置条件从此就是「有账才写」。

**取舍**：感知成功路径因此多了一个 `if log:` 守卫（全仓唯一一处空账可能）；
`PLAN_CALL` 仍无写点（`BrainPlanner` 只填 `input/output`，不变）。
顺带归零了四文件 `ruff format` 偏差与两处 tests 的 E402/F401（皆非本次逻辑
引入，`judge.py` 的 `verdict_req` 收行等）。

**影响面**：行为不变的只有「有重试的成功路径」——此前它经
`append_model_calls` 逐条 `append`，现在一次 `append` 交整条链，渲染层
摊出的**事件序列与内容逐字相同**（`_RENDERERS` 分派与 `model_call` 渲染
都没动）。唯一语义变化是 `TraceToolPort` 少一个方法、`schemas.harness`
少一个信封出口。验证：pytest **127 条全过**、ruff check + format
（`pokemon_agent` / `tests` / `scripts`）全绿、`check_trace_self_contained.py`
A/B/C 全过。

## 2026-09-16（138）—— 清掉调用账信封里残留的 `attempt` 说法，写清 N 是尝试次数

**改了什么**：`schemas/harness/communication/FromHarnessToTraceToolAppendModelCallsReq.py`
四处措辞——① 模块 docstring 的"拆的规则（**每条带自己的 `attempt`**）住在 tool 层"
改为"拆的规则住在 tool 层"；② 同段的"重试循环（**决策 / 感知 / 规划三处**）"改为
"（`BrainTool._attempt_loop` 的六条链路，以及 `GameTools.perceive_with_retry`）"；
③ `ModelCallLog` 的"按 `attempt` 升序：`list[(attempt, ModelCall)]`"改为
"按尝试先后排列：`list[ModelCall]`"；④ 「`ModelCallLog` 为什么定义在本文件里」
那段里的"**三个**攒账的重试循环"改为"两个"。另**新增一段**写明"`N = 尝试次数`"。

**为什么这么改**：`attempt` 这枚戳 0914 就跟 `with_attempt()` 一起删了（现由账在
链上的位置回答"第几次"），`ModelCallLog` 从来就只是 `list[ModelCall]`——这几处都是
**指向已不存在之物的说法**；"三处循环"同理，循环早已并成两个（`_attempt_loop`
一个覆盖六条链、`perceive_with_retry` 一个）。数量那处是同日查账的副产品：provider
层的 `max_attempts` 删掉（0915）之后容易读成"一次交互就一条账"，而循环仍在 tool 层
攒整条链，`log` 的长度是 1..3。信封是这类误解的第一现场，所以在那里把两件事分开
写明：**一次尝试恰好一条账**（账不虚增），**一次交互 N 条**（N = 尝试次数）。

**取舍**：只在信封 docstring 里补，没有去 `model_calls.py` / `ports.py` 那几处
"N 次尝试 → N 条调用账"旁边再加一遍——它们本来就对，重复表述会多出几个将来要
同步的地方。

**影响面**：纯 docstring，**零行为变化**。验证：`pytest tests/` 127 条全过
（复跑一次同样全绿）、ruff check + format 该文件过。

## 2026-09-16（137）—— 拆掉"契约层 import trace 会成环"这条过期断言（6 处）

**改了什么**："`schemas/harness/domain` import `pokemon_agent.trace` ⇒ 成环 ⇒
`ImportError: partially initialized module`"这个说法散在 **6 个活的地方**——3 处代码
docstring（`domain/__init__.py` / `domain/trace_event.py` / `scripts/check_trace_self_contained.py`）
与 3 处活文档（`docs/spec/schemas/SPEC.md` / `docs/spec/trace/SPEC.md` /
`docs/spec/trace/API.md`），全部改成"守**分层方向**，不是防环"。自包含脚本的 C 项
随之改名：`schemas/harness/domain 不成环` → `契约层不依赖实现包`
（`_check_c` 的 docstring 与 `CHECKS` 表同步）。

**为什么这么改**：那条环属于 0913 脱钩**之前**的形状——当时 `trace/store.py`
确实 import `schemas.harness.domain`（为了 `TraceEvent`），`PLAN_trace_decoupling.md` §3
记着 v1 实测复现的完整链条与报错原文。脱钩把 store 换成自带的 `_Event` 之后**那条边
就不存在了**；A 项（`trace/` 出边为零）既然成立，任何 `X → trace` 的边都构不成回环，
"成环"这个理由在今天的代码上**站不住**。这不是推理——实测过：把
`import pokemon_agent.trace` 临时加回 `domain/trace_event.py`，四种加载顺序
（契约层先进 / trace 先进 / `build` / `harness`）**全都不炸**（测完逐字撤销，
A/B/C 复核仍全过）。

**取舍**：C 项**保留**——它指向的约束仍然真实（契约层不许反向依赖实现包），只是
理由从"防环"降级为"分层方向 + 前瞻"：A 将来若被破坏，别让环跟着一起被破出来。
它本来就是 B 的真子集（脚本 docstring 自己写着"B 已涵盖 C"），单列的价值只在失败
信息的指向性，这一点没变。历史叙述留在 `PLAN_trace_decoupling.md` 与
`docs/experiences/` 的**历史档**里照旧不改写。

**影响面**：纯 docstring 与文档，**零行为变化**。验证：`check_trace_self_contained.py`
A/B/C 全过（C 项新名字的打印读得通）、`pytest tests/` 127 条全过、ruff check + format
三处改动文件全过。

## 2026-09-16（136）—— memory 命名规范化、包出口收窄、restore 改为以 zip 为准

**改了什么**：三件事，都是围着"memory 这块第三方模块的边界面"做的。

**① 类型命名与 `trace/` 同形**：协议带 `Port` 后缀、本包自带的实现带 `Local`
前缀——`EmbeddingProvider` → `EmbeddingProviderPort`、`RerankerProvider` →
`RerankerProviderPort`、`FastEmbedText` → `LocalEmbeddingProvider`、
`FastEmbedReranker` → `LocalRerankerProvider`、`MemoryStore` →
`LocalMemoryStore`（对应 `trace/` 已有的 `TracePort` / `LocalTrace`）。
全仓 21 个文件批量正则替换（包内 8 个源文件 + `tools/` 两处 + `build.py` +
`trace/store.py` 注释 + schemas 注释 + `experiment/real_check/` 两处 + tests +
五份 spec + `AGENTS.md`）。

**② 包出口从 12 个名字收窄到 6 个**：`memory/__init__.py` 的 `__all__` 只留
3 协议 + 3 实现；摘掉 `tokenize` / `bm25_rank` / `embedding_rank` /
`reciprocal_rank_fusion` / `hybrid_retrieve` 五个检索纯函数与
`SNAPSHOTS_DIRNAME` 常量。函数本身还在 `retrieval.py` / `store.py` 里，
`LocalMemoryStore.search` / `rank` 照常串联调用，单测就地深 import。

**③ `restore` 语义从"覆盖（原样留着）"改成"以 zip 为准"**：zip 里有的记录
按 zip 写（同名直接盖），**zip 里没有的记录文件从库里删掉**——"恢复到某个
存档"就一个意思，没有"只加不减"的另一半入口。`snapshots/` 子目录不受影响
（存档 zip 自己不被还原动掉）。改动面：`store.py::restore`（解包前扫四个
kind 目录、把 zip 清单里没有的记录 unlink）、`memory/ports.py` 与
`tools/interface/ports.py` 的契约 docstring、`restore_memory` 的 Resp 措辞、
两个信封的 docstring、`tests/test_memory_store.py` 两条断言翻转 + 新增
"snapshots/ 不被还原动到"一条、`check_memory_roundtrip.py` 路径 7 的断言
翻转（后写那条**被删掉**才算过）。

**为什么这么改**：①是用户口径——"像这种应该规范一下名称"，同一套协议/
实现命名规矩在 `trace/` 已经立住了，memory 没理由各叫各的；名字里挤着具体
技术（FastEmbed）还堵死了将来换远程实现的路。②的判据是**引用面**：五个
检索函数全仓零仓外消费方（`grep` 复核只有 `store.py` 在用），`search` /
`rank` 已经是"要排序"的唯一正门；把内部实现细节摆进 `__all__` 等于把
"BM25 + RRF + reranker"这条流水线也变成对外承诺，将来想换检索算法就得
背兼容。③同样是用户口径——"其实 restore 就是删掉库里多出来的那些"：
"覆盖但留着多出来的"本来就是个四不像语义，叫"恢复"却不恢复干净。

**取舍**：① `SNAPSHOTS_DIRNAME` 一并摘出口——"快照放哪"是实现细节，
消费方依赖它就等于把 `snapshots/` 目录名焊死在契约上；真要看 zip 落哪，
`snapshot_memory` 的 Resp 里带的是**返回的路径**，不需要常量。② restore
删记录的判据是**zip 清单**（`infolist()` 里 `<kind>/<file>` 形状的条目），
不是"先清空根再解包"——后者会把 `index.json` / `vectors.jsonl` 也删了再
整体重建，动静大且失败窗口宽；前者只动"库里有、zip 里没有"的记录文件，
派生物交给既有的 `_load_or_rebuild()` 对账。③ "只补几份、保留库里其他"
的合并语义**不提供**——那不是恢复，是导入；真要合并在库上自己写。

**影响面**：全仓 `FastEmbedText` / `FastEmbedReranker` / `MemoryStore`（裸名）
/ `EmbeddingProvider` / `RerankerProvider`（裸名）**零残余**（grep 复核，
spec 与代码一致）；`import pokemon_agent.memory` 的公开面从 12 → 6，无仓外
消费方受影响（被摘的名字全仓零引用）；`check_memory_roundtrip` 七条路径
全 PASS（快照路径翻成"以 zip 为准"口径后 8 秒跑完）。spec 四份同步：
`memory/PORTS.md`（§5 出口重写、restore 契约、§6 标题加"不在包出口上"）、
`memory/SPEC.md`（出口计数、检索函数加"不在出口上"注记）、
`memory/API.md`（出口表重写、restore 详述、用法示例、测试清单、约束一节）、
`tools/SPEC.md`（快照两方法措辞）。

## 2026-09-16（135）—— trace 落盘平铺、读口改 meta 交集匹配、落盘根改名 tracelog

**改了什么**：三件事一起做，因为它们是同一个决定的三个面。

**① 落盘从 `<落盘根>/<run_id>/events/<uuid>.json` 平铺成 `<落盘根>/<uuid>.json`**：
`LocalTrace` 的 `_run_dir` / `_events_dir` 两个属性收成一个 `_dir`；构造时只建
**一层**目录；`run_id` **不再参与路径**，只由 `_stamp_run_id` 盖进 `meta`。

**② `TracePort.read_events(episode_id: str | None)` 换成 `read_events(meta: dict |
None)`**：筛选语义从"单维相等"升级成 **AND-of-equalities**（给的每个键都要相等，
取交集；`None`/`{}` = 整个落盘根），与 `MemoryStorePort.filter` 同一条。新增内部
`_meta_of()`（解不动给空 dict，于是读不动的文件不匹配任何条件）与 `_matches()`。
下游整条链跟着改签名：`TraceTool.read_events`、`TraceToolPort.read_events`、
`RunHarness.read_events`（薄委托）、`review` 节点（改成
`deps.trace.read_events({"run_id": deps.run_id, "episode_id": state.episode_id})`
——平铺后不带 `run_id` 会读到别的 run 的事件，`HarnessDeps.run_id` 正是为此取的）。
`review.py` 里那个"先装完整 trace 再按局筛"的 `episode_trace_events()` 随之删掉。

**③ 缺省落盘根 `trace_data/` 改名 `tracelog/`**（`trace/store._default_root`、
`common.TRACE_ROOT`、`build.py` / `build/SPEC.md` / 起跑脚本的注释一处不落）。

**核对侧**（`experiment/real_check/`）改写三处：`load_events(run_id)` 改成"扫落盘根
→ 按 `meta.run_id` 过滤"；新增 `event_files(root)` 定义"什么是事件文件"（第一层
`*.json`，**点开头的除外**——`.last_realcheck.json` 这个 run 指针平铺后与事件同住
一层，`glob("*.json")` 会把它捞出来）；`resolve_run` 的**回退扫描整段重写**——没有
run 目录可认了，改成扫全部事件、按 `meta.run_id` 分组（只认 `realcheck-` /
`restorecheck-` 前缀）、按 `_recency()` 取最新。`_recency()` 返回
`(最大 ts, 最大 uuid)` 而不是只返回 `ts`。`check_memory_roundtrip.py` 的临时目录从
`trace_data/<eid>` / `tracelog/<eid>` 挪到 `.memcheck/<eid>`（它压根不碰 trace，
不该借 trace 的名字当场地）。

**为什么这么改**：用户三条口径。① "落盘路径不需要多层文件夹，就在下面就行了"
——`<run_id>/events/` 两层是照搬"一个 run 一个目录"的直觉，而 `memory/` 早就是
"**不按 run 分层、run_id 在记录 metadata 里**"（`common.MEMORY_ROOT` 的注释写着
这句）；trace 是同一族的独立模块，没有理由用另一条规矩。② "`episode_id` 应该换成
一个 meta dict 做交集匹配"——单维切片一次只能问一个问题（"哪一局"），而"哪个 run
的哪一步哪个位置"是常态；交集匹配让读口只留一个参数、语义与记忆侧对齐。
③ 改名是因为 `trace_data` 这个名字在平铺之后会误导人——它不再是"trace 的数据目录
树"，就是一堆事件文件；`tracelog` 更贴近它现在的样子。

**取舍**：① 平铺换掉了"路径天然保证 run 边界"这条免费的不变式——`read_events()`
不带条件现在会读到**别的 run 的事件**，想只要自己那一批必须显式筛
`{"run_id": …}`；`review` 节点就踩在这条上，所以它那一处必须传 `run_id`。
② `resolve_run` 的回退扫描从"看目录名 + mtime"变成"**读全目录按事件内容分组**"，
比原来贵（要解析每一个事件文件），换来的是会话重启丢了指针之后仍能定位到产物。
③ `_recency()` 加 uuid 兜底这一位是被实测逼出来的：第一版只比 `ts`，探针跑第一遍
就翻车——两个 run 的事件落在同一刻时 `sorted` 退回字典插入序，把先扫到的那个当成
"最新"。补 `uuid` 之后比较恢复全序。但**换来的只是"确定"，不是"更准"**：Windows
的 `time.time()` 实测只有 ~15.6 ms 的更新步长，背靠背写的两个 run 会共用同一个
`ts`，而 v7 uuid 在同毫秒内的随机段并不跟写入先后走——真打平时赢家任意但固定。
所以探针里"取最新的那个 run"那条改成先把夹具的 `ts` 摊平到可分（测的是判据，不是
时钟），另加一条钉"打平时换落盘顺序答案不变"（测的是比较有全序）。④ `event_files()`
把"点开头的不算事件"这条规矩收成一处，两个读者共用；这是平铺的连带成本，不写下来
下一个人必踩。

**影响面**：`pokemon_agent/trace/{store,__init__}.py`、
`trace/interface/{trace_port,event}.py`、`tools/trace/__init__.py`、
`tools/interface/ports.py`、`harness/run/harness.py`、
`harness/run/nodes/review.py`、`build.py`；`experiment/real_check/` 四个脚本；
`tests/` 六个文件（路径断言、两个假 trace 实现的签名、`test_frame_slot.py` 一个
死参数）。验证：`tests/` 全量 **127 条全过**（`python -m pytest tests/` 口径，
连跑 12 次稳定）、`check_trace_self_contained.py` A/B/C 三项全过、
行为探针 25 条全过（含 `check_trace` 端到端、`resolve_run` 的打平兜底、
与"半截 JSON 必须被逮住"）。
活文档同步：`AGENTS.md` 九、（`CLAUDE.md` 镜像走 `sync_claude_md.py`）、
`docs/spec/` 下的 `trace/API.md`、`trace/SPEC.md`、`tools/SPEC.md`、
`experiment/SPEC.md`、`memory/API.md`、`build/SPEC.md`、
`TRACE_37_accounts_examples.md`。顺带修掉 `experiment/SPEC.md` 里更早的一处漂移：
它还在描述 `--step-root` / `--object-root` / `--episode-root` / `--knowledge-root`
四个开关（四族共用 `--memory-root` 一个之后，这四个就不存在了）。

## 2026-09-16（134）—— 新增 trace 模块 API 接口文档

**改了什么**：新增 `docs/spec/trace/API.md`，一份面向"要调这个模块"的接口参考：
五个出口名字、`TracePort` 两个方法的完整签名/参数表/前置-后置条件/失败模式、
`Event` 协议六属性与三处形状对齐、落盘路径与盘上真实 JSON 样例、
`meta` 四键与 `EventType` 七类、`LocalTrace` 构造与落盘根覆盖链、
tool 层 `TraceTool` 的四个方法及它多出来的五条 assert、三步最小用法示例、
三套核对（自包含脚本 / 单元测试 / 真机维度 2）怎么跑。
同批更新 `docs/spec/README.md` 的文件一览表，登记新文件与它的更新触发条件。

**为什么这么改**：`trace/SPEC.md` 讲的是**边界与全貌**（为什么这么设计、谁认识谁），
`memory/` 下早有 `SPEC.md` + `PORTS.md` 的分工先例（一份讲全貌、一份讲契约）。
trace 缺的正是"契约那一份"——想调用它的人需要的是签名、前置条件、出错什么样、
盘上产物长什么样，这些散在 `trace_port.py` 的 docstring、`store.py` 的注释、
`check_trace.py` 的断言和 `test_trace_store.py` 的示范里，没有一处集中可读。

**取舍**：写成并列的第二份文件而不是把 `SPEC.md` 拆开——两者读者不同，
`SPEC.md` 的读者是"要改 trace 的人"，`API.md` 的读者是"要用 trace 的人"，
拆开各自能一口气读完；代价是同一条事实有两处描述，改签名时两份都要动，
所以在 `README.md` 的触发条件里写明了"改方法签名、改缺省值、改前置条件、改核对入口"
该动 `API.md`。文中**不重复** `DATAFLOW.md` 的事件总表，改为指过去。

**影响面**：纯文档，零代码改动。顺带修掉 `docs/spec/trace/SPEC.md`
「发现的不一致」第 1 条——它说 `docs/spec/DATAFLOW.md` 不存在，而该文件
0915 就已重建（15 KB，`docs/spec/README.md` 与 `AGENTS.md` 九、都引它当事件总表），
这条过期的"不存在"判断已删。

## 2026-09-16（133）—— trace / memory 落盘根改为启动时指定；memory 归档换成 zip 快照

**改了什么**：两件事，一件是"数据落在哪"，一件是"怎么存档"。

**① 落盘根从"代码住在哪"改成"启动时指定"。** `trace/store.py` 删掉
`Path(__file__)` 回溯仓库根的 `STORAGE_ROOT`，`memory/store.py` 与
`tools/memory_tool.py` 删掉各自的 `_PROJECT_ROOT`——缺省根统一改为**进程启动
目录**（`Path.cwd()`）下的 `trace_data/` 与 `memory/`。覆盖链逐级打通：
`build_real(trace_root=…, memory_root=…)` → `TraceTool.build(trace_root=…)` /
`MemoryTool.build(memory_root=…)` → 各 store 的 `root`。起跑脚本
`check_harness.py` 新增 `--trace-root PATH` 与 `--memory-root PATH`，写方与
跑完的核对读法同源；`check_trace.py` / `check_memory.py` 也认这两个开关
（读产物跟着写方走）。解析器 `_arg` 上收为 `common.flag_value()` 一份实现
三家共用；`common.py` 的 `memory_dir(kind, memory_root=None)` /
`read_memory_files(kind)` 都收可选 root，`LAST_RUN` 常量随之删除（指针路径由
函数按根现算）。

**② 归档整个删掉，换成 zip 快照 + 覆盖恢复。** `MemoryStore.archive_many()`
（把记录搬进 `voided-<ts>/<kind>/` 留档）改写成 `delete_many()`——**直接删**，
让记录消失只有这一条路；容量淘汰（`_trim_summaries`）改调它。新开一对方法：
`snapshot(name) -> Path` 把**整个记忆根**用 `shutil.make_archive` 打成
`<根>/snapshots/<name>.zip`（打包时把 `snapshots/` 自己剔掉，否则快照自我
嵌套），`restore(archive) -> int` 把一个 zip **覆盖**回根里（只认
`<kind>/<file>` 两层路径，防目录穿越）。tool 层开两个口：
`MemoryTool.snapshot_memory(req{name})` → `resp{archive}`、
`restore_memory(req{archive})` → `resp{unpacked}`，配套四个信封进
`schemas/harness/communication/`，两层 Port（`MemoryStorePort` /
`MemoryToolPort`）各加这两个方法。`_load_vectors` 顺带按活着的 uuid 过滤
（删掉的记录其向量行自然丢弃，不必为派生的 sidecar 设计压实策略）。

**为什么这么改**：落盘根原来锚在"代码住在哪"上——`__file__` 回溯三层得到
仓库根，启动目录换到别处数据仍塞进仓库。对 trace / memory 两个独立第三方
模块来说，"项目仓库根在哪"本来就不是它们该知道的事——缺省改 `Path.cwd()`
后，这两个模块对仓库结构的最后一点知识清零，"拷走即可复用"更纯粹。

归档换成快照是因为**归档本身就难做对**：它要维护"哪些记录被淘汰过、淘汰
到哪个时间戳目录、恢复时新旧怎么合"这一整套中间态，而留下的东西（`voided-`
目录里一堆 json）既不能整体还原、也不能当存档用。快照把这个问题整个消掉
——一个 zip 是原子的、可拷走、可回灌，语义只有两条（打 / 覆盖回来），
不需要任何"淘汰历史"的概念。要留档就在淘汰之前先拍一张，淘汰本身该是干脆的。

**取舍**：① 参数形状**最终是"一个 `memory_root` 管四族"**——中途一度试过
"四族各一个 root"（`step_root` / `object_root` / `episode_root` /
`knowledge_root`），同日回退：四族没有哪一族是特殊的，为它们各开一个开关
只是把"一个位置"说成四遍。四族一视同仁地住在同一个根下各自的 `<kind>/`
子文件夹里。② 快照打的是**整个根**不是某一族——四族共用一个根，存档的语义
单位就是那个根，任意一个 store 上的 `snapshot()` 结果都一样（`MemoryTool`
走 `step_memory` 那个实例拿一个确定的入口）。③ `snapshot(name)` 收**名字**、
`restore(archive)` 收**路径**——这个不对称是故意的：拍快照时"放哪"由 memory
决定（harness 不该知道），恢复时"读哪个 zip"必须能接受任意来源（那正是
"覆盖读取"的价值）。④ 恢复是**覆盖不合并重置**：zip 里有谁写谁，zip 里没有
的原样留着；要精确回到某一刻得先清空根，那是更狠的语义，本方法不做。
⑤ 不引 `argparse`，继续"只认空格分隔"（0915 口径），只是把实现挪进
common.py。⑥ `common.TRACE_ROOT` / `MEMORY_ROOT` 保留为"缺省根"常量，
函数级 root 参数不传时落回它们。

**影响面**：从仓库根起跑（cwd == 仓库根）且没传开关时，所有落盘路径与从前
逐字一致（trace 与 memory 四族都是）；`STORAGE_ROOT` 这个名字从
`pokemon_agent.trace` 出口消失（grep 复核零读方）；`archive_many` /
`_voided_dir` / `MEMORY_ROOT_FLAGS` 全仓消失，无残余引用；`LocalTrace` 顺带
补了 str → Path 归一（`TraceTool.build(trace_root=…)` 公开收 `str | Path`，
探针实测不归一会 `TypeError`——原实现只受过 Path）。新增
`tests/test_memory_store.py`（store / tool 缺省根跟启动目录、显式 memory_root
压过缺省、快照打整个根且不含自己、同名快照覆盖、`name` 不许带路径分隔符、
删了能恢复、恢复不删 zip 里没有的、四族都 reload、越界路径不落地），
`test_trace_store.py` 加两条（缺省根、`TraceTool.build(trace_root=…)` 正路
示范，传 str 钉住归一）；`check_memory_roundtrip.py` 加路径 6（快照往返）。
spec 四份（trace / build / memory / experiment）与 `AGENTS.md` 同步
（`CLAUDE.md` 镜像重新生成）。

