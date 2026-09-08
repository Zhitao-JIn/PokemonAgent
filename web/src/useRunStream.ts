import { useEffect, useState } from "react";
import { subscribeEvents } from "./api";
import type { SseEvent } from "./types";

/** 事件流 hook 的返回形状：事件列表 + 连接状态（供 UI 提示"断线了"用）。 */
export interface RunStreamState {
  events: SseEvent[];
  /** false = 浏览器原生 onerror 触发过、还没收到下一条消息——大概率网络断了，
   *  正在自动重连（`EventSource` 内建行为，这里不用手写重连逻辑）。 */
  connected: boolean;
}

/**
 * 订阅一个 run 的事件流，返回**一个事件列表**（不分类）——trace / done /
 * error 都是列表里的一条，怎么展示由渲染层按 `ev.event` switch 决定。
 *
 * runId 为 null 时不连接（run 还没启动）；换 run 时清空列表再重连。
 * 断线重连是浏览器 EventSource 的内建行为（自动带 Last-Event-ID，后端据此
 * 补发），这里不用手写重连——但 done/error 必须主动 close：服务器正常关流
 * 时浏览器会当"断线"处理并无限重连，重连后拿到的是终态补发，白白空转。
 *
 * `connected` 只是给 UI 一个"断线了"的视觉信号（之前完全没有——用户长时间
 * 看不到新事件，分不清是真的没事件还是网络断了），不影响重连本身：
 * `onerror` 触发时浏览器已经在后台自动重试，这里只是把这件事显式暴露出来。
 */
export function useRunStream(runId: string | null): RunStreamState {
  const [events, setEvents] = useState<SseEvent[]>([]);
  const [connected, setConnected] = useState(true);

  useEffect(() => {
    if (runId === null) return;

    setEvents([]);
    setConnected(true);
    const es = subscribeEvents({ run_id: runId }, (ev) => {
      setConnected(true); // 收到消息说明连上了（重连成功也会先触发这里）
      setEvents((prev) => [...prev, ev]);
      if (ev.event === "done" || ev.event === "error") {
        es.close(); // 终态：防浏览器把"服务器正常关流"当断线而无限重连
      }
    });
    es.onerror = () => setConnected(false);

    // StrictMode 双挂载 / 组件卸载 / 换 run：都走这里关连接。
    return () => es.close();
  }, [runId]);

  return { events, connected };
}
