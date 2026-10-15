"""原始 PNG 字节转成统一的完整 data URI。"""

import base64


def png_data_uri(png: bytes) -> str:
    """截图原始字节 → **完整 data URI**（`data:image/png;base64,…`）。

    **本函数是全仓唯一的帧编码点（0915 定）**：帧离开本层之后只有两个去处——
    落盘（trace 事件的 `frame`、`memory/step_memory/*.json` 的
    `before_frame`/`after_frame`、`*_call` 账的 `images`）和进模型——拿到的
    都是本函数的产出，**格式只有这一种**。为什么带前缀：裸 base64 无法与
    普通字符串区分，离线找图连 grep "base64" 都搜不到（前缀本身才含这个词）；
    带上 data URI 前缀后格式说话，离线分析（benchmark 导帧、网页实时
    画面）见串即知是图。
    """
    return f"data:image/png;base64,{base64.b64encode(png).decode()}"
