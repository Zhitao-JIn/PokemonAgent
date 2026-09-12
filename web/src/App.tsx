import { useEffect, useMemo, useRef, useState } from "react";
import { getGoals, pushGoals, startRun, submitHumanNote, submitReview } from "./api";
import { useFrameStream } from "./useFrameStream";
import { useReview } from "./useReview";
import { useRunStream } from "./useRunStream";
import type { DraftGoal, GoalView, HumanDecision, PendingReview, SseEvent, TraceEvent } from "./types";

/**
 * 观测台主页：左栏（画面 + 目标栈）+ 右栏"当前步轨迹"链——一条链 = 一步在
 * episode harness 图上的路径，节点随事件点亮，点击节点看该相位的 raw
 * （`docs/ROADMAP.md` 第 15 条的第二次形态迭代，0903）。
 *
 * 状态机：无 run → 启动表单；startRun 成功 → runId → 三条数据线各自工作：
 * 事件流（SSE 订阅）、画面（帧流订阅）、目标栈（2s 轮询 + 编辑 POST）。
 *
 * 状态只留一个 runId：表单是"提交一次就消失"的临时输入，用不受控
 * defaultValue + FormData，不配 state；编辑失败（终态 409 等）静默。
 * 目标栈栈顶（执行中）锁定：不渲染编辑/删除操作。
 */

/** 主循环节点数：链上 [0, MAIN_END) 是每步必经的主循环，之后是局尾收尾链。
 *  0903 拍板给原本零事件的节点补了轻量"活动"事件（judge/action_space/retrieve/
 *  step/after_action/verify_result，见 `schemas/datastore` 的 EventType），
 *  所以现在链上几乎每个节点都有自己的内容；里程碑推断只兜底
 *  `store_object_semantic_memory`（只在写了新对象时才发事件）这类条件性缺失。
 *  v7 之后主循环占 index 0..16（首位是 `save_checkpoint`），收尾链从 17 起。 */
const MAIN_END = 17;

/**
 * 链的相位表——**与 episode harness 图（`episode_harness._compile`）逐条对齐**：
 * 条数 = 21，`key` 就是 `add_node` 的字符串字面量，顺序就是 `add_node` 的书写顺序
 * （= 执行顺序）。
 *
 * 这条"逐条对齐"不是约定，是断言：`scripts/check_graph_phases.py` 用 `ast` 从
 * `_compile()` 抽出 `add_node` 的字面量列表，与本表的 `key` 列表逐条比对，不一致
 * 就非零退出。这张表曾经停在更早的形状上两个月没人发现（`ROADMAP.md:1136` 那次
 * `verify_and_summarize` 取代 `verify_steps`+`summarize` 只改了代码、没改前端），
 * 所以补了这条机械核对。
 *
 * 内容归属（有事件 ≠ 每格一条）：四个 `retrieve_*` 不各自记事件，检索结果按约定在
 * `merge_retrieval` 汇聚成一条 `memory_read`；`store_object_semantic_memory` 只在真
 * 写了对象时才发 `OBJECT_MEMORY_WRITE`；`note` 给无事件节点一句说明。
 */
const CHAIN_PHASES: { key: string; label: string; note?: string; fromKey?: string }[] = [
  { key: "save_checkpoint", label: "save_checkpoint", note: "链边界存一份（世界快照 + state + 游标）并写 CHECKPOINT_SAVE；未接 checkpoint 时空转、不写账" },
  { key: "record_observation", label: "record_observation", note: "本链开局帧登记成 OBSERVE（带帧）；它不感知" },
  { key: "judge", label: "judge" },
  { key: "get_action_space", label: "get_action_space", note: "零成本事件：这一步允许的动作名" },
  { key: "retrieve_step_episode_memory", label: "retrieve_step_episode_memory", note: "命中摘要（全文在 merge_retrieval 的合并读）" },
  { key: "retrieve_global_episode_memory", label: "retrieve_global_episode_memory", note: "命中摘要（全文在 merge_retrieval 的合并读）" },
  { key: "retrieve_knowledge_semantic_memory", label: "retrieve_knowledge_semantic_memory", note: "命中摘要（全文在 merge_retrieval 的合并读）" },
  { key: "retrieve_object_semantic_memory", label: "retrieve_object_semantic_memory", note: "命中摘要（全文在 merge_retrieval 的合并读）" },
  { key: "merge_retrieval", label: "merge_retrieval", note: "四路汇聚：折 object 进 facts + 记一条合并读 MEMORY_READ" },
  { key: "think_action", label: "think_action" },
  { key: "act", label: "act" },
  { key: "perceive_after_action", label: "perceive_after_action", note: "取帧 + 判读；写 AFTER_ACTION（带帧）；链尾/中止键另有 MODEL_CALL(PERCEPTION)" },
  { key: "apply_stop", label: "apply_stop", note: "按 stop 的作废范围截队；只在真的丢了键时写 ACTION_TRUNCATED" },
  { key: "detect_stall", label: "detect_stall" },
  { key: "store_step_episode_memory", label: "store_step_episode_memory" },
  { key: "store_object_semantic_memory", label: "store_object_semantic_memory", note: "只在写了新对象时发 OBJECT_MEMORY_WRITE" },
  { key: "close_step", label: "close_step", note: "扶正当前帧 + 步号加一；链内小循环的分叉出口" },
  { key: "retrieve_verify_step_memory", label: "retrieve_verify_step_memory", note: "取本局 step 记忆；无 entries 时直接跳 verify_and_summarize" },
  { key: "retrieve_verify_knowledge", label: "retrieve_verify_knowledge", note: "校验用知识检索——仅 judge 判 done 的窗口出现" },
  { key: "verify_and_summarize", label: "verify_and_summarize", note: "一次调用问完两件事：先逐条判可信、再只用可信的蒸馏跨局摘要" },
  { key: "close_episode", label: "close_episode", note: "本局收尾：算 outcome（success / steps / reason）并写 EPISODE_END" },
];

/**
 * 一条 trace 事件归到链上哪个节点。memory_read 有两种读却发同一种事件——
 * 局中 enrich 的合并检索 vs 局尾 verify 的知识检索；区分只能靠"当前窗口里
 * 还有没有 decision 调用"：有（走的是主循环）→ enrich，没有（judge 已 done
 * 走收尾链）→ retrieve_verify_knowledge。
 */
/**
 * 一条 trace 事件归到链上哪个节点。0903 type 收敛后按 (type, payload.kind)
 * 定位；memory_read 两种读的分叉（enrich 合并读 vs 收尾 verify 检索）由
 * kind=read_merge / read_verify_knowledge 直接区分，不再需要窗口启发式。
 */
function phaseKeyOf(t: TraceEvent): string | null {
  const kind = String(t.payload.kind ?? "");
  switch (t.type) {
    case "lifecycle":
      if (kind === "step") return "close_step";
      if (kind === "checkpoint_save") return "save_checkpoint";
      // 本局结算由 `close_episode` 写（v8 之前这一步在图外、没有节点可归）。
      if (kind === "episode_end") return "close_episode";
      return null;
    case "view":
      return kind === "frame" ? "record_observation" : kind === "after" ? "perceive_after_action" : null;
    case "llm_outcome":
      return (
        (kind === "intent" && "think_action") ||
        (kind === "verdict" && "judge") ||
        (kind === "audit" && "verify_and_summarize") ||
        null
      );
    case "act":
      return (
        (kind === "space" && "get_action_space") ||
        (kind === "executed" && "act") ||
        (kind === "stall" && "detect_stall") ||
        (kind === "truncated" && "apply_stop") ||
        null
      );
    case "memory_io":
      switch (kind) {
        case "read_merge":
          return "merge_retrieval";
        case "read_step":
          return "retrieve_step_episode_memory";
        case "read_global":
          return "retrieve_global_episode_memory";
        case "read_knowledge":
          return "retrieve_knowledge_semantic_memory";
        case "read_object":
          return "retrieve_object_semantic_memory";
        case "read_verify_steps":
          return "retrieve_verify_step_memory";
        case "read_verify_knowledge":
          return "retrieve_verify_knowledge";
        case "write_step":
          return "store_step_episode_memory";
        case "write_object":
          return "store_object_semantic_memory";
        case "write_episode":
          return "verify_and_summarize";
        default:
          return null;
      }
    case "model_call":
      // MODEL_CALL 已在专门日志栏列出；这里仍映射到所属节点让节点"点亮"，
      // 内容展示时会被过滤掉、不重复。
      switch (t.source) {
        case "judge":
          return "judge";
        case "decision":
          return "think_action";
        case "perception":
          return "perceive_after_action";
        case "verify":
          return "verify_and_summarize";
        case "memory":
          return "verify_and_summarize";
        default:
          return null;
      }
    default:
      return null;
  }
}

/** 链窗口：一条 OBSERVE（view/frame）起、到下一条前的事件，归到各节点。 */
interface ChainWindow {
  /** 第几局——SSE 的 trace 不带 episode_id，只能数窗口前的 lifecycle/episode_start 事件。 */
  episodeNumber: number;
  step: number;
  /** 节点 key → 该节点在这一步里收到的事件（保持到达顺序；只收有事件的节点）。 */
  phases: Record<string, TraceEvent[]>;
  /** 主循环里最远走到哪：有事件的节点的最大主循环下标（里程碑推断的基准）。 */
  furthestMain: number;
  /** 局尾节点点亮情况（链上每节点现在都有自己的事件，靠 presence 即可）。 */
  endSeen: { rv_step: boolean; rv_knowledge: boolean; verify: boolean };
}

/** 把一段 trace 事件（一条 OBSERVE 的窗口）归到各节点，算元信息。 */
function assembleWindow(
  segment: TraceEvent[],
  episodeNumber: number,
): ChainWindow {
  const phases: Record<string, TraceEvent[]> = {};
  for (const t of segment) {
    const key = phaseKeyOf(t);
    if (key !== null) (phases[key] ??= []).push(t);
  }
  const indexOf = new Map(CHAIN_PHASES.map((ph, i) => [ph.key, i]));
  let furthestMain = -1;
  for (const key of Object.keys(phases)) {
    const i = indexOf.get(key) ?? -1;
    if (i >= 0 && i < MAIN_END && i > furthestMain) furthestMain = i;
  }
  return {
    episodeNumber,
    step: segment[0]?.step ?? 0,
    phases,
    furthestMain,
    endSeen: {
      rv_step: (phases.retrieve_verify_step_memory?.length ?? 0) > 0,
      rv_knowledge: (phases.retrieve_verify_knowledge?.length ?? 0) > 0,
      verify: (phases.verify_and_summarize?.length ?? 0) > 0,
    },
  };
}

/**
 * 把事件流切成**每链一页**的链窗口数组：每条 OBSERVE（view/frame）开一页，收
 * 到下一条前。全部保留、不丢弃——用户可翻回任意历史链看它当时走过
 * 图的哪些节点（0903 拍板：不再"每新 OBSERVE 清空"，改历史翻页）。
 *
 * 一次扫描完成切分：只在 OBSERVE 边界断开，事件本身不复制进多个窗口。
 */
function buildChainWindows(events: SseEvent[]): ChainWindow[] {
  const traces: TraceEvent[] = [];
  const lookIdx: number[] = [];
  for (const ev of events) {
    if (ev.event !== "trace") continue;
    if (ev.data.type === "view" && ev.data.payload.kind === "frame") lookIdx.push(traces.length);
    traces.push(ev.data);
  }
  if (lookIdx.length === 0) return []; // 还没有任何 OBSERVE，链无从画起
  const wins: ChainWindow[] = [];
  let epStart = 0; // 当前窗口起点前有几个 episode_start（窗口序号 = 局号 - 1 的累计）
  let epCount = 0;
  for (let w = 0; w < lookIdx.length; w++) {
    const start = lookIdx[w];
    const end = w + 1 < lookIdx.length ? lookIdx[w + 1] : traces.length;
    // 数本窗口起点前的 episode_start：从上一个已数位置扫到 start。
    for (; epStart < start; epStart++) {
      const t = traces[epStart];
      if (t.type === "lifecycle" && t.payload.kind === "episode_start") epCount++;
    }
    // 每局的 episode_start 事件（`kind === "episode_start"`）在该局第一次
    // OBSERVE 之前就已经写进 trace（`EpisodeHarness._begin` 先发 episode_start
    // 再进 record_observation 节点）——所以扫到这一步时 epCount 已经把"当前正在跑的这一
    // 局"算进去了，是正确的 1-based 局号，不需要再 +1。原来的 `epCount + 1`
    // 让所有局号整体多算一个：第 1 局的第一步显示成"第 2 局"（0903 引入，
    // 用户复现报告"直接从第2局开始"，实测确认）。
    wins.push(assembleWindow(traces.slice(start, end), epCount));
  }
  return wins;
}

/** 从 FormData 读目标的三个字段（goal / criteria / maxSteps）。 */
function readGoalForm(data: FormData) {
  return {
    goal: String(data.get("goal")),
    success_criteria: String(data.get("criteria")),
    max_steps: Number(data.get("maxSteps")),
  };
}

export default function App() {
  // runId 初始值从 URL `?run=<id>` 恢复——runId 只活在 React 内存里，刷新
  // 或重开浏览器就跟运行中的 run 失联了；URL 是刷新后唯一能幸免的载体。
  const [runId, setRunId] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("run"),
  );
  const submitting = useRef(false); // 防双击连发：启动失败已静默，别把 409 当防抖

  const { events, connected } = useRunStream(runId);
  const frameUrl = useFrameStream(runId);
  const review = useReview(runId);
  // 目标栈的任何编辑（追加/行内改/删除）现在跟 review 绑在一起：只有真有
  // 待审查请求时才允许改——用户 0904 明确要求"也改成只有 review 的时候能
  // 改"。`human_note` 不受这条影响（各自独立门控，见 HumanNotePanel）。
  const reviewActive = review !== null && runId !== null;

  // 0904 再改版：目标栈变成纯前端草稿（`draft`），可以完整编辑（含栈顶）。
  // 读写两个独立通道（用户拍板"goals 单独拿出来，一个后端接口"）：
  // 写 = pushGoals()（POST /runs/{id}/goals，整栈原子替换）；
  // 读 = getGoals()（独立的 GET /runs/{id}/goals，不跟 GET /runs/{id} 那个
  // 大而全的状态接口混在一起）。
  //
  // 刷新本地草稿的精确时机：每次看到一条 `Source.PLAN`/`kind=verdict` 的
  // trace 事件（下面 `latestPlanVerdictId`）就重新 getGoals() 一次——这是
  // 后端 `plan()` 节点刚跑完一轮、目标栈刚真正变化的那一刻（可能是刚消费
  // 了上一次 push、也可能是模型自己压的），比之前"review 变 pending"这个
  // 信号精确得多：plan → dispatch/reflect 走完一整个 episode 之后才轮到
  // review，用那个当信号会晚一整个 episode 才刷新。除此之外（包括每次
  // 打开面板、reviewActive 变化）都不动 `draft`——不然会把正在编辑的东西
  // 冲掉。用户拍板：后端中途变了就覆盖本地，因为现在只有人工 review 阶段
  // 能编辑，这个冲突窗口基本不会撞上。
  const [draft, setDraft] = useState<(DraftGoal & { _key: string })[]>([]);

  function toDraft(gs: GoalView[]): (DraftGoal & { _key: string })[] {
    return gs.map((g) => ({
      _key: g.task_id,
      task_id: g.task_id,
      goal: g.goal,
      success_criteria: g.success_criteria,
      max_steps: g.max_steps,
    }));
  }

  // 初次进入 / 换 run：先拉一次目标栈打底（这之后只靠下面的 plan verdict
  // 事件刷新，不再轮询）。
  useEffect(() => {
    if (runId === null) {
      setDraft([]);
      return;
    }
    getGoals({ run_id: runId })
      .then((gs) => setDraft(toDraft(gs)))
      .catch((err) => console.error("getGoals failed:", err));
  }, [runId]);

  const latestPlanVerdictId = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const ev = events[i];
      if (
        ev.event === "trace" &&
        ev.data.type === "llm_outcome" &&
        ev.data.source === "plan" &&
        ev.data.payload.kind === "verdict"
      ) {
        return ev.data.event_id;
      }
    }
    return null;
  }, [events]);
  const lastHandledPlanVerdictRef = useRef<number | null>(null);
  useEffect(() => {
    if (latestPlanVerdictId === null || latestPlanVerdictId === lastHandledPlanVerdictRef.current) return;
    lastHandledPlanVerdictRef.current = latestPlanVerdictId;
    if (runId === null) return;
    getGoals({ run_id: runId })
      .then((gs) => setDraft(toDraft(gs)))
      .catch((err) => console.error("getGoals failed:", err));
  }, [latestPlanVerdictId, runId]);

  // 审查超时提示：本地不知道后端超时秒数是多少（那是 review.deadline_ts 的事），
  // 只知道"上一轮还在、这一轮没了、而且没人在面板里点过按钮"——大概率是
  // REVIEW_TIMEOUT 到点自动兜底成 continue，不是手动提交。纯观感提示，
  // 不影响任何数据流转（后端已经处理完了）。
  const prevReviewRef = useRef<PendingReview | null>(null);
  const reviewSubmittedRef = useRef(false);
  const [timeoutNotice, setTimeoutNotice] = useState(false);
  useEffect(() => {
    const prev = prevReviewRef.current;
    if (review !== null) {
      // 用 outcomes 长度识别"是不是同一轮"——粗糙但够用：每轮 review 必然
      // 对应新弹出一条 outcome。
      if (prev === null || prev.outcomes.length !== review.outcomes.length) {
        reviewSubmittedRef.current = false;
        setTimeoutNotice(false);
      }
    } else if (prev !== null && !reviewSubmittedRef.current) {
      setTimeoutNotice(true);
      const timer = setTimeout(() => setTimeoutNotice(false), 4000);
      prevReviewRef.current = review;
      return () => clearTimeout(timer);
    }
    prevReviewRef.current = review;
  }, [review]);

  async function handleStart(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    const data = new FormData(e.currentTarget);
    try {
      const resp = await startRun({ goals: [readGoalForm(data)] });
      setRunId(resp.run_id); // 表单随之卸载，submitting 随组件一起作废
    } catch (err) {
      // 用户拍板：启动失败（单进程 409 等）静默，不需要 UI——console 留痕便于排查
      console.error("startRun failed:", err);
    } finally {
      submitting.current = false;
    }
  }

  // 0904 再改版：以下三个都是纯本地草稿操作，不再直接打后端——只有
  // handlePushGoals（"推送到后端"）才会真正发请求。
  function handleDraftAdd(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const g = readGoalForm(new FormData(e.currentTarget));
    setDraft((prev) => [...prev, { _key: `local-${Date.now()}-${Math.random()}`, ...g }]);
    e.currentTarget.reset();
  }

  function handleDraftRemove(key: string) {
    setDraft((prev) => prev.filter((g) => g._key !== key));
  }

  function handleDraftReplace(e: React.FormEvent<HTMLFormElement>, key: string) {
    e.preventDefault();
    const g = readGoalForm(new FormData(e.currentTarget));
    setDraft((prev) => prev.map((row) => (row._key === key ? { ...row, ...g } : row)));
  }

  async function handlePushGoals() {
    if (runId === null) return;
    try {
      await pushGoals(
        runId,
        draft.map(({ _key, ...rest }) => rest),
      );
    } catch (err) {
      console.error("push goals failed:", err);
    }
  }

  return (
    <div style={styles.app}>
      <h1 style={styles.title}>Pokemon Agent · 观测台</h1>

      {/* 启动区：没有 run 时是表单；有 run 时只显示 run_id */}
      {runId === null ? (
        <form onSubmit={handleStart} style={styles.form}>
          <label style={styles.field}>
            目标
            <input name="goal" defaultValue="向上走，直到进入宝可梦中心" required style={styles.input} />
          </label>
          <label style={styles.field}>
            成功判据
            <input name="criteria" defaultValue="已进入宝可梦中心" required style={styles.input} />
          </label>
          <label style={styles.field}>
            步数上限
            <input
              name="maxSteps" type="number" min={1} defaultValue={8} required style={styles.input}
            />
          </label>
          <button type="submit" style={styles.button}>启动 run</button>
        </form>
      ) : (
        <div style={styles.banner}>
          run: <code>{runId}</code>
        </div>
      )}

      {runId !== null && !connected && (
        <div style={styles.disconnectedBanner}>事件流已断开，浏览器正在自动重连…</div>
      )}
      {timeoutNotice && (
        <div style={styles.timeoutBanner}>上一轮审查已超时，自动按 continue 处理</div>
      )}

      {/* 观测区：左画面+目标栈；右链。model_call 日志栏挪到页面最下面（见下） */}
      <div style={styles.grid}>
        <section style={styles.panel}>
          <h2 style={styles.section}>实时画面</h2>
          <div style={styles.screenBox}>
            {frameUrl !== null ? (
              <img src={frameUrl} alt="游戏实时画面" style={styles.screen} />
            ) : (
              <div style={styles.placeholder}>画面未连接</div>
            )}
          </div>

          <h2 style={styles.section}>目标栈（{draft.length}）</h2>
          {/* 0904 再改版：目标栈变成纯前端草稿——不再是 useRunGoals 轮询结果的只读
              渲染。栈顶（数组最后一项）现在也能编辑，`reviewActive` 时才解锁，
              跟其他行一样；真正落到后端要等下面"推送到后端"按钮。 */}
          {draft.map((g, i) => (
            <GoalRow
              key={g._key}
              goal={g}
              isTop={i === draft.length - 1}
              disabled={!reviewActive}
              onRemove={handleDraftRemove}
              onReplace={handleDraftReplace}
            />
          ))}
          {draft.length === 0 && <div style={styles.placeholder}>目标栈为空</div>}

          {/* 0904 改版：追加目标表单从这里挪进下面那一个框，跟"人工审查"
              框在一起，用同一条 `reviewActive` 门控——用户要求"也改成只有
              review 的时候能改，和 review 单独一起用框框起来"。0904 再改版：
              这里的"追加"现在只是往本地草稿 append 一行，不再直接打后端；
              草稿要落地得靠下面"推送到后端"按钮（sync，整栈原子替换）。 */}
          <section style={{ ...styles.reviewPanel, opacity: reviewActive ? 1 : 0.55 }}>
            <h2 style={styles.section}>{reviewActive ? "人工审查" : "无待审查"}</h2>
            <form onSubmit={handleDraftAdd} style={styles.form}>
              <label style={styles.field}>
                追加目标（本地）
                <input name="goal" placeholder="新目标" required disabled={!reviewActive} style={styles.input} />
              </label>
              <label style={styles.field}>
                判据
                <input name="criteria" placeholder="成败判据" required disabled={!reviewActive} style={styles.input} />
              </label>
              <label style={styles.field}>
                步数
                <input
                  name="maxSteps" type="number" min={1} defaultValue={8} required
                  disabled={!reviewActive} style={styles.input}
                />
              </label>
              <button type="submit" style={styles.button} disabled={!reviewActive}>加到草稿</button>
            </form>
            <button
              type="button" onClick={handlePushGoals} disabled={!reviewActive}
              style={{ ...styles.button, marginBottom: 12 }}
            >
              推送目标栈到后端
            </button>
            <ReviewPanel
              review={review}
              runId={runId}
              onSubmit={() => {
                reviewSubmittedRef.current = true;
              }}
            />
          </section>

          <h2 style={styles.section}>人类实时插话</h2>
          <HumanNotePanel runId={runId} />
        </section>

        <section style={styles.panel}>
          <ChainPanel events={events} />
        </section>
      </div>

      {/* model_call 日志栏：0905 再改版——从右侧栏挪到页面最下面，用 <details>
          折叠、默认收起，不起眼（用户要求"移到最下面，不起眼"）。内容/数据
          来源不变，只是位置和默认可见性变了。 */}
      <details style={styles.modelCallDetails}>
        <summary style={styles.modelCallSummary}>model_call 日志</summary>
        <ModelCallPanel events={events} />
      </details>
    </div>
  );
}

/**
 * 人工审查面板：0904 改版——**常驻渲染**，不再"没有待审查就整块消失"。
 * `review === null`（没有待审查请求）时四个决策按钮全部 `disabled`，"插入
 * 新目标"的展开表单也不让打开；`review` 非空时正常可操作，行为跟改版前
 * 完全一样（outcomes/last_task 给判断依据，push 复用 `readGoalForm`）。
 * `runId === null`（还没启动 run）同样禁用——没有 run 谈不上审查。
 *
 * **不自带边框/标题**（0904 二次改版）：调用方（`App`）现在把这个组件跟
 * "追加目标"表单放进同一个外层框（`reviewActive` 门控、`人工审查`/`无待
 * 审查`标题都在外层），这里再包一层会变成"框中框、标题重复两遍"，所以
 * 这里只吐内容，边框和标题交给调用方。
 *
 * 倒计时纯展示：真正的超时兜底在后端（`REVIEW_TIMEOUT`），这里只是把
 * `review.deadline_ts` 换算成"还剩几秒"，`review` 为 null 或 `deadline_ts`
 * 为 null（未启用阻塞审查）时都不显示倒计时。
 */
function ReviewPanel(props: { review: PendingReview | null; runId: string | null; onSubmit: () => void }) {
  const { review, runId, onSubmit } = props;
  const [remaining, setRemaining] = useState<number | null>(null);
  const disabled = review === null || runId === null;

  useEffect(() => {
    if (review === null || review.deadline_ts === null) {
      setRemaining(null);
      return;
    }
    const tick = () => setRemaining(Math.max(0, review.deadline_ts! - Date.now() / 1000));
    tick();
    const timer = setInterval(tick, 500);
    return () => clearInterval(timer);
  }, [review]);

  // 0904 简化：review 的 push 决策已删——加/改/删目标现在统一走"目标栈"
  // 那个框（本地草稿 + 推送到后端），跟这里的 continue/stop/retry 分开。
  async function decide(decision: HumanDecision) {
    if (disabled || runId === null) return;
    onSubmit();
    try {
      await submitReview({ run_id: runId, decision });
    } catch (err) {
      // 来晚了（409，后端已经超时兜底掉了）也好、别的错误也好——静默：
      // 下一轮轮询会把面板状态收敛回正确的样子。
      console.error("submitReview failed:", err);
    }
  }

  const last = review?.last_task ?? null;

  return (
    <>
      {remaining !== null && (
        <div style={styles.countdown}>{remaining.toFixed(0)}s 后自动 continue</div>
      )}
      {last !== null && (
        <div style={styles.placeholder}>
          刚跑完：{last.goal}（{last.success_criteria}，{last.max_steps} 步）
        </div>
      )}
      {review !== null && (
        <ul style={styles.list}>
          {review.outcomes.map((o) => (
            <li key={o.episode_id} style={styles.item}>
              [{o.success ? "成功" : "失败"}] {o.episode_id} · {o.steps} 步 · {o.reason}
            </li>
          ))}
        </ul>
      )}
      <div style={styles.form}>
        <button style={styles.button} disabled={disabled} onClick={() => decide("continue")}>继续</button>
        <button style={styles.buttonDanger} disabled={disabled} onClick={() => decide("stop")}>停止</button>
        <button style={styles.buttonSmall} disabled={disabled} onClick={() => decide("retry")}>重试上一层</button>
      </div>
    </>
  );
}

/**
 * 人类实时插话面板（0904 新增）：一个文本框 + 发送按钮，`POST /runs/{id}/note`。
 * **永远可操作，不受 `review` 状态门控**——这是它跟上面 `ReviewPanel` 唯一
 * 但也是最重要的区别：episode 内每一步都可能想插一句话，不需要、也不应该
 * 等"正好有一轮审查待处理"才能发。只在 `runId === null`（还没启动 run）时
 * 禁用——没有 run 没有地方可插。
 *
 * 一次性语义（跟后端槽位一致）：发送后清空输入框，不保留"上一次插了什么"
 * 的展示——它只对下一次决策生效，展示历史容易让人误以为还在持续生效。
 */
function HumanNotePanel(props: { runId: string | null }) {
  const { runId } = props;
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [justSent, setJustSent] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (runId === null || text.trim() === "" || sending) return;
    setSending(true);
    try {
      await submitHumanNote({ run_id: runId, text: text.trim() });
      setText("");
      setJustSent(true);
      setTimeout(() => setJustSent(false), 2000);
    } catch (err) {
      console.error("submitHumanNote failed:", err);
    } finally {
      setSending(false);
    }
  }

  const disabled = runId === null;

  return (
    <section style={{ ...styles.reviewPanel, opacity: disabled ? 0.55 : 1 }}>
      <form onSubmit={handleSubmit} style={styles.form}>
        <label style={{ ...styles.field, flex: 1 }}>
          插一句话（下一步生效，最高优先级，一次性）
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="例如：别管这个 NPC 了，直接往右走出这个房间"
            disabled={disabled}
            style={styles.input}
          />
        </label>
        <button type="submit" style={styles.button} disabled={disabled || sending || text.trim() === ""}>
          发送
        </button>
      </form>
      {justSent && <div style={styles.placeholder}>已发送，下一步决策会读到</div>}
    </section>
  );
}

/**
 * 当前链轨迹链（历史翻页）：每条链一页，页 = 该条 OBSERVE 起的事件归到 20 个节点。
 * 页标签栏列出全部历史步（局·step），点标签切到那一页；没有手动翻页时自动
 * 跟随最新页。链节点点击钉住看内容、再点取消；翻页时清空钉住。
 */
function ChainPanel(props: { events: SseEvent[] }) {
  const { events } = props;
  const wins = useMemo(() => buildChainWindows(events), [events]);
  // page = 用户翻到第几页（wins 下标）；null = 自动跟随最新页。手动翻页后停
  // 在那一页（新 OBSERVE 不打断阅读），按 End 或点"回到最新"跳回。
  const [page, setPage] = useState<number | null>(null);
  // pinned = 用户点过哪个节点；null = 自动跟随。翻页时清空。
  const [pinned, setPinned] = useState<string | null>(null);
  useEffect(() => {
    setPinned(null);
  }, [page, wins.length]);

  // 键盘翻页：← 上一页 / → 下一页（或最新一页再按 → 跟随最新）/
  // Home 第一页 / End 回到最新。翻页时清掉钉住的节点。
  useEffect(() => {
    if (wins.length === 0) return;
    const onKey = (ev: KeyboardEvent) => {
      const lastIdx = wins.length - 1;
      const cur = page ?? lastIdx;
      if (ev.key === "ArrowLeft") {
        setPinned(null);
        setPage(cur > 0 ? cur - 1 : 0);
      } else if (ev.key === "ArrowRight") {
        setPinned(null);
        setPage(cur < lastIdx ? cur + 1 : null); // 已到最新 → 跟随最新
      } else if (ev.key === "Home") {
        setPinned(null);
        setPage(0);
      } else if (ev.key === "End") {
        setPinned(null);
        setPage(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [wins.length, page]);

  if (wins.length === 0) {
    return (
      <div style={styles.subPanel}>
        <h2 style={styles.section}>当前步轨迹</h2>
        <div style={styles.placeholder}>等第一条观测…</div>
      </div>
    );
  }

  // 当前看的页：手动翻页则停在那，否则自动跟随最新（wins 尾部）。
  const last = wins.length - 1;
  const shown = page ?? last;
  const win = wins[shown];
  const following = page === null || page === last;

  const indexOf = new Map(CHAIN_PHASES.map((ph, i) => [ph.key, i]));
  // 自动跟随目标 = 有事件的节点里链序最靠后的（主循环已走完时局尾节点优先）。
  let autoKey: string | null = null;
  let autoIdx = -1;
  for (const key of Object.keys(win.phases)) {
    const i = indexOf.get(key) ?? -1;
    if (i > autoIdx) {
      autoIdx = i;
      autoKey = key;
    }
  }
  const shownKey = pinned ?? autoKey;
  const shownDef = shownKey !== null ? CHAIN_PHASES[indexOf.get(shownKey) ?? -1] : undefined;

  const litOf = (key: string, idx: number): boolean => {
    if (idx < MAIN_END) return idx <= win.furthestMain;
    return (
      (key === "retrieve_verify_step_memory" && win.endSeen.rv_step) ||
      (key === "retrieve_verify_knowledge" && win.endSeen.rv_knowledge) ||
      (key === "verify_and_summarize" && win.endSeen.verify)
    );
  };

  const shownEvents = shownDef
    ? (win.phases[shownDef.fromKey ?? shownDef.key] ?? []).filter(
        // MODEL_CALL 的账（tokens/raw）已单独归 model_call 日志栏，节点内容
        // 只展示它自己的活动事件。
        (t) => t.type !== "model_call",
      )
    : [];
  const raw = shownEvents
    .map((t) => `#${t.event_id} [${t.type}] ${t.source}\n${JSON.stringify(t.payload, null, 2)}`)
    .join("\n\n");

  return (
    <div style={styles.subPanel}>
      <h2 style={styles.section}>
        当前步轨迹 · 第 {win.episodeNumber} 局 · step {win.step} ·{" "}
        {Math.max(0, win.furthestMain + 1)}/{MAIN_END} 主循环节点
      </h2>
      {/* 翻页器：◀ 上一页 / 页码（局·step 与页位置）/ 下一页 ▶，支持键盘 ← →。
          Home=第一页、End=回到最新（用户 0903 拍板：按键翻页，不是点标签激活）。 */}
      <div style={styles.pager}>
        <button
          type="button"
          style={styles.pagerBtn}
          onClick={() => {
            setPinned(null);
            setPage(shown > 0 ? shown - 1 : 0);
          }}
          title="上一页（←）"
        >
          ◀
        </button>
        <div style={styles.pagerInfo}>
          {following ? "最新" : `历史 ${shown + 1}/${wins.length}`} · 第{" "}
          {win.episodeNumber} 局 · step {win.step}
        </div>
        <button
          type="button"
          style={styles.pagerBtn}
          onClick={() => {
            setPinned(null);
            setPage(shown < last ? shown + 1 : null); // 已到最新 → 跟随最新
          }}
          title="下一页（→）"
        >
          ▶
        </button>
        {!following && (
          <button
            type="button"
            style={styles.pagerBtn}
            onClick={() => {
              setPinned(null);
              setPage(null);
            }}
            title="回到最新（End）"
          >
            ⤓ 最新
          </button>
        )}
      </div>
      <div style={styles.chain}>
        {CHAIN_PHASES.map((ph, idx) => {
          const lit = litOf(ph.key, idx);
          const bg = !lit ? "#2a2a2a" : ph.key === shownKey ? "#378ADD" : "#0F6E56";
          return (
            <button
              key={ph.key}
              type="button"
              onClick={() => setPinned(pinned === ph.key ? null : ph.key)}
              style={{ ...styles.bead, background: bg, opacity: lit ? 1 : 0.5 }}
              title={lit ? (ph.note ?? `${ph.label} 的内容`) : "此步未走到该节点"}
            >
              {ph.label}
            </button>
          );
        })}
      </div>
      <div style={styles.chainHint}>
        {pinned === null
          ? `自动跟随 ${autoKey ?? "…"} · 点节点查看 · 键盘 ←/→ 翻页，End 回最新`
          : `已钉住 ${pinned} · 再点一次回到自动跟随`}
      </div>
      {shownDef === undefined || (!shownEvents.length && !shownDef.note) ? (
        <div style={styles.placeholder}>该节点此步没有事件可看</div>
      ) : (
        <div>
          {shownDef.note && <div style={styles.chainHint}>{shownDef.note}</div>}
          {shownEvents.length > 0 ? (
            <pre style={styles.rawBlock}>{raw}</pre>
          ) : (
            <div style={styles.placeholder}>该节点无独立 trace 事件（纯本地计算 / 合并读见 merge_retrieval）</div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * model_call 日志栏：全部模型调用的账（谁调的、几次尝试、token、raw）集中一处，
 * 不再混在链节点内容里（用户 0903 拍板"model_call 的 trace 单独放到一个 log 栏"）。
 * 链节点只显示它自己的活动事件；raw 在这里按到达顺序倒序滚动。
 */
function ModelCallPanel(props: { events: SseEvent[] }) {
  const { events } = props;
  const calls = useMemo(
    () =>
      events.filter(
        (e): e is Extract<SseEvent, { event: "trace" }> =>
          e.event === "trace" && e.data.type === "model_call",
      ),
    [events],
  );
  return (
    <div style={{ ...styles.subPanel, marginTop: 12 }}>
      <h2 style={styles.section}>model_call（{calls.length}）</h2>
      {calls.length === 0 ? (
        <div style={styles.placeholder}>暂无模型调用</div>
      ) : (
        <ul style={styles.list}>
          {[...calls].reverse().map((ev) => (
            <li key={`mc-${ev.data.event_id}`} style={styles.item}>
              <pre style={styles.rawBlock}>
                {`#${ev.data.event_id} [${ev.data.source}] step ${ev.data.step}\n${JSON.stringify(ev.data.payload, null, 2)}`}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 目标栈的一行：0904 再改版——目标栈是纯前端草稿，栈顶不再只读，跟其他
 *  行一样可编辑/删除（只是保留一个"执行中"标记，提醒这项目前是后端正在
 *  跑的那个，改了要等下次"推送到后端"才生效）。`disabled` 时（没有待审查
 *  请求）行内表单/按钮全部禁用。用 `_key` 定位（本地新增行没有 task_id）。 */
function GoalRow(props: {
  goal: DraftGoal & { _key: string };
  isTop: boolean;
  disabled: boolean;
  onRemove: (key: string) => void;
  onReplace: (e: React.FormEvent<HTMLFormElement>, key: string) => void;
}) {
  const { goal, isTop, disabled, onRemove, onReplace } = props;
  return (
    <form onSubmit={(e) => onReplace(e, goal._key)} style={styles.goalRow}>
      {isTop && <span style={styles.goalTop}>→ 执行中</span>}
      <input name="goal" defaultValue={goal.goal} disabled={disabled} style={styles.inputInline} title="目标" />
      <input
        name="criteria" defaultValue={goal.success_criteria} disabled={disabled}
        style={styles.inputInline} title="判据"
      />
      <input
        name="maxSteps" type="number" min={1} defaultValue={goal.max_steps} disabled={disabled}
        style={styles.inputSmall} title="步数"
      />
      <button type="submit" style={styles.buttonSmall} disabled={disabled}>保存</button>
      <button
        type="button" onClick={() => onRemove(goal._key)} disabled={disabled}
        style={styles.buttonDanger}
      >
        删除
      </button>
    </form>
  );
}

const styles: Record<string, React.CSSProperties> = {
  app: { maxWidth: 1300, margin: "0 auto", padding: 16 },
  title: { fontSize: 20, margin: "0 0 12px" },
  form: { display: "flex", gap: 12, flexWrap: "wrap", alignItems: "end", marginBottom: 16 },
  field: { display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "#aaa" },
  input: {
    background: "#222", color: "#e6e6e6", border: "1px solid #444",
    borderRadius: 6, padding: "6px 8px", minWidth: 180,
  },
  button: {
    background: "#378ADD", color: "#fff", border: "none", borderRadius: 6,
    padding: "8px 18px", cursor: "pointer",
  },
  banner: { background: "#222", border: "1px solid #444", borderRadius: 8, padding: "8px 12px", marginBottom: 16 },
  reviewPanel: {
    background: "#2a2110", border: "1px solid #6b551f", borderRadius: 10,
    padding: 12, marginBottom: 16,
  },
  countdown: { color: "#E0B84A", fontSize: 12, fontWeight: 400 },
  timeoutBanner: {
    background: "#332616", border: "1px solid #6b551f", borderRadius: 8,
    padding: "8px 12px", marginBottom: 16, color: "#E0B84A", fontSize: 13,
  },
  disconnectedBanner: {
    background: "#331a1a", border: "1px solid #6b2f2f", borderRadius: 8,
    padding: "8px 12px", marginBottom: 16, color: "#E07A7A", fontSize: 13,
  },
  grid: { display: "grid", gridTemplateColumns: "380px 1fr", gap: 16 },
  modelCallDetails: { marginTop: 16, color: "#666", fontSize: 12 },
  modelCallSummary: { cursor: "pointer", color: "#666", fontSize: 12, userSelect: "none" },
  panel: { background: "#222", border: "1px solid #333", borderRadius: 10, padding: 12 },
  section: { fontSize: 14, margin: "0 0 8px", color: "#ccc" },
  screenBox: { display: "flex", justifyContent: "center", background: "#111", borderRadius: 8, padding: 8 },
  screen: { width: "100%", imageRendering: "pixelated" },
  placeholder: { padding: "12px 0", color: "#666", fontSize: 13 },
  goalRow: {
    display: "flex", gap: 6, alignItems: "center", padding: "4px 0",
    borderBottom: "1px solid #2a2a2a", fontSize: 12,
  },
  goalTop: { color: "#97C459", fontWeight: 500, whiteSpace: "nowrap" },
  goalText: { color: "#e6e6e6", wordBreak: "break-all" },
  goalMeta: { color: "#888", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
  inputInline: {
    background: "#1a1a1a", color: "#e6e6e6", border: "1px solid #444",
    borderRadius: 4, padding: "3px 6px", fontSize: 12, flex: 1, minWidth: 0,
  },
  inputSmall: {
    background: "#1a1a1a", color: "#e6e6e6", border: "1px solid #444",
    borderRadius: 4, padding: "3px 6px", fontSize: 12, width: 56,
  },
  buttonSmall: {
    background: "#0F6E56", color: "#fff", border: "none", borderRadius: 4,
    padding: "3px 10px", fontSize: 12, cursor: "pointer", whiteSpace: "nowrap",
  },
  buttonDanger: {
    background: "#A32D2D", color: "#fff", border: "none", borderRadius: 4,
    padding: "3px 10px", fontSize: 12, cursor: "pointer", whiteSpace: "nowrap",
  },
  // 右栏单步轨迹链（步历史翻页版，用户 0903 拍板）：翻页器 + 相位圆点横排 +
  // 下方 raw 详情。每步一页、全部保留，键盘/按钮翻页回看历史步；点节点切内容。
  pager: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 },
  pagerBtn: {
    border: "1px solid #444", borderRadius: 8, padding: "3px 10px",
    fontSize: 12, cursor: "pointer", color: "#ddd", background: "#222",
  },
  pagerInfo: { fontSize: 12, color: "#aaa", fontFamily: "monospace", flex: 1 },
  chain: { display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 },
  bead: {
    border: "1px solid #444", borderRadius: 12, padding: "4px 10px",
    fontSize: 11, cursor: "pointer", color: "#e6e6e6", fontFamily: "monospace",
  },
  chainHint: { fontSize: 11, color: "#666", marginBottom: 6 },
  rawBlock: {
    background: "#111", border: "1px solid #2f2f2f", borderRadius: 6, padding: 8,
    fontFamily: "monospace", fontSize: 11, lineHeight: 1.4, color: "#bbb",
    whiteSpace: "pre-wrap", wordBreak: "break-all",
    maxHeight: 420, overflowY: "auto", margin: 0,
  },
  subPanel: { background: "#1a1a1a", border: "1px solid #2f2f2f", borderRadius: 8, padding: 10 },
  list: { listStyle: "none", margin: 0, padding: 0, maxHeight: 280, overflowY: "auto" },
  item: {
    padding: "4px 0", borderBottom: "1px solid #2a2a2a", fontSize: 12,
    fontFamily: "monospace", color: "#bbb", wordBreak: "break-all",
  },
};
