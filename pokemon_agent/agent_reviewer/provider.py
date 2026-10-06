"""`agent_reviewer` 的 LLM 接线层——`brain/providers.py` 里 `DeepSeekProvider` 的**叶级副本**。

**为什么是副本不是依赖**：agent 是独立进程，按铁律不与 `brain` 耦合（"谁消费谁持有 provider"
在 `memory/Local*Provider` 已开先例）。这里只留 DeepSeek（视觉版，deepseek-flash V4.1 原生多模态），
`complete`/`describe` 改为收裸字段（`describe(prompt, images)` / `complete(prompt)`），返回
本地 `LlmResult`，不引入对 `brain` 数据模型的耦合；异常也自己定义一份，避免 import `brain.errors`。

只用标准库（`urllib` + `concurrent.futures`）+ `PIL`，不引第三方 HTTP / SDK——与 `brain/providers.py`
同款（见其模块 docstring 第 3 条设计决定）。
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

# ---- 本地异常（与 brain.errors 同形，副本，零 brain 依赖） ----


class EmptyCompletion(Exception):
    """模型回了空正文（思考模式把额度花在 reasoning 上、或 json_mode 概率性空 content）。"""

    def __init__(self, completion_tokens: int, reasoning_tokens: int, finish_reason: str) -> None:
        super().__init__(
            f"空正文（completion={completion_tokens}, reasoning={reasoning_tokens}, "
            f"finish={finish_reason}）"
        )


class ImageNotDelivered(Exception):
    """带图请求的入 token 远低于阈值——图大概率是静默丢掉了（OpenAI 兼容端点实测会吞图）。"""

    def __init__(self, actual: int, floor: int) -> None:
        super().__init__(f"入 token {actual} < 阈值 {floor}：图可能没送到")


class ProviderRejected(Exception):
    """服务端明确拒绝（401/403/400/404）——重试注定无用，让上层立即耗尽预算。"""


class ToolTimeout(Exception):
    """传输层没调通 / 单请求总时长超闸——一次即抛，重试与否归调用方。"""


@dataclass(frozen=True)
class LlmResult:
    """一次 LLM 调用的结果：正文 + 四类 token 计数。"""

    text: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int


# 一张 160x144 的 GB 截图真被当图处理时，输入至少是这个量级。
IMAGE_TOKEN_FLOOR = 100

_POST_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent-llm-post")
"""`_post` 单请求总时长硬闸共用的工作线程池（含义见 `brain/providers.py` 同名字段）。"""

_DUMP_DIR = os.environ.get("VISION_DUMP_DIR", "")
_dump_seq = 0


def _png_bytes(image: str) -> bytes:
    """帧字符串 → PNG 原始字节。前置：完整 data URI（`data:image/png;base64,…`，0915 起唯一格式）。

    需要字节的只有落盘（写 .png）这处——绕不开"文本 → 字节"这一跳。
    """
    assert image.startswith("data:image/png;base64,"), (
        f"帧不是 data URI 格式（0915 起唯一格式）：{image[:40]!r}…"
    )
    return base64.b64decode(image.removeprefix("data:image/png;base64,"))


def _dump(image_b64: str) -> None:
    """写一张图，文件名按序号递增。出错就算了，不能影响这一局。"""

    global _dump_seq
    try:
        _dump_seq += 1
        d = Path(_DUMP_DIR)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{_dump_seq:04d}.png").write_bytes(_png_bytes(image_b64))
    except Exception:  # noqa: BLE001  排查工具不该让实验挂掉
        pass


class _OpenAICompatibleBase:
    """共用的鉴权与 POST。key 只从环境变量读，任何情况下都不落盘、不进日志。

    子类必须覆盖 `BASE_URL` 与 `API_KEY_ENVS`（见 `brain/providers.py` 同名字段）。
    """

    BASE_URL: str = ""
    API_KEY_ENVS: tuple[str, ...] = ()

    def __init__(
        self,
        model: str,
        *,
        temperature: float,
        max_tokens: int = 25600,
        timeout: int = 45,
        multimodal: bool = True,
        json_mode: bool = False,
        thinking: bool = False,
    ) -> None:
        assert model, "model must not be empty"
        assert self.BASE_URL, f"{type(self).__name__} 没有设置 BASE_URL 类属性"
        assert self.API_KEY_ENVS, f"{type(self).__name__} 没有设置 API_KEY_ENVS 类属性"
        assert 0.0 <= temperature <= 2.0, f"temperature out of range: {temperature}"

        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self.multimodal = multimodal
        self._json_mode = json_mode
        self._thinking = thinking
        self._base = self.BASE_URL.rstrip("/")
        self._timeout = timeout
        self._key = next(
            (os.environ[name] for name in self.API_KEY_ENVS if os.environ.get(name)),
            None,
        )
        if not self._key:
            raise RuntimeError(f"{' / '.join(self.API_KEY_ENVS)} 均未设置")

    def _disable_thinking_payload(self) -> dict[str, object]:
        raise NotImplementedError(f"{type(self).__name__} 必须覆盖 _disable_thinking_payload()")

    def _enable_thinking_payload(self) -> dict[str, object]:
        raise NotImplementedError(f"{type(self).__name__} 必须覆盖 _enable_thinking_payload()")

    def _post(self, content: list[dict] | str, thinking: bool | None = None) -> dict:
        """POST 一次，失败按类别立即上抛。不重试——重试的循环与预算全在调用方。"""
        body = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        think = self._thinking if thinking is None else thinking
        body.update(self._enable_thinking_payload() if think else self._disable_thinking_payload())
        if self._json_mode:
            body["response_format"] = {"type": "json_object"}

        req = urllib.request.Request(
            f"{self._base}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self._key}",
            },
        )

        def _do_post() -> dict:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                return json.loads(r.read())

        try:
            # **单请求总时长硬闸**（见 `brain/providers.py` 同名字段 docstring）。
            return _POST_POOL.submit(_do_post).result(timeout=self._timeout + 15)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", "ignore")
            if 400 <= e.code < 500:
                raise ProviderRejected(f"{type(self).__name__} HTTP {e.code}: {error_body}") from e
            raise ToolTimeout(f"{type(self).__name__} HTTP {e.code}: {error_body}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise ToolTimeout(f"{type(self).__name__} 调用不通：{type(e).__name__}: {e}") from e

    @staticmethod
    def _unpack(resp: dict) -> tuple[str, int, int, int, int, bool]:
        """取出正文、两类 token 数、缓存命中与思考 token 数、是否被截断。"""
        choices = resp.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        truncated = choices[0].get("finish_reason") == "length"
        finish = str(choices[0].get("finish_reason") or "")
        usage = resp.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        if not str(text).strip():
            raise EmptyCompletion(
                int(usage.get("completion_tokens", 0)),
                int(completion_details.get("reasoning_tokens", 0)),
                finish,
            )
        return (
            str(text),
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
            int(prompt_details.get("cached_tokens", 0)),
            int(completion_details.get("reasoning_tokens", 0)),
            truncated,
        )


class _MultimodalMixin:
    """`.complete()`/`describe()` 的共同实现，混进 `DeepSeekProvider`。"""

    _floor: int

    def _prepare_images(self, images: list[str]) -> list[str]:
        return list(images)

    def complete(self, prompt: str) -> LlmResult:
        """纯文本调用。前置：`prompt` 非空。"""
        assert prompt, "complete() got an empty prompt"
        text, n_in, n_out, n_cached, n_reason, _cut = self._unpack(self._post(prompt))
        return LlmResult(
            text=text,
            input_tokens=n_in,
            output_tokens=n_out,
            cached_tokens=n_cached,
            reasoning_tokens=n_reason,
        )

    def _send_multimodal(self, prompt: str, images: list[str]) -> LlmResult:
        """带图发一次：落盘（可选）→ 组多模态 content → POST → 解包 + 静默丢图检测。"""
        images = self._prepare_images(list(images))
        if _DUMP_DIR:
            for image_b64 in images:
                _dump(image_b64)

        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        # 帧本身就是完整 data URI（`image_url.url` 要的正好是这个形状，直接透传）。
        content.extend(
            {"type": "image_url", "image_url": {"url": image_b64}} for image_b64 in images
        )
        text, n_in, n_out, n_cached, n_reason, _cut = self._unpack(self._post(content))

        floor = self._floor * len(images)
        if n_in < floor:
            raise ImageNotDelivered(n_in, floor)
        return LlmResult(
            text=text,
            input_tokens=n_in,
            output_tokens=n_out,
            cached_tokens=n_cached,
            reasoning_tokens=n_reason,
        )

    def describe(self, prompt: str, images: list[str]) -> LlmResult:
        """视觉调用：文字块在前、图片在后（缓存前缀命中，见 `brain/providers.py` 同名字段）。"""
        assert images, "describe() got no images"
        assert prompt, "describe() got an empty prompt"
        return self._send_multimodal(prompt, list(images))


class DeepSeekProvider(_MultimodalMixin, _OpenAICompatibleBase):
    """DeepSeek 官方 API——视觉版 `deepseek-flash`（V4.1-Flash，原生多模态）。

    只服务 agent 复核席：固定 `temperature=0`（复核要确定性）、`timeout=20`、
    `thinking=False`、`multimodal=True`、`json_mode=False`。换模型只改 `model=`。
    """

    BASE_URL = "https://api.deepseek.com"
    API_KEY_ENVS = ("DEEPSEEK_API_KEY",)

    def __init__(
        self,
        model: str = "deepseek-flash",
        *,
        temperature: float,
        max_tokens: int = 25600,
        timeout: int = 20,
        token_floor: int = IMAGE_TOKEN_FLOOR,
        **kw: object,
    ) -> None:
        assert model, "DeepSeekProvider 的 model 不能是空字符串"
        super().__init__(
            model, temperature=temperature, max_tokens=max_tokens, timeout=timeout, **kw
        )
        self._floor = token_floor

    def _disable_thinking_payload(self) -> dict[str, object]:
        return {"thinking": {"type": "disabled"}}

    def _enable_thinking_payload(self) -> dict[str, object]:
        return {"thinking": {"type": "enabled"}}


def build_deepseek(
    model: str = "deepseek-flash", *, temperature: float, timeout: int = 20
) -> DeepSeekProvider:
    """造一个 agent 用的 DeepSeek provider。失败（key 缺失）当场 `RuntimeError`。"""
    return DeepSeekProvider(model, temperature=temperature, timeout=timeout)


__all__ = [
    "DeepSeekProvider",
    "EmptyCompletion",
    "ImageNotDelivered",
    "LlmResult",
    "ProviderRejected",
    "ToolTimeout",
    "build_deepseek",
]
