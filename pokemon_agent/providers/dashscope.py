"""DashScope（阿里云百炼）的两个 Provider 实现。

**全项目只有这个文件直连模型服务**（CLAUDE.md 第六节）。换供应商 = 加一个同级文件，
再改装配处一行，其余代码不动。

两个类对两个 Port，各自用不同的模型，这是**计费结构决定的**，不是设计洁癖：

| 类 | Port | 模型 | 为什么 |
|---|---|---|---|
| `QwenText` | `LLMProvider` | qwen-plus | 有资源包抵扣（非思考模式，输入 ≤128K） |
| `QwenVision` | `VisionProvider` | qwen3-vl-plus | flash 读不出格子级的几何，见 CHANGELOG |

走 OpenAI 兼容端点而不是 Anthropic 兼容端点：后者实测会**静默丢弃图片**
（见 `ImageNotDelivered`）。

只用标准库，不引第三方 HTTP 依赖——两个 POST 而已，不值得为它加一个 requirement。
"""

from __future__ import annotations

import pathlib
import base64
import json
import os
import time
import urllib.error
import urllib.request

from pokemon_agent.errors import ImageNotDelivered
from pokemon_agent.schemas.completion import Completion, VisionCompletion
from pokemon_agent.vision.preprocess import ImageFilter, apply_all

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
        temperature: float,
        max_tokens: int = 1024,
        base_url: str | None = None,
        timeout: int = 90,
        max_attempts: int = 3,
    ) -> None:
        """`temperature` 没有默认值，**必须由子类显式给出**。

        走服务端默认值等于把一个影响全部实验结果的变量交给别人管，
        而那个值是什么、会不会变，你我都不知道。两个子类各自定，理由见各自的类。

        记下 base_url、型号与温度，此后不再变。
        """
        assert model, "model must not be empty"
        assert max_attempts >= 1, f"max_attempts must be >= 1, got {max_attempts}"
        assert 0.0 <= temperature <= 2.0, f"temperature out of range: {temperature}"

        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
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

        POST 一次，网络层失败按退避重试。
        """
        req = urllib.request.Request(
            f"{self._base}/chat/completions",
            data=json.dumps({
                "model": self._model,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
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

    def config(self) -> dict[str, str]:
        """自报配置，进 run manifest。

        实验可复现的前提是配置**被记下来**，而不是"当时应该是默认值吧"。
        不含 key —— 它永远不进任何会被写出去的东西。
        """
        return {
            "model": self._model,
            "temperature": str(self._temperature),
            "max_tokens": str(self._max_tokens),
            "base_url": self._base,
        }

    @staticmethod
    def _unpack(resp: dict) -> tuple[str, int, int, bool]:
        """取出正文、两个 token 数，以及**是否被截断**。

        截断判据用 `finish_reason == "length"`，不用 `completion_tokens == max_tokens`：
        后者是巧合（正好写满也可能是自然结束），前者是服务端的明确答复。

        从响应里取出正文、两个 token 数和截断标记。
        """
        choices = resp.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        truncated = choices[0].get("finish_reason") == "length"
        usage = resp.get("usage") or {}
        return (str(text), int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)), truncated)


class QwenText(_DashScopeBase):
    """`LLMProvider` 的实现 —— 决策链路。

    **temperature 默认非零**，因为大脑的重试策略以此为前提：
    `ReActBrain.choose()` 解析失败后用**完全相同的 prompt** 再问一次，
    温度为 0 的话第二次会得到同样的坏输出，重试就是纯浪费。

    0.7 是个起点不是结论——它会进 manifest，所以任何一批实验都说得清用的是多少。
    """

    def __init__(
        self,
        model: str = "qwen-plus",
        *,
        temperature: float = 0.7,
        max_tokens: int = 25600,
        **kw: object,
    ) -> None:
        """**max_tokens 比基类的默认值大得多，这是有实测依据的。**

        `Action.thought` 刻意不设上限（它的长度就是模型这一步的算力）。1024 时
        实测出现过一次 `completion_tokens` 正好 1024 的 `ParseFailure`——
        JSON 是被切断的，不是写错的。那一次调用烧了 23 秒和一整笔 token，
        产出为零，而错误信息指向的是"模型不会写 JSON"这个错误的方向。

        3072 也不够：实测单步 `thought` 到过 2235 token，离顶只剩八百，
        而那还是它在**和自己的记忆吵架**的情况下——真正需要长推理的局面还没出现。

        **这是上限不是预算。** 它只在模型自己想说这么多时才花得掉；
        判定那条链路每次只输出二三十个 token，抬高上限对它没有任何影响。
        真正控成本的是 `max_steps` 和 prompt 长度，不是这个数。

        25600 不是结论，是当前观测下的余量。它进 manifest，所以任何一批数据都说得清。
        **注意各家模型对 max_tokens 有自己的硬上限**（qwen-plus 一档通常是 8192），
        超过会被 API 拒掉——被拒的话用 `--max-tokens` 调低，别改这里的默认值。

        同上，另外把 max_tokens 定在实测够用的档位。
        """
        super().__init__(model, temperature=temperature, max_tokens=max_tokens, **kw)  # type: ignore[arg-type]

    def complete(self, prompt: str) -> Completion:
        """见 `LLMProvider.complete` 的契约。本方法不为输出格式负责。"""
        assert prompt, "complete() got an empty prompt"

        text, n_in, n_out, cut = self._unpack(self._post(prompt))
        return Completion(
            text=text, prompt_tokens=n_in, completion_tokens=n_out, truncated=cut
        )


_DUMP_DIR = os.environ.get("VISION_DUMP_DIR", "")
"""把送进视觉模型的图写到这个目录。空 = 不写。

    VISION_DUMP_DIR=vision_dump python -m pokemon_agent.experiment.run_experiment ...

存的是**预处理之后**的字节，也就是模型真正收到的那一份——存预处理之前的
没有意义，那张图和模型看到的不是同一个东西。
"""

_dump_seq = 0


def _dump(png: bytes) -> None:
    """写一张图，文件名按序号递增。**出错就算了，不能影响这一局。**"""
    global _dump_seq
    try:
        _dump_seq += 1
        d = pathlib.Path(_DUMP_DIR)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{_dump_seq:04d}.png").write_bytes(png)
    except Exception:  # noqa: BLE001  排查工具不该让实验挂掉
        pass


class QwenVision(_DashScopeBase):
    """`VisionProvider` 的实现 —— 感知链路。"""

    def __init__(
        self,
        model: str = "qwen3-vl-plus",
        *,
        temperature: float = 0.0,
        token_floor: int = IMAGE_TOKEN_FLOOR,
        preprocess: tuple[ImageFilter, ...] = (),
        **kw: object,
    ) -> None:
        """**temperature 钉死在 0。**

        感知是抽取不是创作。同一张图两次读出不同结果是纯噪声，而这个噪声会污染
        全部下游数字：状态抽象准确率、state key 的稳定性、机制三的 value 回填——
        后两者直接建立在"同一状态映射到同一 key"上，读不稳这个前提就没了。

        这正是把感知和决策分成两个 Port 的又一个理由：它们对随机性的需求相反。

        ## preprocess：送进模型之前先改图

        为什么注入而不是写死：预处理和**问什么问题**是一对（叠了网格才谈得上
        "第 3 行第 4 列那格"），这一对还要一起换好几轮。注入的话换预处理不用碰这个类。

        为什么放在 provider 而不是 world：world 的职责是交出**这一帧的真实画面**，
        网格是给模型看的辅助线，不是画面的一部分。存证、replay、将来换 CV 通道
        用的都该是原图。

        默认空元组：不写就是不改图，行为和以前完全一样。

        同上，另外接好图像预处理链。
        """
        super().__init__(model, temperature=temperature, **kw)  # type: ignore[arg-type]
        self._floor = token_floor
        self._preprocess = tuple(preprocess)

    def config(self) -> dict[str, str]:
        """在基类的基础上补上预处理链。

        **必须补。** 叠不叠网格会显著改变感知准确率，manifest 里没记的话，
        两批数字摆在一起没人说得清差异是模型带来的还是网格带来的。
        """
        cfg = super().config()
        cfg["preprocess"] = " -> ".join(
            f.config().get("filter", type(f).__name__) for f in self._preprocess
        ) or "none"
        for i, f in enumerate(self._preprocess):
            for k, v in f.config().items():
                cfg[f"preprocess.{i}.{k}"] = v
        return cfg

    def describe(self, image_png: bytes, prompt: str) -> VisionCompletion:
        """见 `VisionProvider.describe` 的契约，尤其是关于静默丢图的那一段。"""
        assert image_png, "describe() got an empty image"
        assert prompt, "describe() got an empty prompt"

        sent = apply_all(image_png, self._preprocess)

        # **把真正送出去的那张图落盘。** 感知出错时，唯一没被任何日志覆盖的东西
        # 就是模型实际看到的像素——人盯着模拟器窗口看到的是 `scale=4` 的 SDL 窗口，
        # 和这里送出去的是两条不同的路径，肉眼比对不能当证据。
        # 实测卡过一整轮：人看得清光标在 RUN，模型始终报 FIGHT，而当时没有任何办法
        # 分辨是"图里没有"还是"模型没看"。
        #
        # 靠环境变量开，默认不写：这是排查用的，不该在正常实验里生成上千张图。
        if _DUMP_DIR:
            _dump(sent)

        b64 = base64.b64encode(sent).decode()
        text, n_in, n_out, _cut = self._unpack(self._post([
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]))

        # 这一行是整个感知链路最重要的一行：没有它，丢图会表现为"一切正常"。
        if n_in < self._floor:
            raise ImageNotDelivered(n_in, self._floor)

        return VisionCompletion(text=text, input_tokens=n_in, output_tokens=n_out)
