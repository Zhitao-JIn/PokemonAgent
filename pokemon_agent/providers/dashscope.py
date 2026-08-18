"""DashScope（阿里云百炼）的两个 Provider 实现。

**全项目只有这个文件直连模型服务**（CLAUDE.md 第六节）。换供应商 = 加一个同级文件，
再改装配处一行，其余代码不动。

两个类对两个 Port，各自用不同的模型，这是**计费结构决定的**，不是设计洁癖：

| 类 | Port | 模型 | 为什么 |
|---|---|---|---|
| `QwenText` | `LLMProvider` | qwen-plus | 有资源包抵扣（非思考模式，输入 ≤128K） |
| `QwenVision` | `VisionProvider` | qwen3-vl-flash | 每步都调，要最便宜的；另有免费额度 |

走 OpenAI 兼容端点而不是 Anthropic 兼容端点：后者实测会**静默丢弃图片**
（见 `ImageNotDelivered`）。

只用标准库，不引第三方 HTTP 依赖——两个 POST 而已，不值得为它加一个 requirement。
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

from pokemon_agent.errors import ImageNotDelivered
from pokemon_agent.interfaces.llm import Completion
from pokemon_agent.interfaces.vision import VisionCompletion

_DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 一张 160x144 的 GB 截图真被当图处理时，输入至少是这个量级。
# 实测静默丢图时输入会塌到 30 上下（纯提示词的量），两者差着一个数量级，
# 所以这个阈值取在哪都行，不需要精调。
IMAGE_TOKEN_FLOOR = 100


class _DashScopeBase:
    """共用的鉴权与 POST。key 只从环境变量读，任何情况下都不落盘、不进日志。"""

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        timeout: int = 90,
        max_attempts: int = 3,
    ) -> None:
        assert model, "model must not be empty"
        assert max_attempts >= 1, f"max_attempts must be >= 1, got {max_attempts}"

        self._model = model
        self._base = (base_url or os.environ.get("DASHSCOPE_BASE_URL") or _DEFAULT_BASE).rstrip("/")
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if not self._key:
            raise RuntimeError("DASHSCOPE_API_KEY (或 ANTHROPIC_AUTH_TOKEN) 未设置")

    def _post(self, content: list[dict] | str) -> dict:
        """POST 一次，网络层失败按退避重试。

        为什么要重试：这个端点在国内，用户在德国。跨境 TLS 偶发断连
        （`UNEXPECTED_EOF_WHILE_READING`）是常态，尤其是带图的大请求。
        不重试的话，一次抖动就让整个 episode 崩掉，几小时的实验白跑。

        **只重试网络层错误，不重试 HTTP 错误。** 4xx/5xx 是服务端的明确答复
        （型号不对、没权限、超限），重试改变不了任何东西，只是把钱和时间烧两遍。
        """
        req = urllib.request.Request(
            f"{self._base}/chat/completions",
            data=json.dumps({
                "model": self._model,
                "messages": [{"role": "user", "content": content}],
            }).encode(),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self._key}",
            },
        )

        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")[:500]
                # "调不通"必须和"调通了但输出没用"能被调用方区分开（LLMProvider 契约）。
                raise RuntimeError(f"DashScope HTTP {e.code}: {body}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = e
                if attempt < self._max_attempts:
                    time.sleep(0.5 * 2 ** (attempt - 1))  # 0.5s, 1s, 2s...

        raise RuntimeError(
            f"DashScope 网络层失败，{self._max_attempts} 次重试后放弃："
            f"{type(last).__name__}: {last}"
        ) from last

    @staticmethod
    def _unpack(resp: dict) -> tuple[str, int, int]:
        choices = resp.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = resp.get("usage") or {}
        return str(text), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


class QwenText(_DashScopeBase):
    """`LLMProvider` 的实现 —— 决策链路。"""

    def __init__(self, model: str = "qwen-plus", **kw: object) -> None:
        super().__init__(model, **kw)  # type: ignore[arg-type]

    def complete(self, prompt: str) -> Completion:
        """见 `LLMProvider.complete` 的契约。本方法不为输出格式负责。"""
        assert prompt, "complete() got an empty prompt"

        text, n_in, n_out = self._unpack(self._post(prompt))
        return Completion(text=text, prompt_tokens=n_in, completion_tokens=n_out)


class QwenVision(_DashScopeBase):
    """`VisionProvider` 的实现 —— 感知链路。"""

    def __init__(
        self, model: str = "qwen3-vl-flash", *, token_floor: int = IMAGE_TOKEN_FLOOR, **kw: object
    ) -> None:
        super().__init__(model, **kw)  # type: ignore[arg-type]
        self._floor = token_floor

    def describe(self, image_png: bytes, prompt: str) -> VisionCompletion:
        """见 `VisionProvider.describe` 的契约，尤其是关于静默丢图的那一段。"""
        assert image_png, "describe() got an empty image"
        assert prompt, "describe() got an empty prompt"

        b64 = base64.b64encode(image_png).decode()
        text, n_in, n_out = self._unpack(self._post([
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]))

        # 这一行是整个感知链路最重要的一行：没有它，丢图会表现为"一切正常"。
        if n_in < self._floor:
            raise ImageNotDelivered(n_in, self._floor)

        return VisionCompletion(text=text, input_tokens=n_in, output_tokens=n_out)
