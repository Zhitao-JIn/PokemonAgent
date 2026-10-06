# evals 变更志

> 主题账：测评体系（evals/）的每一次变更，按**背景问题 → 归因 → 更改方案 → 结果**
> 四段记录。主 CHANGELOG.md 保持编号总账，这里是测评专题的完整叙事——每条目标：
> 拿出来就是一段可以直接写进博客或简历的"发现问题 → 定位 → 修"故事。
>
> 背景基线（2026-09-28 工业差距评估，对标 inspect-ai）：数据集 v1 冻结（20 样本）+
> 机械判据 18 条注册表 + 红线 R1–R3 + rubric 框架 + 批跑入口已通；短板集中在
> **判定三套协议不统一、编排无抽象（Task/Solver/epochs）、Metric 无抽象、
> 真值耦合 trace、边界纯净度**五项。21 维 rubric 见用户级 skill `module-gap-audit`
> 的 `references/rubric-evals.md`（复检后 ✅7/🟡6/🔴5/⚪3）。
> 文档链：`docs/eval/intent.md`（意图 + V1–V13 拍板）→ `spec2.md` → `plan2.md`（R0–R5）。

---

## EVAL-1（2026-09-25~26，主账 229–260）—— 测评体系 v1：从"成功率模型说了算"到机械判据注册表

**背景问题**：`Termination.GOAL_DONE` 是 success 的唯一来源，由 judge 模型给出——
0827 机械复核 124 次 run：judge 记 115 次成功、实际 102 次（**假阳 16、假阴 3**）。
复核脚本用完即丢，仓库里没有任何可复用的测评设施；每次改 prompt / 重试 / 判定都在盲飞
（仅 0924 一天就有 28 条变更无法回答"变好还是变坏"）。

**归因**：三个断层。① 真值断层——被测对象（judge）同时充当裁判，没有独立的机械真值；
② 设施断层——原 `evaluation/` 整体删除后没有批次入口，核链路的 `real_check` 明确不回答效果；
③ 复现断层——没有冻结起点，两次"同配置"跑的不是同一个世界。

**更改方案**：四件套一次落齐（E1–E8）。① **数据集 v1**：20 样本 = 钉死 `.state`（sha256
冻结校验）+ goal + 机械判据 id + rubric/红线引用，`check()` 命令核 id 唯一/引用存在/哈希；
② **机械判据注册表**：18 条 `@rule` 纯函数（重名当场报错），真值口径钉死——ram 永远可信、
对话/选项只认 `ram.decoded`（视觉抄的字不算）、位置只认内存，judge 当年被台词骗的
三类错（我方掉血当对手受伤、`Choose a POKéMON.` 当选项、致谢台词当买成）各有一条反例测试；
③ **红线 R1–R3**（出错收尾 / 刹车失灵 / 谎报成功，命中即判负不参与加权）；
④ **批跑入口**：`python -m evals e2e run`，每样本独立子进程（卡死崩溃不连累，超时即杀），
口径头钉 git/模型/旋钮/数据集哈希/知识库哈希——比 inspect-ai 默认口径头更细。

**结果**：第一份 k=1 报告链路可跑通（正式基线待 k>1）；diff 命令带口径全等校验
（口径字段不全等的两份报告拒绝对比——比 inspect 默认更严）。遗留：model grader
只有 schema 声明无实现；报告聚合手写在 markdown 渲染里（EVAL-3 的病根）。

---

## EVAL-2（2026-09-28，主账 314–318）—— 工业差距评估 21 维：用 inspect-ai 的槽位概念给尺子定位

**背景问题**：v1 落地后方向问题浮出来——自研到什么程度算够？测试该照搬训练界的
train/val/test 协议吗？epochs、pass@k 这些"别人都有"的东西值不值得自建？

**归因**：拿 inspect-ai（UK AISI，Anthropic/OpenAI/DeepMind 系统卡在用的事实标准）
当 rubric 逐维对照，21 维评级 ✅7/🟡3/🔴10/⚪2。三个关键定位：① 判定三套协议
（@rule / 红线 / rubric grader）形状互不相容——是 Metric 与 pass@k 缺位的**根源**；
② 编排散在两个手写函数里，"一条测评"没有名字，epochs/resume 没有挂点；③ train/val/test
是训练概念——用户拍板**不照搬**（单数据集 + 版本冻结即可，rubric 22→21 维）。
12 条拍板（V1–V12）升格为 spec2：**真依赖 inspect-ai 轻用**——"inspect view 看结果、
Langfuse 看过程"：结果层交给 Inspect View（含 run_id↔Langfuse 的复制粘贴级接线），
过程层不映射进 inspect 事件 schema（35 种 trace kind 只配当 metadata，不值得适配）。

**更改方案**：spec2 定骨架 `core/`（六薄适配）+ `bridge.py` + `tasks/` + `scorers/` +
`data/`；solver 保留每样本子进程隔离（PyBoy 崩溃隔离是真实需求）；plan2 定 R0–R5
落码序（先冒烟验证 inspect-ai 真实 API 再搬迁；先契约后消费）。

**结果**：方向定案，路线图挂账 R0–R5；复检同日再跑（19 条证据全部复核成立），
唯一改判 #12 并发调度 🟡→⚪——真机单模拟器硬约束（两模拟器并存是 Event 41 触发器），
并发补了纯风险。

---

## EVAL-3（2026-09-28，主账 326）—— 判定协议层：三套判定收敛到 `(stream, sample) → Score`

**背景问题**：同一份 run 产物要过三道判定，各说各话——@rule 回 `CheckVerdict(outcome,
evidence, reason)`、红线回 `list[RedLineHit]`、rubric 回 `RubricScore(score, detail)`。
指标层想算"成功率 / pass@k"时没有任何统一输入可消费——pass@k 在报表里是一行硬编码的
n/a 文案。热力图 #5/6/13/14 四个 🔴 的根都在这。

**归因**：不是缺指标函数，是**缺槽位的形状**——Task/eval_set（编排层）还没搭，
但 scorer/metrics 槽位接受什么类型必须先定；反过来先搭架子，inspect-ai API 一验证出偏差
（R0 未跑）就得返工两层。

**更改方案**：协议先行（V13，用户拍板"工程缺失的协议部分先做"+"Task 抽象是要做的"）。
新增 `evals/e2e/scoring/` 四文件：`Score` 载体（`kind` 机械分列 verdict/graded——
模型分永不混进机械成功率，V3 的分列用类型系统钉死）+ 统一 Scorer 签名
`(RunStream, EvalSample) → Score`（inspect 的 `(state, target) → Score`）+ Metric 协议
（accuracy / pass@k / pass^k 用 Codex 无偏估计量 `1−C(n−c,k)/C(n,k)`、unjudgeable
不进分母）+ `ModelGrader` 注入协议（默认关 D6，解析归注入方，evals 零 provider 依赖）。
旧三套各包一层适配、**零删除零消费**——先契约、后消费。

**结果**：定向 56 绿、ruff 净。测试踩坑两笔记档：手造 `run_end` 账塞裸 dict 会被
`ParsedEvent` 校验成未完成 BaseModel（`__private_attributes__` AttributeError）——
必须用真 `RunEndContent`；pydantic 校验器里的 assert 以 `ValidationError` 浮出。
R2a 上移 `core/` 时只换 import；R2b 消费方接上后删旧三套。
**消费已接（328，主账 328）**：`evaluate.py` 判定主链改走 `mechanical_scorer` +
`red_line_scorer` 并列出 Score，`judge` / `red_lines` 降为 scoring/ 内部实现
（外部直调清零，`report/__init__` 撤 re-export），`judge_cells` 改收 `Outcome`；
`CheckVerdict` / `RedLineHit` 降为**报告投影**（`verdict_of` / `hits_of`，
R5 退役 SampleResult 时删）——投影守卫按 `scorer_id` 走而非 kind（红线 Score 也是
verdict 型，第一版守卫被自己的测试炸出反例）。#5 的残留只剩"主输入换 RunResult（R1）
与投影退役（R5）"，协议本身已收口。

---

## EVAL-4（2026-09-28，主账 327）—— 批跑前置：起 harness 之前检测并拉起 inspect view

**背景问题**：观测三层分工定稿后，结果层入口是 Inspect View，但它是独立本地服务
（默认 127.0.0.1:7575）——批跑跑完才发现忘了起 view，live view（逐样本跟随）就废了；
反过来 view 已在跑时再起一个会同端口互杀。

**归因**：纯流程缺口——缺一个"起 harness 之前的前置检查"，与 real_check 的
pre-checks 同构，但服务对象是结果层。

**更改方案**：`runner/view.py::ensure_view` 三态——端口通（别人在跑）→ 不动；没在跑且
`inspect` CLI 在 PATH → **脱离批跑进程**拉起（Windows `DETACHED_PROCESS`，批跑结束
view 不陪葬），输出落 `inspect_view.log` 供诊断，5s 内轮询端口确认拉起成功；CLI 缺失
或端口不通 → 显式跳过，只报告不抛。`batch.run_batch` 在口径头之后、第一个 run-one
子进程之前接线。

**结果**：定向 56 绿。inspect-ai 到 R0 才装——此前本模块恒走"跳过"分支，预接线，
装上即自动生效；拉起路径不进单元测试（要真 CLI，留给 R0 本机验收）。

---

## EVAL-5（2026-09-28，主账 329）—— R0：真库入位，"自研 vs inspect-ai"的悬案落地

**背景问题**：spec2 拍板"真依赖 inspect-ai 轻用"后，代码里实际一次都没 import 过它——
协议层（326）是按网页资料对齐的"想象形状"，R0（装库 + 冒烟 + 核真签名）是 plan2 的闸门。
用户定向：先核实 R0，拿真库的接口写，不要自己编。

**归因**：三处想当然被实测推翻——① pass@k/pass^k 在 0.3.271 里**不是独立 Metric**，
是 `Epochs(n, reducer=pass_at(k)/pass_k(k))` 的 ScoreReducer 机制（`pass_at`=pass@k
至少一次成、`pass_k`=pass^k 全成——命名与我方草稿正好错位）；② `Score.reason` 是失败
原因**字面量**（refusal/…），文字理由必须放 `explanation`；③ Metric 协议收
`list[SampleScore]`、指标挂在 scorer 装饰器上。

**更改方案**：`uv add inspect-ai`（0.3.271 定版）+ `scripts/r0_smoke.py` 冒烟
（@task + 假 solver + @scorer + eval_set epochs，全链出 .eval）+ spec2/plan2 回写 +
**删除自研 pass@k/pass^k 估计量**（`metric.py` 只剩过渡期 accuracy/stderr 的
unjudgeable 包装；R5 report 改读 `EvalLog.results.metrics` 后整体退役）。

**结果**：冒烟五项全过（Task/eval_set/Epochs reducer/真库 metrics/.eval 落盘）；
删除前先独立调用真库 reducer 对拍——C,C,I → pass_at(2)=1.0、pass_k(2)=1/3，
C,I,I → 2/3、0.0，与自研公式逐位一致，删得零语义损失。`runner/view.py` 的
`inspect` CLI 自此真实可用。定向 55 绿。

---

## EVAL-6（2026-09-28，主账 330）—— R2a：五包骨架落位，"搬完删旧目录"兑现

**背景问题**：R0 后目标骨架（core/scorers/data/tasks/bridge）只在 spec2 里，盘上还是
e2e/ 九子目录平铺 + 根级三旁支——R2b 的落点悬空，边界纯净度违规（screen import 被测
私有名、红线耦合 live config）也没地方修。

**更改方案**：按 spec2 §二迁移映射整体搬迁——checks+redlines+model_graded →
`scorers/`；scoring 三件 → `core/`；diff → `core/evallog.py`；dataset（含 v1 冻结数据）→
`data/`；schemas → `schema/`；三旁支 → `tasks/`；新增 `core/{task,solver,evalset}.py`
真库薄适配 + `bridge.py`/`tasks/e2e.py` 占位。30 文件 import 批量改写。

**结果**：`python -m evals e2e dataset check` 20 条全过（冻结样本路径随迁改写、
`loader.py` 的 REPO_ROOT 深度修正）；全量 135 绿、ruff 净、compile smoke 过。
踩坑两笔：① `core.evallog → report.assemble` 的 import 环——用"HEADER/RESULTS 常量
上移进 evallog（V9 载体）、assemble 反向引用"解开；② `data/v1/samples.jsonl` 里冻结的
**仓库相对路径**指向旧位置，机械改写后冻结校验复过——数据集"冻结"冻的是样本与哈希，
路径属包装层。`e2e/` 保留 runner/report/cases/process/rubric 五包到 R2b/R3/R5 收编。
**边界修正两处（plan2 R2a 验收项）随迁落齐**：① 红线阈值注入化——`red_line_scorer(3,3)`
式显式传参，`evaluate` 经 `stall_limits_of(header)` 从口径头快照取值，`redlines.py`
零 live config；② `pyboy_world._overlay_of/_layout_field` 更名转公开 + 上移纯模块
`screen_text.py`（顺带把纯文字→Facts 逻辑从 pyboy 重依赖里摘出来），`world` 公开面
扩八名、screen_reading 全走 `from pokemon_agent.world import …`——**21 维评级 #20
边界纯净度的两处实锤清零**（剩 macros/takeover_views 骨架复制一处，随 R2b 收敛）。

---

---

## EVAL-7（2026-09-28，主账 331–333）—— R1→R4 连续落码：从"裸四元组"到"inspect 真协议跑批"

**背景问题**：R0 之后协议层就位，但主链还是三张旧皮——harness 返回裸四元组没人接（V8 空转）、evaluate 各读各的 trace 算开销、epochs/resume 没有入口、inspect 装了却只被 view.py 探测。

**归因**：四步是一条依赖链：R1 定契约（RunResult）→ R2b 换数据面（evaluate 主输入 + 效率层取数源）→ R3 接线（bridge/solver/task/eval_set）→ R4 钉口径（header 扩依赖版本与生成参数）。跳步就会双账并行。

**更改方案**：R1 `RunResult`（outcomes/usage/counts/wallclock/episode_bounds，branch 过滤本执行线）+ 三处签名换形 + `one.py` 落 `run_result.json`；R2b evaluate 主输入换 RunResult（旧产物记 invalid，不留过渡）、效率层改 `_efficiency_of` 字段映射（旧 `efficiency.py` 删）、judge 一致性包成 `judge_agreement_scorer`、`LLMGrader`（DeepSeekProvider→ModelGrader，重试一次）入位；R3 bridge 翻译 + `run_one_solver`（子进程隔离取舍 A）+ `tasks/e2e.py` 真 `@task` + `evaluate()`（eval_set：epochs/Epochs reducer=[pass_at,pass_k]/eval_set_id 即 resume）+ cli `evaluate` 子命令；R4 header 扩 `deps`/`epochs`/`speed`/`timeout`/`rule_ids` 并入 COMPARABLE_FIELDS。

**结果**：全量 **290 绿**、ruff 净、dataset check 过、`evaluate --help` 可用。踩坑三笔：① python 字符串 `\n` 手滑成 `/n` 写坏 restore.py（grep 当场抓出）；② CRLF 文件上 python 多行 replace 不可靠——多行改写一律回 Edit 工具；③ 330 条目边界段被补写时重复了一遍（编辑前没重读文件），当日去重。**待真机**：evaluate 跑 2 样本 × epochs=2 + 中断 resume + inspect view 三项验收（plan2 R3 验收，二号条归你本机）；**待拍板**：D7（report.md/results.jsonl/batch.py 退役时点）——验收过了一次删净即 R5 完整闭环。

---

---

## EVAL-8（2026-09-29，主账 334）—— 入口统一 `inspect eval`：自研 CLI 退场，参数改 config.json

**背景问题**：R3 落了自研 `evaluate` 子命令（argparse 包住 eval_set）——与 inspect 的原生玩法（task 文件 + `inspect eval` + `-T`）重复，两套入口纯维护负担；跑批参数（切分/型号/速度/超时）靠旗标传递，与"口径头"的文件化本意相悖。

**更改方案**（用户定向"统一成 inspect eval 的形式，不要自研 cli；config 写 config.json 启动读取"）：新增 `evals/config.json`（进 git）+ `runconfig.load_config()`（缺省补齐）/`resolve_models()`（null 链路回退主型号）；`tasks/e2e.py` 重写为 `@task e2e(...)`——参数缺省 None 回退配置、`-T` 逐项覆盖；`e2e_scorer` 补 `@scorer(metrics=[accuracy(), stderr()])`；**删自研 evaluate 子命令**；`.venv` 补 pyboy==2.7.0（R3 隐性部署缺口：venv 有 inspect-ai 没 pyboy，真 evaluate 起不来）。

**结果**：装配冒烟过（config → Task：20 样本；`-T samples=[...]` 覆盖 1 条）；全量 290 绿、ruff 净。新跑法：`inspect eval evals/tasks/e2e.py --log-dir eval_results/inspect --epochs 2 --epochs-reducer pass_at` + `inspect view --log-dir eval_results/inspect`。旧 `run`/`report`/`diff` 命令暂留至真机验收（删净清单在待办）；`run-one --epoch` 是 solver↔子进程的内部协议，不是用户 CLI。

---

---

## EVAL-9（2026-09-29，主账 335）—— 起点改"预打包存档"：打包挪出运行时，data 层新增打包工具

**背景问题**：R3 链路里 `_pack` 在 eval 运行时为每条样本**白白起一次 PyBoy** 打包起点（打包完 restore_run 又起一次）——运行时做了本该属于数据准备的事；且 manifest 内嵌代码版本章，"运行时打包"让每次跑批都隐性依赖"代码与存档同刻新鲜"。

**更改方案**（用户定向："运行时只读打包好的存档；打包是我在数据层面自己准备的事，你提供打包脚本我打包，接受重打数据集"）：`SampleStart` 收敛为单一 `kind="archive"`（存档目录名 + 来源 .state/sha256 留痕）；`loader.check` 核"存档存在 + 来源哈希"；`runner/one.py` 删 `_pack`/`_adopt`，`run_one` 直读 `data/<version>/archives/<样本>/manifest.json`；新增 `data/pack.py` 打包工具（核哈希 → build_real 起 PyBoy → checkpoint_only 打包 → 拷进 archives/）。

**结果**：全量 290 绿、ruff 净；dataset check 正确报"20 条起点存档缺失"（等打包）。manifest 跟代码走 → 存档不进冻结哈希，数据集冻结的是来源（.state+哈希）；存档过期由 restore_run 版本章校验拦下、重打即可。**你的操作序**：`python -m evals.data.pack` → `dataset check` 全过 → `inspect eval evals/tasks/e2e.py …` → `inspect view …`。

---

## 待办（按 plan2 R0–R5，做完挪进上面成条）

- ~~**R0 冒烟**~~：**已完成（EVAL-5，329）**——inspect-ai 0.3.271 入位，API 偏差回写 spec2。
- ~~**R2a 骨架搬迁**~~：**已完成（EVAL-6，330）**——五包落位、行为不变、边界修正两处落齐（#20 两处实锤清零）。
- ~~**R1 RunResult**~~：**已完成（EVAL-7，331）**——三处签名换形 + one.py 落 run_result.json。
- ~~**R2b Scorer 收敛**~~：**已完成（EVAL-7，332）**——主输入换 RunResult、效率层换源（旧 efficiency.py 删）、judge 附加 scorer、LLMGrader；旧协议公共面 328 已清零。
- ~~**R3 eval_set 化**~~：**代码完成（EVAL-7，333）**——bridge/solver/task/evaluate + cli；**真机三项验收待你本机**（evaluate 2 样本 × epochs=2 + 中断 resume + inspect view）。
- ~~**R4 manifest**~~：**已完成（EVAL-7，333）**——header 扩 deps/epochs/speed/timeout/rule_ids，COMPARABLE_FIELDS 同步。
- **R5 收尾**：指标消费已由 inspect 兑现；入口已统一 `inspect eval`（EVAL-8）；起点已改预打包存档（EVAL-9）——剩"删 report.md / results.jsonl / batch.py / 旧 cli 命令面"——D7 待拍板 + 真机 evaluate 验收后一次删净。
- **数据准备（你本机，一次性）**：`python -m evals.data.pack` 打 20 条起点存档（PyBoy 逐条起，产物进 `data/v1/archives/`）→ `dataset check` 全过后再跑 evaluate。代码动 RunState 结构后存档过期，重跑 pack 即可。
- **覆盖表难度列回填**：等第一批 k=1 结果按成功率标定（coverage.md 缺口清单）。
