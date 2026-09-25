# intent —— 测评体系先行，再复现 WikiSkill

> 流程位置：**intent.md** → spec.md → plan.md → PR → production
> 状态：**草案，待拍板**（§六 的待定项全部拍板后才进 spec.md）
> 起草：2026-09-24 ｜ 取代关系：`docs/spec/PLAN_wikiskill_reproduction.md` 作为参考留档，本文件**从论文重新出发**，不继承其设计决定 D1–D8。

---

## 一、一句话意图

**先造一把可信的尺子，量出"这个 agent 现在到底有多好"；再用同一把尺子，检验 WikiSkill 的技能进化能不能让它变好、好多少、代价多少。**

尺子是主产出，WikiSkill 复现是尺子的第一个用户。

## 二、为什么是这个顺序

1. **现在回答不了"产品效果如何"。**
   - 成败的唯一来源是模型判定：`Termination.GOAL_DONE` 的 docstring 写明它是"`success` 的唯一来源"，而它由 judge 模型给出。
   - judge 被量化证伪过：`docs/experiments/0827-knowledge-baseline.md` 复核 124 次 run，judge 记 115 次成功，机械复核后 102 次（假阳 16、假阴 3）。当时的复核脚本（`probe/audit_verdicts.py`）已不在仓库里。
   - 没有批次入口与汇总报表（ROADMAP F1 📋），`evaluation/` 评测框架已整体删除（`docs/spec/README.md` 第四节）。现有 `experiment/real_check/` 核的是"链路对不对"，不是"效果好不好"。
2. **WikiSkill 的机制本身就依赖这把尺子。** 论文第 4 步门控是"候选技能集在验证集上的得分 ℛ(𝒯_val) 严格大于 ℛ_best 才接受，否则回滚"。尺子不可信 → 门控不可信 → 进化出的技能是在拟合 judge 的偏差，而不是拟合游戏。
3. **没有基线就没有"提升"。** 论文所有结论都是"相对 no-skill 基线"。我们必须先有同口径的 no-skill 数字。

## 三、要复现的东西（论文口径，arXiv 2608.27454）

只列机制与评测协议，实现形态留给 spec.md。

**三层工作区**
- Raw：不可变执行轨迹 + 成败结果；
- Wiki：跨迭代累积的模式页（失败模式 / 有效策略 + 根因）、演化日志、`skill-impact` 记录（每次提案、验证分、接受与否）；
- Skills：当前生效的程序性技能，推理时注入 Inference Agent 的 prompt。

**四个角色 / 一轮迭代（Algorithm 1）**
1. Inference Agent 用当前技能集 S_{k-1} 在训练集上 rollout；**不读 Wiki**；
2. Wiki Maintainer 读抽样轨迹，做根因分析、提炼策略，以补丁方式改写 Wiki；
3. Skill Proposer（ReAct 式多轮）读 Wiki 索引 + skill-impact + 结果摘要，按需翻页 / 翻原始轨迹，产出**一个只针对单个技能的原子提案**（新建或增量补丁）；
4. Gating：在验证集上评估 S'_k；ℛ 严格大于 ℛ_best 则接受并更新 ℛ_best，否则技能回滚到 S_{k-1}；**Wiki 无论接受与否都不回滚**，验证结果写回 skill-impact。ℛ_best 初值 = 空技能集的验证分。

**评测协议**
- train / val / test 三集互不相交，打分 f ∈ [0,1]，报告 test 均分；
- 所有方法从空技能集出发；
- 结果取**整个进化过程独立跑 3 次**的均值；显著性用**配对 bootstrap（1000 次，p<0.05）**。

**我们的环境与论文的差别**（spec 阶段要逐条给出对策，这里只登记）
- 论文五个 benchmark 里最接近的是 ALFWorld（交互式具身任务）；我们是真实模拟器，单局以分钟计、成本高，3 次独立进化 × 多轮验证的预算需要单独算；
- 我们的动作空间是固定按键集，论文的技能是任意 `SKILL.md`；复现的是机制，不是文件格式；
- 论文中"Inference Agent 读 Wiki 会降分"的具体数值（草案引用的 63.7% → 60.9%）本次未能在论文正文里核到，spec 前需要对照原文确认。

## 四、测评体系

测评体系单独立项：**`docs/eval/intent.md`**（要回答的问题、三层尺子、尺子自身的规矩、待拍板项都在那里）。
本复现对它只有两条硬需求：

1. 能在指定任务集（val / test）上跑一遍并返回一个分数 ℛ，供门控与最终对照直接调用；
2. 成败来自机械判定而不是 judge——否则门控会拟合 judge 的偏差。

## 五、范围

**做**
- 在测评体系（`docs/eval/intent.md`）之上切出本复现用的 train / val / test；
- Raw 事实带来源类型标签（RAM 读数 / VLM 感知 / LLM 生成），成败标签由机械判定产出——Wiki 维护者据此区分确证与线索（ROADMAP B1；替代已撤销的 B5a）；
- no-skill 基线：直接取测评体系的第一份正式基线；
- WikiSkill 三层 + 四角色 + 门控的忠实复现，默认关闭、按开关启用；
- 对照实验：no-skill vs WikiSkill（3 次独立进化、配对 bootstrap），加一条消融：Inference Agent 读 Wiki vs 不读。

**不做**
- 不改现有 run / episode / task 三张图的决策逻辑来"刷分"——尺子造好之前不调参；
- 不做论文里针对通用 agent 的文件协议细节（`PURPOSE.md`、页面级单测、权限护栏）；
- 不做跨层聚类（ROADMAP B6）——那是复现成立之后的扩展；Belief 层与前提失效传播（B5a / B5b）已撤销；
- 不接 CI 回归门禁（F5）——报表稳定后另议；
- 不更新任何模型权重（项目铁律）。

## 六、待拍板（进入 spec.md 前必须定）

任务集构成、机械判定覆盖、基线口径、测评住哪，已移到 `docs/eval/intent.md` 的 V1 / V3 / V4 / V5，这里不重复。

| 编号 | 问题 | 为什么需要你定 |
|---|---|---|
| I1 | **train / val / test 怎么切**，每集多少条，每任务重复几次 | 定了就冻结；直接决定预算与统计功效 |
| I2 | **预算**：进化迭代轮数 K、每轮验证多少局、总 token / 时间上限；进化各角色用哪个模型 | 真机单局分钟级，3 次独立进化的开销需要你接受 |
| I3 | **与机制二（skill library）的关系**：AGENTS.md 第十一节写着"这个阶段不做 skill library" | 本次复现越过这条边界，要不要主动登记为"机制二的首次尝试" |

## 七、成功的样子（intent 层验收）

1. 能用一条命令跑完一份任务集，拿到一份钉住口径的报表，回答 Q1–Q5；
2. 报表给出第一份 no-skill 基线，以及 judge 的假阳 / 假阴率；
3. WikiSkill 在同一把尺子下跑完 3 次独立进化，给出 test 集上相对基线的差值与 bootstrap 显著性——**无论结果正负都算完成**，负结果同样是结论；
4. 每一个数字都能从盘上 trace 重算出来。

## 八、参考

- WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution（arXiv 2608.27454, Google Research, 2026-08）
- 社区复现：`kenhuangus/wikiskill`、`ashutoshsinghpr7/wikiskill`（GitHub）——仅作实现细节参照（如抽样"≤5 条失败 + ≤3 条成功轨迹"），不作为论文口径
- 仓库内：`docs/spec/PLAN_wikiskill_reproduction.md`（旧草案）、`docs/experiments/0827-knowledge-baseline.md`、`docs/ROADMAP.md` 的 B1 / B3 / B4 / F1 / F2 / F4 / F5
