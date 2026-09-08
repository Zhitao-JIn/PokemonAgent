# Git 仓库损坏与修复记录（2026-09-08）

## 发生了什么

`.git/objects` 里哈希前缀 `00`–`d7` 的松散对象目录整体消失（只剩 `d8`–`ff` 范围保留），
两个已有 pack 文件本身完好，但这之后新产生、尚未打包的提交对象几乎全部丢失。
同时 `main` 分支自身的 reflog 文件、以及两个分支的 `refs/heads/*` 松散 ref 文件也一并丢失，
只剩 `packed-refs` 里的旧指针（指向已丢失的对象）。备份 `Pokemon_Agent_backup_20260908.tar.gz`
是损坏之后打的包，同样的丢失状态，未能提供额外可恢复对象。PyCharm Local History 也未保留这段历史。

丢失范围：`main` 分支自 2026-09-04 起、`feat/model-call-observability-and-providers` 分支自
2026-08-26 起（从 main fork 出来后）的全部逐次提交对象——共计 65 次提交/合并/reflog 记录
（下方列表按时间顺序保留了这些提交的说明，用于后续追溯，但对应的 diff 内容已无法找回）。

**好消息**：损坏只发生在 `.git` 内部对象/引用层面，工作区源码文件本身完好，`git status` 显示的改动
（相对于最后一个仍然有效的祖先提交）就是这段时间的真实工作成果。

## 修复方式

1. 清除卡住的 `.git/index.lock`。
2. 把两个分支指针分别重新指向各自最后一个仍然有效的祖先提交（只改指针，不动工作区文件）：
   - `main` → `54f9f69476bb8c302c794967815a12cb34f8de94`（与 GitHub 上 `origin/main` 一致）
   - `feat/model-call-observability-and-providers` → `51b76895eeeefc42a7c43c67b8f6ffd734ed4029`
3. 把当前工作区状态整体提交为一个新 commit，作为这次修复后的起点。

## 丢失的提交记录（按时间顺序，仅存说明，无法找回 diff）

- 2026-09-04 17:58 `63acd015e8` 观测台目标栈：前端纯本地草稿 + 后端整栈 push/read 独立接口
- 2026-09-05 03:45 `2de5e89365` Merge made by the 'ort' strategy.
- 2026-09-05 10:11 `c7e0598488` 可观测性补全 + provider 架构重排（ModelCall.prompt、frame_png 直挂、prompt 归位、多供应商 provider）
- 2026-09-05 13:19 `50240c7212` observation 字段清理：删三个纯诊断字段 + done/success 搬出 observation
- 2026-09-05 15:12 `88f1ae596a` StepMemory 挂截图（base64 存储）+ judge/verify 改多模态调用 + 判定链路换供应商
- 2026-09-05 15:12 `12507de3f9` StepMemory 挂截图（base64 存储）+ judge/verify 改多模态调用 + 判定链路换供应商
- 2026-09-05 15:48 `5e4efcfba5` 合并 verify_steps 与 summarize 为一次调用；decide_action.md 补 rationale 依据→结论硬规则
- 2026-09-05 16:09 `0e3572d8e7` 真机跑通前修掉三处回归：trace/store.py 方法被误缝进函数、入口守卫丢失、旧 3 元组解包
- 2026-09-05 16:29 `07b0748585` 人工审查超时兜底：CONTINUE → STOP
- 2026-09-05 16:34 `b793c62743` 前端：model_call 日志栏拆成独立一栏
- 2026-09-05 16:35 `15150fd0c3` 前端：model_call 挪到页面最下面，折叠不起眼
- 2026-09-05 16:45 `77acea574c` 校验/蒸馏/规划三条链路统一切到 doubao-seed-2-1-pro-260628
- 2026-09-05 16:53 `ae7e1e4daf` plan 真跳过模型调用；单独给 plan 设置 provider
- 2026-09-05 16:59 `5de8b73ddc` 记录每次模型调用的缓存命中 token（cached_tokens）
- 2026-09-05 17:10 `f72135e1f9` 多模态请求：文字块挪到最前面，图片挪到最后面
- 2026-09-05 17:27 `28a1fc164e` 前端数字台显示缓存命中；verify_and_summarize.md 调整结构方便缓存
- 2026-09-05 17:31 `c900adbb95` perceive_screen.md：把动态地图数据挪到文末，方便缓存
- 2026-09-06 10:22 `95d443c9a1` judge: 减少 history 窗口到 2 条，压缩 input token
- 2026-09-06 10:29 `1a168cf79f` judge: 步号连续时跳过当前帧的现读现编
- 2026-09-06 10:32 `75afe8ad25` judge: 删掉当前帧现读现编，图只来自 history
- 2026-09-06 10:51 `a26a463b8b` judge: 第 0 步不问模型，BrainVerdictReq 删掉 obs 字段
- 2026-09-06 11:09 `8fe8774bce` step_memory: 新增 dedup_snapshots，一次遍历返回图+对应观测
- 2026-09-06 11:13 `07c8a64191` verify_and_summarize 也换成 dedup_snapshots，删掉 frame_sequence 包装
- 2026-09-06 11:30 `f79d11464e` verify_and_summarize.md: 删掉重复的 goal 和 initial/final_state
- 2026-09-06 12:21 `3e5a6dd6ee` 删掉 summarize() 兜底节点，收尾链只留 verify_and_summarize 一条路径
- 2026-09-06 12:45 `6557f3888d` 补删 EpisodeHarnessPort.summarize()：上次删兜底节点时漏了这个 Protocol 声明
- 2026-09-06 12:57 `125cb181d5` 死代码清理：run_plan 改走 prompts 层拼装，choose_once 用起 BrainDecisionResp，删掉真正的死字段
- 2026-09-06 15:56 `63da479fcf` 统一出口：11 个子包对外接口收拢到 __init__.py（编码范式规则 6）
- 2026-09-06 16:00 `07d0a81f04` 清理：7 个既有格式债务文件跑 ruff format
- 2026-09-06 17:09 `002ced0072` 注释历史叙事迁出代码（编码范式规则 7）+ AGENTS.md 注释条款同步
- 2026-09-07 13:55 `ca5a407b65` 基线快照：重构前工作区现状（含进行中的 BrainTool 层、harness 拆分等未提交改动）
- 2026-09-07 13:59 `dced1b2cc8` utils 归位：删包根 utils.py，三个函数按消费者各回各家
- 2026-09-07 14:47 `617c6eb5a0` 协议类按通信方向改名：文件名=类名=From{调用方}To{被调方}{函数名}{Req|Resp}
- 2026-09-07 15:28 `5c5a365812` TraceTool：记账转换收进 tool 层（按 TraceKind 分派渲染），trace/utils.py 退役
- 2026-09-07 15:33 `fde2f905a4` TraceTool：记账转换收进 tool 层（按 TraceKind 分派渲染），trace/utils.py 退役
- 2026-09-07 15:35 `48162ee046` TraceTool：记账转换收进 tool 层（按 TraceKind 分派渲染），trace/utils.py 退役
- 2026-09-07 15:36 `319e59c6b3` TraceTool：记账转换收进 tool 层（按 TraceKind 分派渲染），trace/utils.py 退役
- 2026-09-07 15:37 `8ee7e3c09d` TraceTool：记账转换收进 tool 层（按 TraceKind 分派渲染），trace/utils.py 退役
- 2026-09-07 15:41 `67b4a8f5b1` BrainTool 接线：harness 不再直握 BrainPort
- 2026-09-07 15:43 `69b72e63be` 收尾：RunHarness 断言与 import 补齐（BrainTool 接线遗漏）
- 2026-09-07 15:49 `06b7f23d9c` 方案文档：providers 协议定论——不改，保持 text/vision 两个（用户拍板）
- 2026-09-07 16:17 `2558d37980` 集成测试跑通，修掉 4 个 req 化接线 bug
- 2026-09-07 16:18 `05a37424c0` 集成测试跑通，修掉 4 个 req 化接线 bug
- 2026-09-07 16:36 `c8b9ab7ba1` 交叉验证交接文档：提交链/验收清单/测试覆盖与盲区/环境坑/判断点
- 2026-09-07 18:10 `c288b3fa57` checkpoint 前置改造：StepMemory 落盘写穿 + 记忆落盘三元组签名（PLAN v4 §7.0/§3）
- 2026-09-07 18:23 `6d154ae3ed` CheckpointTool：存/取/废弃归档实现 + WorldPort 字节快照 + MemoryTool 恢复方法（PLAN v4 §7.1）
- 2026-09-07 18:59 `98ff1e5499` checkpoint 接线：save_checkpoint 图节点 + 三级恢复入口（PLAN v4 §2/§4/§5）
- 2026-09-07 19:25 `414760c32f` DataCenter 事件流槽 + checkpoint 恢复测试（PLAN v4 §7.2/§10，收尾）
- 2026-09-07 19:27 `06145d86e0` checkpoint 设计方案 v4：三级恢复语义/签名三元组/废弃归档/判断点拍板记录
- 2026-09-07 19:27 `624e0da88b` checkpoint 交接文档：代码事实清单/触点/验收标准（粒度部分以 PLAN_checkpoint 为准）
- 2026-09-07 19:28 `dfb531d96f` checkpoint 交接文档：代码事实清单/触点/验收标准（粒度部分以 PLAN_checkpoint 为准）
- 2026-09-07 19:50 `82a14ef4cc` MemoryTool 补 SemanticObjectReader.query(place)：真机跑出的端口不匹配修复
- 2026-09-07 20:19 `c443ad7fa9` judge_success 模板：散文里的 $占位符提及改为中文小节名
- 2026-09-07 20:28 `44dc468139` reasoning token 进账单：provider 解析 → trace payload → 观测台聚合
- 2026-09-07 20:58 `c13b397aa2` TraceEvent.frame_png 改 base64 str：内存/磁盘/HTTP 三处形态统一
- 2026-09-08 07:13 `d05971b3bc` decide_action 模板重排：静态规则整体前置（决策链吃缓存）
- 2026-09-08 07:35 `491b1ecee9` temperature 分层：判定/规划链归零，决策降到 0.3
- 2026-09-08 07:42 `a65ab165d8` run_plan 模板重排：规则与输出格式前置（run 级规划吃缓存）
- 2026-09-08 07:42 `32f69ff513` run_plan 模板重排：规则与输出格式前置（run 级规划吃缓存）
- 2026-09-08 10:13 `d16f834527` judge 换 qwen3.8-max + verify 留豆包多帧拼接：按图费结构重新分岗
- 2026-09-08 10:13 `399a702497` judge 换 qwen3.8-max + verify 留豆包多帧拼接：按图费结构重新分岗
- 2026-09-08 10:24 `06facf3d0e` 图片拼接下沉到 ArkProvider：豆包收到的一定是一张图（provider 层结构保证）
- 2026-09-08 10:25 `79ec32571b` 图片拼接下沉到 ArkProvider：豆包收到的一定是一张图（provider 层结构保证）
- 2026-09-08 10:47 `8cfb310175` verify 拼图去上采样 + 布局契约去 provider 依赖 + $images_note 移出静态前缀
- 2026-09-08 11:30 `c76caadf7f` 撤掉 $images_note：网格读法说明改纯静态（只标注 3 列），行数交给模型看图数
