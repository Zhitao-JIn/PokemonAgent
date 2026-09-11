"""Frontend → GameTools 的 latest_frame 交互：取最新帧请求。"""

from __future__ import annotations

from pydantic import BaseModel


class FromFrontendToGameToolLatestFrameReq(BaseModel):
    """从实时画面管道取最新一帧（SSE 轮询）。

    当前无参数——管道是单槽生产者-消费者，取到即最新；留空信封占位，
    后续若要按时间戳/最小间隔过滤在此扩字段。
    """
