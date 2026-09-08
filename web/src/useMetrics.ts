import { useEffect, useState } from "react";
import { getMetrics } from "./api";
import type { RunMetrics } from "./types";

/**
 * 轮询一个 run 的实时聚合报表（每 2s 拉一次 GET /runs/{id}/metrics）——
 * `docs/ROADMAP.md` 第 2 条"可观测"第二拍。同 `useRunGoals` 的轮询节奏：
 * 这类聚合数字不是每一步都值得重算一次的东西，2s 够用，不需要跟审查面板
 * 那种 500ms 的紧凑轮询看齐（那边有个 5s 超时窗口在赶，这里没有）。
 *
 * runId 为 null 时不轮询；run 结束后轮询也不停（同 `useRunGoals` 的理由：
 * 终态数字是观测台还想看的最后画面，代价只是一个 2s 一次的小请求）。
 * 轮询失败静默，下一轮自动恢复。
 */
export function useMetrics(runId: string | null): RunMetrics | null {
  const [metrics, setMetrics] = useState<RunMetrics | null>(null);

  useEffect(() => {
    if (runId === null) return;

    let alive = true;
    const tick = async () => {
      try {
        const data = await getMetrics({ run_id: runId });
        if (alive) setMetrics(data);
      } catch {
        // 静默：报表是辅助视图，读不到不影响主链路，下轮再试
      }
    };
    tick();
    const timer = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [runId]);

  return metrics;
}
