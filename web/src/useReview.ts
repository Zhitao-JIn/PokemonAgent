import { useEffect, useState } from "react";
import { getPendingReview, getRun } from "./api";
import type { PendingReview } from "./types";

const REVIEW_POLL_INTERVAL_MS = 500;
/** 轮询节拍：跟 `REVIEW_TIMEOUT`（后端默认 5s）配的，不是跟其他轮询
 * hook（`useRunGoals` 那种 2s）对齐——2s 轮一次意味着审查请求发出后最坏
 * 要等接近 2s 才会在面板里冒出来，5s 的窗口被吃掉快一半，人根本来不及点。
 * 500ms 把这个延迟砍到可以忽略，代价是 run 运行期间多发几个请求，本地/
 * 开发环境这点开销可以忽略（同 `RunDataCenter` 内部 0.2s 阻塞轮询的取舍）。 */

/**
 * 轮询一个 run 有没有待处理的审查请求（每 `REVIEW_POLL_INTERVAL_MS` 拉一次
 * GET /runs/{id}，`review_pending` 为 true 时再拉一次 GET /runs/{id}/review
 * 取详情）。
 *
 * 两步轮询而不是每轮都拉详情：详情可能带完整的 episode_trace，没有待处理
 * 请求时没必要传这份可能不小的 payload——跟 GetRunResp.review_pending
 * 这个字段存在的理由是同一件事。
 *
 * runId 为 null 时不轮询；轮询失败静默，下一轮自动恢复（同 useRunGoals）。
 */
export function useReview(runId: string | null): PendingReview | null {
  const [review, setReview] = useState<PendingReview | null>(null);

  useEffect(() => {
    if (runId === null) return;

    let alive = true;
    const tick = async () => {
      try {
        const status = await getRun({ run_id: runId });
        if (!status.review_pending) {
          if (alive) setReview(null);
          return;
        }
        const pending = await getPendingReview({ run_id: runId });
        if (alive) setReview(pending);
      } catch {
        // 静默：轮询失败下一轮自动恢复，不打断主链路
      }
    };
    tick();
    const timer = setInterval(tick, REVIEW_POLL_INTERVAL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [runId]);

  return review;
}
