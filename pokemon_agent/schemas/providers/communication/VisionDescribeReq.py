"""视觉端口 describe() 的请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisionDescribeReq(BaseModel):
    """一次视觉补全的请求：一张或多张图加上要问的问题。

    images：待识别的图片，**base64 编码后的 PNG 字符串**（不是原始字节）——
        直接是 REST API `image_url` 那个字段要拼的内容
        （`f"data:image/png;base64,{img}"`），**按要出现在 prompt 里的顺序
        排列**，至少一张。`StepMemory`
        直接存 base64（省掉“存文件名→用的时候再读盘+编码”这一趟），
        `judge`/`verify_steps` 用的图片天然就是已经编好的字符串，
        这里用 `str` 才不用来回编解码；感知（`PyBoyWorld`）产出的是
        原始字节，调用方在构造这个请求之前自己 `base64.b64encode(...).decode()`
        一次。
    prompt：要问这些图的问题。
    """

    images: list[str] = Field(min_length=1)
    prompt: str
