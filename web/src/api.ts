/**
 * 后端 HTTP/SSE 面的客户端封装。只做"发请求、建连接、按类型分发消息"，
 * 不做任何状态管理——状态归 hooks（useRunStream / useFrameStream）。
 *
 * 约定：每个对外函数的输入是 `XxxReq`、输出是 `XxxResp`（SSE 订阅的"输出"
 * 是活连接本身，关流靠它）。Req/Resp 形状全部定义在 types.ts，这里不重复。
 *
 * 路径全部是相对路径：dev 下由 vite 代理转发到 127.0.0.1:8000（见 vite.config.ts），
 * 生产下由静态托管层保证同源。前端代码不出现后端 host。
 */

import type {
  DraftGoal,
  FramePushResp,
  GetRunReq,
  GetRunResp,
  GoalsEditResp,
  GoalView,
  HumanNoteReq,
  HumanNoteResp,
  PendingReview,
  ReviewSubmitReq,
  ReviewSubmitResp,
  RunMetrics,
  SseEvent,
  StartRunReq,
  StartRunResp,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    // 朴素版：后端 HTTPException 的 detail 足够定位（404/409/422），先不做错误分类。
    throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

/** 启动一个 run。后端单进程单 run，并发会拿到 409——由调用方决定如何呈现。 */
export function startRun(req: StartRunReq): Promise<StartRunResp> {
  return request("/runs", { method: "POST", body: JSON.stringify(req) });
}

/** 查询 run 状态与结算（轮询/兜底用；常规实时数据走 SSE）。 */
export function getRun(req: GetRunReq): Promise<GetRunResp> {
  return request(`/runs/${req.run_id}`);
}

/** 目标栈单独的读接口（0904 拍板"goals 单独拿出来，一个后端接口"）——
 *  跟 `pushGoals` 配对，不跟 `GET /runs/{id}` 那个大而全的状态接口混在
 *  一起。前端在看到一条 plan verdict trace 事件时调这个刷新本地草稿。 */
export function getGoals(req: GetRunReq): Promise<GoalView[]> {
  return request(`/runs/${req.run_id}/goals`);
}

/** goal 的 push：把本地整份目标草稿（含栈顶）一次性原子同步到后端，不锁
 *  栈顶——0904 简化：现在只保留两个通道，这个（goal 的 push）+ goals 的
 *  read（独立的 `getGoals()`/`GET /runs/{id}/goals`），`remove`/`replace`
 *  以及 review 自己的 `push` 决策都已删，不再撞名。 */
export function pushGoals(runId: string, goals: DraftGoal[]): Promise<GoalsEditResp> {
  return request(`/runs/${runId}/goals`, {
    method: "POST",
    body: JSON.stringify({ goals }),
  });
}

/** 查当前待处理的审查请求（GET /runs/{id} 的 review_pending 为 true 时拉这个取详情）。 */
export function getPendingReview(req: GetRunReq): Promise<PendingReview | null> {
  return request(`/runs/${req.run_id}/review`);
}

/** 提交这一轮审查的决策（POST /runs/{id}/review）；没有待处理请求时后端给 409。 */
export function submitReview(req: ReviewSubmitReq): Promise<ReviewSubmitResp> {
  const { run_id, ...body } = req;
  return request(`/runs/${run_id}/review`, { method: "POST", body: JSON.stringify(body) });
}

/** 提交一条人类实时插话（POST /runs/{id}/note）——非阻塞单槽，最新一条覆盖
 *  旧的、还没被 episode 内 think_action 取走的；跟 review 无关，任何时候都
 *  能发，不需要等有待审查请求。 */
export function submitHumanNote(req: HumanNoteReq): Promise<HumanNoteResp> {
  const { run_id, ...body } = req;
  return request(`/runs/${run_id}/note`, { method: "POST", body: JSON.stringify(body) });
}

/** 查实时聚合报表（GET /runs/{id}/metrics）——run 还在跑也能查，看到的是到
 *  目前为止的数字，不用等 run 结束。`docs/ROADMAP.md` 第 2 条"可观测"第二拍。 */
export function getMetrics(req: GetRunReq): Promise<RunMetrics> {
  return request(`/runs/${req.run_id}/metrics`);
}

/**
 * 订阅事件流（/runs/{id}/events），把三类 SSE 消息解析成 types.ts 的 SseEvent
 * 后回调 onMessage——调用方拿到的是已收窄的判别联合，不用自己 JSON.parse。
 *
 * 断线重连不用手动写：浏览器原生 EventSource 重连时自动带 Last-Event-ID 头，
 * 后端按它补发缺失的 trace 事件——这正是 SSE 协议内建的补发通道。
 * 返回的 EventSource 由调用方持有并负责 close（换 run / 卸载组件时）。
 */
const parse = (e: MessageEvent) => JSON.parse(e.data);

export function subscribeEvents(req: GetRunReq, onMessage: (ev: SseEvent) => void): EventSource {
  const es = new EventSource(`/runs/${req.run_id}/events`);
  es.addEventListener("trace", (e: MessageEvent) =>
    onMessage({ event: "trace", id: e.lastEventId || null, data: parse(e) }),
  );
  es.addEventListener("done", (e: MessageEvent) => onMessage({ event: "done", id: null, data: parse(e) }));
  es.addEventListener("error", (e: MessageEvent) => onMessage({ event: "error", id: null, data: parse(e) }));
  return es;
}

/**
 * 订阅实时画面流（/runs/{id}/frames），只推 event: frame，data 解析成 FramePushResp。
 * 与事件流是两条独立的线：帧不带 id、不补发；run 终态时后端关流，浏览器触发
 * onerror——消费方据此判断"画面没了"而不是报错。
 */
export function subscribeFrames(req: GetRunReq, onFrame: (frame: FramePushResp) => void): EventSource {
  const es = new EventSource(`/runs/${req.run_id}/frames`);
  es.addEventListener("frame", (e: MessageEvent) => {
    onFrame(JSON.parse(e.data) as FramePushResp);
  });
  return es;
}
