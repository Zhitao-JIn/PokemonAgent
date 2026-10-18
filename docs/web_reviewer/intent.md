> 状态：旧实现已在 reviewer R6c（529）删除；当前入口为 `python -m pokemon_agent.reviewer --seats human`。新 AI 席待 R7。以下正文作为历史设计保留。

# intent —— 纯展示前端：不带 reviewer，只看实时推送

> 流程位置：**intent.md** → spec（若需要）→ plan → 落码
> 状态：**讨论稿**（2026-09-29 与用户定向后起草）；**未授权落码**
> 关联：`docs/web_reviewer/spec.md`（人在环的设计，已落地 W1–W5）、`docs/web_reviewer/plan.md`、
> `pokemon_agent/review_backend/`、`pokemon_agent/tools/trace/live_feed.py`、`experiment/real_check/check_harness.py`
>
> ⚠ 本文**不是** WebReviewer 的 intent——那个设计早已落地（spec.md / plan.md）。
> 本文是**同一套设施的第二种用法**的意图：**关掉"问人"，只留"看"**。

---

## 一、一句话意图

让前端界面在**没有 reviewer** 时也能直接打开、实时看见 run 在干什么（画面 + 事件时间线），
**不做历史**：不看已结束的 run，不补旧账，不落盘。人是观众，不是参与者。

## 二、为什么这样做（用户的两条定向）

1. **不采用依赖 reviewer 的形态**：现在想看画面必须先开 `--review`（问人）——
   "想看"被绑在"要人插手"上，这是错的。
2. **不做历史**：只看实时推送。历史 run 的读取要新开一条读通道
   （盘上扫描或查 Langfuse），还要解决"后端不该认识盘上路径"的边界冲突——
   **代价与收益不成比例，明确砍掉**。

## 三、现状：能力已经都在，只差一处耦合

| 件 | 状态 | 用于纯展示 |
|---|---|---|
| `LiveFeedTrace`（`tools/trace/live_feed.py`） | 已落地 | ✅ 就是数据源：包在 trace 存储外，落盘照旧、顺手推一份给后端 |
| 后端 `/feed` 转播 + `/ui` 广播 | 已落地 | ✅ 原样复用 |
| 后端 `GET /` 吐单页 + 重连补发 | 已落地 | ✅ 不需要 `/harness` 也能服务（`_process_request` / `_serve_ui` 都不看 `_harness`） |
| 页面「实时」区（当前画面 + 时间线） | 已落地（`page.py`） | ✅ 原样复用：最新 `sense_frame` 的 `content.frame` 直接上 `<img>`，其余事件进时间线 |
| 页面「待答卡片」+「历史」两块 | 已落地 | ⬜ 纯展示下恒空，需定空态（§六 Q2） |

**唯一的耦合是人为的**，在 `check_harness.py`：

```python
reviewer, review_url = None, None
if _REVIEW_MODE:                       # ← 只有 --review 才有值
    review_url = _REVIEW_URL or DEFAULT_URL
    reviewer = WebReviewer(run_id, url=review_url)
...
live_feed_url=review_url,              # ← 展示通道被绑在"问人"开关上
```

解开它 = 加一个开关（reviewer 保持 `NullReviewer`、`live_feed_url` 有值）。**前端零改动即可跑通**。

```
run 进程 ──TraceTool.append──► LocalTrace/Langfuse（落盘，唯一真相）
                      └──LiveFeedTrace──► 有界队列 ──daemon 线程──► WS /feed ──► 后端 ──► WS /ui ──► 网页
                                          （满了丢最旧 / 断了丢弃 + 一行日志）
```

## 四、核心原则（落码时的判据）

1. **展示是支流，不是真相**：盘上/Langfuse 的账仍是唯一真相。推送丢了不补、不回查、
   不影响 run 的成败与耗时（`LiveFeedTrace` 已如此保证）。
2. **零新增状态**：后端仍只有内存 `deque`（feed 300 / history 50）。**不做落盘、不做索引、
   不做按 run/episode 的分组存储**（要做就是"历史"，已砍）。
3. **后端与网页仍不认识游戏语义**：只搬渲染好的文本与事件形状；渲染归源程序。
4. **不碰 reviewer 链路**：`Reviewer` Protocol、`Null/Console/Web/Tape` 四实现、
   `--review` 的六个落点一律不动。
5. **起跑仍交回用户本机**（0924 口径）：后端 `python -m pokemon_agent.review_backend`
   由用户先起，run 后起；AI 不经沙箱拉长跑进程。
6. **后端不在也要能跑**：`live_feed_url` 指了但后端没起 → `LiveFeedTrace` 每 5s 重试、
   期间事件丢弃、只打一行 `[feed]` 日志，run 不受影响（已是现行为）。

## 五、明确不做

| 不做 | 理由 |
|---|---|
| 历史 run 回看 / 旧账补发 | 用户定向砍掉（§二.2） |
| 按 episode / task 的回放索引 | 属于"历史"；实时流里只有"最新一帧"和"最近 80 条" |
| 控制（暂停 / 中断 / 改目标） | 那是另一件事（跳 B 的双向通道已留好，不在本 intent 范围） |
| 鉴权 / TLS / 多 run 并发 | 与 spec §八同一条：只绑回环 |
| 结构化改表单、给页面加游戏语义 | 后端与网页不懂游戏（§四.3） |

## 六、待你定的三件事

| # | 问题 | 建议 |
|---|---|---|
| Q1 | 开关名与语义 | `--feed-url ws://host:port`（与 `--review-url` 同形）。`--review` 仍隐含开 feed（现状不变）；两个都给时以 `--feed-url` 为准并打印一行说明 |
| Q2 | 页面空态 | **保留**两块但改文案：待答卡片显示"未接入人在环（本次 run 只是展示）"，历史区显示"本次会话还没问过"。理由：删 DOM 分支会让 `/ui` 与页面多一个"模式"状态，而文案是零成本 |
| Q3 | 命名 | 包名 `review_backend/`、目录 `docs/web_reviewer/` 都带 review。纯展示是它的第二种用法，**建议暂不改**（改包名要动 `__main__`、文档、清场清单，收益只是字面）；真要改名，等这个功能立住之后整目录一并改 |

## 七、验收（机械可验，不含主观评价）

1. `python -m pokemon_agent.review_backend` 起后端 → 浏览器开页 →
   `check_harness.py --feed-url ws://127.0.0.1:8765`（**不传 `--review`**）：
   - 后端日志出现 `[feed] 实时画面开始推送到 …`；
   - 页面时间线在涨、画面随 `sense_frame` 更新；
   - `/health` 的 `harness_connected` 恒 false（本就没有 `/harness`）；
   - **盘上账与不接 feed 时逐条同序**（`check_web_reviewer.py` 已有同款比对做法，照抄）。
2. 不传任何开关 → 与改动前**逐字相同**（不起 `/feed` 连接、`build_real` 拿到的 `live_feed_url=None`）。
3. 传了 `--feed-url` 但后端没起 → run 跑完、账全、日志里有一行 `[feed]` 提示（不刷屏）。
4. ruff 净 + 定向测试绿（`test_review_backend` / `test_trace_tool` / `test_build`）。

## 八、落码范围预估（供你判断要不要拆步）

- `experiment/real_check/check_harness.py`：加开关解析、`live_feed_url` 与 reviewer 解耦、
  起跑打印一行、模块 docstring 补一段（**唯一的行为面改动**）。
- `pokemon_agent/review_backend/page.py`：空态文案（若 Q2 选"改文案"）。
- 文档：`docs/web_reviewer/plan.md`（追加本 intent 的落码步骤）、`docs/spec/experiment/SPEC.md`
  （开关表）、CHANGELOG 一条。
- **后端 `backend.py` 与 `LiveFeedTrace` 零改动**——这是本方案最大的优点。
