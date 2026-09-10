/**
 * 从后端 schema（pokemon_agent/schemas/communication/）翻译的 TS 类型。
 * 只放"前端要消费"的形状，不逐字翻译——后端会变的字段以这里为准对接。
 *
 * review 相关类型对应后端 human_review.py：`RunDataCenter` 统一了前后端
 * 交互中间层之后，人工审查有了真实传输层（GET/POST /runs/{id}/review），
 * 不再是 harness 阶段性自动 CONTINUE 的占位桩。这里只翻译数据形状；审查
 * 面板 UI（组件/交互）是后续任务。
 */

/** POST /runs 的单个目标（对应后端 GoalIn / TaskForHarness）。 */
export interface Goal {
  goal: string;
  success_criteria: string;
  max_steps: number;
  initial_state_hint?: string;
}

/** Runs的启动函数，run_id可以留空 */
export interface StartRunReq{
  run_id?: string;
  goals: Goal[];
}

export interface StartRunResp{
  run_id: string;
  status: string;
}

export interface GetRunReq{
  run_id: string;
}

/** GET /runs/{id} 的响应（RunStatus）。 */
export interface GetRunResp {
  run_id: string;
  status: "running" | "done" | "failed" | "stopped";
  event_count: number;
  outcome: RunOutcome | null;
  error: string | null;
  /** 当前目标栈（栈底 → 栈顶，top = 正在执行的那个）。 */
  goals: GoalView[];
  /** 有没有待处理的审查请求——true 时拉 GET /runs/{id}/review 取详情。 */
  review_pending: boolean;
}

/** 目标栈里一条目标的观测视图（GET /runs/{id} 的 goals 元素）。 */
export interface GoalView {
  task_id: string;
  goal: string;
  success_criteria: string;
  max_steps: number;
  /** true = 栈顶（正在执行）。栈顶锁定：不可 remove/replace。 */
  top: boolean;
}

/** 目标栈里一条草稿目标：task_id 缺省 = 本地新增的目标（尚未跟后端同步过）。 */
export interface DraftGoal extends Goal {
  task_id?: string;
}

/**
 * 运行时目标栈编辑（POST /runs/{id}/goals）：整栈原子替换，不锁栈顶——
 * 前端把目标栈当纯本地草稿编辑（含栈顶），点 push 时把整份草稿一次性
 * 同步过去，已有 task_id 的项保留（从而保留 attempts 计数），新项留空
 * 由后端生成。
 *
 * 0904 简化：曾经还有 push/remove/replace 三种按 task_id 定位的增量 kind，
 * 前端改造成纯本地草稿后已经没有调用点，用户确认删掉，只剩这一种。
 */
export interface GoalsEditReq {
  run_id: string;
  /** 完整新目标栈（栈顶=最后一项）。 */
  goals: DraftGoal[];
}

export interface GoalsEditResp {
  accepted: boolean;
}

/** run 结算（RunOutcomeResp）。 */
export interface RunOutcome {
  total: number;
  succeeded: number;
  failed: number;
}

/**
 * SSE /runs/{id}/events 的消息。前端消费其中三类：
 *  - trace : 一条 TraceEvent（带 event_id，断线补发协议的地基）
 *  - done  : run 结束（随后关流）
 *  - error : run 异常（随后关流）
 * 后端还会推 review 消息，当前阶段前端不注册它的 listener，收不到即忽略。
 * discriminated union：按 event 收窄 payload 类型。
 */
export type SseEvent =
  | { event: "trace"; id: string | null; data: TraceEvent }
  | { event: "done"; id: null; data: RunOutcome }
  | { event: "error"; id: null; data: { message: string } };

/** trace 事件的通用字段（后端 TraceEvent 的超集，只取前端展示用）。
 *  注意字段是 `type`（EventType 枚举的字符串值），不是 `event_type`——
 *  当初翻译错名字，事件列表一直显示 `[undefined]`。 */
export interface TraceEvent {
  event_id: number;
  step: number;
  type: string;
  source: string;
  payload: Record<string, unknown>;
}

/** SSE /runs/{id}/frames 单条 frame 消息的 data（base64 PNG）。 */
export interface FramePushResp {
  frame_png: string;
}

/** 人类（或未来的 LLM reviewer）对一轮审查的决策（对应后端 HumanDecision）。
 *  0904 简化：`push` 决策已删——加/改/删目标现在统一走
 *  `POST /runs/{id}/goals`（见 GoalsEditReq），跟这里分开。 */
export type HumanDecision = "continue" | "stop" | "retry";

/**
 * GET /runs/{id}/review 的响应：待处理的审查请求（对应后端
 * HumanReviewReqFromHarness），没有待处理请求时是 null。
 *
 * `episode_trace` 是刚跑完那一局的**完整** trace（不是全量 run trace）——
 * 一次请求自带审查所需的全部依据，不用再额外拉一次事件流历史。
 */
export interface PendingReview {
  run_id: string;
  outcomes: { episode_id: string; success: boolean; steps: number; reason: string }[];
  goals: GoalView[];
  last_task: GoalView | null;
  episode_trace: TraceEvent[];
  /** 这一轮审查的截止时间戳（`Date.now()/1000` 口径，秒）——超过就会被后端
   *  自动兜底成 continue。`POKEMON_REVIEW_TIMEOUT <= 0`（不阻塞）时为 null，
   *  前端不用渲染倒计时。 */
  deadline_ts: number | null;
}

/** POST /runs/{id}/review 的请求体（对应后端 HumanReviewRespFromFrontend）。 */
export interface ReviewSubmitReq {
  run_id: string;
  decision: HumanDecision;
}

export interface ReviewSubmitResp {
  accepted: boolean;
}

/**
 * POST /runs/{id}/note 的请求体（对应后端 HumanNoteReq，0904 新增）：
 * episode 内实时插话，episode 内下一次决策（think_action）会当成最高优先级
 * 指令读到一次（取到即清空），只对那一次生效——要一直提醒得再发一次。
 * 跟 review 是完全独立的两条通道：不受 review_pending 状态影响，任何时候
 * 都能发。
 */
export interface HumanNoteReq {
  run_id: string;
  text: string;
}

export interface HumanNoteResp {
  accepted: boolean;
}
