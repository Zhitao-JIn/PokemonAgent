import { useEffect, useState } from "react";
import { subscribeFrames } from "./api";

/**
 * 订阅一个 run 的实时画面流，返回最新一帧的 data URL（可直接当 img.src）。
 *
 * runId 为 null 时不连接；换 run 时清掉旧帧再重连。
 *
 * 30fps 高频更新走 useState：160x144 的 PNG 转 data URL 只有几十 KB，React
 * 每帧重渲染一次小组件树可接受；不需要 objectURL——那要先解码 base64 再
 * 包 Blob，对小图是倒贴开销。若将来帧更大/组件更重，再把"写 img.src"下沉
 * 到 ref + requestAnimationFrame，hook 接口不用变。
 *
 * onerror → close：后端在 run 终态时正常关流，浏览器会把"服务器关流"当
 * 断线并无限重连；帧无 id、无补发，重连只能拿到新帧，而 run 已结束——
 * 主动 close 是对的。这行代码和 useRunStream 里 done/error 时 close 是
 * 同一个动机，只是这里没有终态消息可听，只能靠 onerror 兜底。
 */
export function useFrameStream(runId: string | null): string | null {
  const [frameUrl, setFrameUrl] = useState<string | null>(null);

  useEffect(() => {
    if (runId === null) return;

    setFrameUrl(null);
    const es = subscribeFrames({ run_id: runId }, (frame) => {
      setFrameUrl(`data:image/png;base64,${frame.frame_png}`);
    });
    es.onerror = () => es.close();

    return () => es.close();
  }, [runId]);

  return frameUrl;
}
