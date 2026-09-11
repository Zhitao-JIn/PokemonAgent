import { useEffect, useState } from "react";
import { getRun } from "./api";
import type { GoalView } from "./types";

/**
 * 轮询一个 run 的目标栈（每 2s 拉一次 GET /runs/{id}）。
 *
 * 目标栈变化不频繁（plan 每轮决策才动一次），轮询足够；不用 SSE——
 * 栈变化没有独立消息，且 GET 顺带拿到 status/outcome 等一次性快照。
 * runId 为 null 时不轮询；run 结束后轮询停不停由调用方决定（这里不停，
 * 终态栈是观测台还想看的最后画面，代价只是一个 2s 一次的小请求）。
 *
 * 轮询失败静默（后端可能瞬时 404/断连），下一轮自动恢复。
 */
export function useRunGoals(runId: string | null): GoalView[] {
  const [goals, setGoals] = useState<GoalView[]>([]);

  useEffect(() => {
    if (runId === null) return;

    let alive = true;
    const tick = async () => {
      try {
        const data = await getRun({ run_id: runId });
        if (alive) setGoals(data.goals);
      } catch {
        // 静默：目标栈是辅助视图，读不到不影响主链路，下轮再试
      }
    };
    tick();
    const timer = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [runId]);

  return goals;
}
