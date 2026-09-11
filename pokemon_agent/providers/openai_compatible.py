"""能打通任意 OpenAI 兼容 `chat/completions` 端点的 Provider 实现。

**全项目只有这个文件直连模型服务**（CLAUDE.md 第六节）。加一个新供应商 = 在这个
文件里加一个新的 `_OpenAICompatibleBase` 子类，再改装配处一行，其余代码不动。

## 三条设计决定

1. **一个供应商一个 Provider 类，不按用途（text/vision）分类。** 当前在用的
   `qwen3.8-max`/`doubao-seed-2-1-pro`/`doubao-seed-2-1-turbo` 全是原生多模态
   模型，一个类 `.complete()`/`.describe()` 两个方法都实现，用哪个方法取决于
   调用方（`Brain` 走 `LLMProvider.complete`，`PyBoyWorld` 走
   `VisionProvider.describe`），跟"这个类打的是哪个供应商"是两件事。哪怕
   塞进去的 `model` 是纯文本模型（比如 `qwen-plus`），类本身仍然两个方法都有
   ——只是永远不会被调 `.describe()`。
2. **换供应商 = 换类，换模型 = 换 `model=` 参数，url/key 不用跟着变。** 每个
   `_OpenAICompatibleBase` 子类用类属性钉死自己的 `BASE_URL` 和 `API_KEY_ENVS`
   （按顺序尝试的环境变量名，第一个非空的生效），同一供应商下换模型只是构造时
   传不同的字符串，不查任何跨供应商的名字表。
3. **没有图像预处理插件机制**——`describe()` 直接把原始 PNG 编码发出去
   （该机制被判定为死重量删除，见 `CHANGELOG.md` 2026-09-05 条目）。

## 一个不能偷懒复用的地方：关不掉"思考模式"的请求体字段，各家不一样

`enable_thinking: false` 是 DashScope（Qwen）的写法；火山方舟（Ark）关思考模式
用的是 `thinking: {"type": "disabled"}`，一个嵌套对象，字段名和结构完全不同
（各家文档可查证）。所以这一个字段**不能**放进共享的 `_post()` 里，
`_OpenAICompatibleBase` 把它做成一个必须被子类覆盖的钩子方法
`_disable_thinking_payload()`，`_post()` 只负责把钩子返回的字典 merge 进请求体。

走 OpenAI 兼容端点而不是各家自己的原生/Anthropic 兼容端点：后者实测会**静默
丢弃图片**（见 `ImageNotDelivered`，这条是 Qwen 上踩出来的坑，Ark 未验证过，
但两家反正都提供 OpenAI 兼容端点，没必要冒险走原生协议）。

只用标准库，不引第三方 HTTP 依赖（也不引各家官方 SDK，比如火山的 `arkruntime`）
——都是走同一套 `POST /chat/completions`，不值得为它们各加一个 requirement。
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import pathlib
import time
import urllib.error
import urllib.request

from PIL import Image

from pokemon_agent.errors import ImageNotDelivered, ParseFailure, ToolTimeout
from pokemon_agent.schemas.providers import (
    LlmCompleteReq,
    LlmCompleteResp,
    VisionDescribeReq,
    VisionDescribeResp,
)

# 一张 160x144 的 GB 截图真被当图处理时，输入至少是这个量级。
# 实测静默丢图时输入会塌到 30 上下（纯提示词的量），两者差着一个数量级，
# 所以这个阈值取在哪都行，不需要精调。
IMAGE_TOKEN_FLOOR = 100


class _OpenAICompatibleBase:
    """共用的鉴权与 POST。key 只从环境变量读，任何情况下都不落盘、不进日志。

    子类必须覆盖 `BASE_URL`（这个供应商的接入点，末尾带不带 `/` 都行，
    `__init__` 会自己 `rstrip`）和 `API_KEY_ENVS`（按顺序尝试的环境变量名
    元组，第一个取到非空值的生效——`("DASHSCOPE_API_KEY", "ANTHROPIC_AUTH_TOKEN")`
    这种"主 key 名 + 兜底名"的写法就是靠这个元组的顺序表达的）。
    """

    BASE_URL: str = ""
    API_KEY_ENVS: tuple[str, ...] = ()

    def __init__(
        self,
        model: str,
        *,
        temperature: float,
        max_tokens: int = 1024,
        timeout: int = 90,
        max_attempts: int = 3,
    ) -> None:
        """`temperature` 没有默认值，**必须由调用方显式给出**。

        走服务端默认值等于把一个影响全部实验结果的变量交给别人管，
        而那个值是什么、会不会变，你我都不知道。**不由子类定死**——一个类
        两种用途都要服务，同一个类的两个实例温度经常不一样（决策要 0.7，
        感知要 0），默认值定在类这一级反而会悄悄用错，所以收紧成"每次构造
        都必须传"。

        记下型号与温度，此后不再变。base_url/api_key 从子类的类属性拿，
        不接受调用方覆盖——见模块 docstring 第 2 条设计决定。
        """
        assert model, "model must not be empty"
        assert self.BASE_URL, f"{type(self).__name__} 没有设置 BASE_URL 类属性"
        assert self.API_KEY_ENVS, f"{type(self).__name__} 没有设置 API_KEY_ENVS 类属性"
        assert max_attempts >= 1, f"max_attempts must be >= 1, got {max_attempts}"
        assert 0.0 <= temperature <= 2.0, f"temperature out of range: {temperature}"

        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._base = self.BASE_URL.rstrip("/")
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._key = next(
            (os.environ[name] for name in self.API_KEY_ENVS if os.environ.get(name)),
            None,
        )
        if not self._key:
            raise RuntimeError(f"{' / '.join(self.API_KEY_ENVS)} 均未设置")

    def _disable_thinking_payload(self) -> dict[str, object]:
        """关掉"思考模式"要合并进请求体的字段——**各家格式不同，子类必须覆盖**。

        为什么要关：不管哪家，思考模式都可能先把输出额度花在
        reasoning_content/思考过程上，`content` 可能整段为空——决策/判定链路
        的契约是"正文必须是可解析的 JSON"，这个模式跟契约冲突，token 也白烧。

        返回一个要 merge 进请求体顶层的字典片段。
        """
        raise NotImplementedError(f"{type(self).__name__} 必须覆盖 _disable_thinking_payload()")

    def _post(self, content: list[dict] | str) -> dict:
        """POST 一次，网络层失败按退避重试。

        为什么要重试：这个端点在国内，用户在德国。跨境 TLS 偶发断连
        （`UNEXPECTED_EOF_WHILE_READING`）是常态，尤其是带图的大请求。
        不重试的话，一次抖动就让整个 episode 崩掉，几小时的实验白跑。

        **只重试网络层错误，不重试 HTTP 错误。** 4xx/5xx 是服务端的明确答复
        （型号不对、没权限、超限），重试改变不了任何东西，只是把钱和时间烧两遍。

        POST 一次，网络层失败按退避重试。
        """
        body = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        body.update(self._disable_thinking_payload())

        req = urllib.request.Request(
            f"{self._base}/chat/completions",
            data=json.dumps(body).encode(),
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
                error_body = e.read().decode("utf-8", "ignore")
                if 400 <= e.code < 500:
                    # 4xx 是配置/请求错误（401 密钥、403 配额、400 请求格式）——
                    # 重试多少次都一样，当场崩，装配期就该暴露。
                    raise RuntimeError(f"{type(self).__name__} HTTP {e.code}: {error_body}") from e
                # 5xx 是服务端抖动：记下来重试，重试耗尽转 ToolTimeout。
                last = e
                if attempt < self._max_attempts:
                    time.sleep(0.5 * 2 ** (attempt - 1))  # 0.5s, 1s, 2s...
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = e
                if attempt < self._max_attempts:
                    time.sleep(0.5 * 2 ** (attempt - 1))  # 0.5s, 1s, 2s...

        # 网络层/5xx 重试耗尽：归 AgentError 家族——调用方（RunHarness.dispatch）
        # 捕到它让这一局失败，而不是让整个 run 崩掉。
        raise ToolTimeout(
            f"{type(self).__name__} 调用不通，{self._max_attempts} 次重试后放弃："
            f"{type(last).__name__}: {last}"
        ) from last

    def config(self) -> dict[str, str]:
        """自报配置，进 run manifest。

        实验可复现的前提是配置**被记下来**，而不是"当时应该是默认值吧"。
        不含 key —— 它永远不进任何会被写出去的东西。
        """
        return {
            "provider": type(self).__name__,
            "model": self._model,
            "temperature": str(self._temperature),
            "max_tokens": str(self._max_tokens),
            "base_url": self._base,
        }

    @staticmethod
    def _unpack(resp: dict) -> tuple[str, int, int, int, int, bool]:
        """取出正文、两个 token 数、命中缓存与思考（reasoning）的 token 数，
        以及**是否被截断**。

        截断判据用 `finish_reason == "length"`，不用 `completion_tokens == max_tokens`：
        后者是巧合（正好写满也可能是自然结束），前者是服务端的明确答复。

        `cached_tokens` 读 `usage.prompt_tokens_details.cached_tokens`——
        DashScope（Qwen）和火山方舟（doubao-seed-2.x 起）字段名完全一致，
        两家都是"隐式缓存默认开、不可关"（各家文档可查证：见
        `docs/ROADMAP.md`"缓存命中率怎么统计"一条），调用方不用做任何事就
        可能命中，这个字段是唯一能看出命中了多少的地方——没有它，`input_tokens`
        看起来降不下来时分不清是"根本没命中"还是"命中了但没算进省下来的钱"。
        取不到就是 0（老响应没有这个字段，或者本来就没命中），不是异常。

        从响应里取出正文、两个 token 数、缓存命中 token 数和截断标记。
        """
        choices = resp.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        truncated = choices[0].get("finish_reason") == "length"
        usage = resp.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        return (
            str(text),
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
            int(prompt_details.get("cached_tokens", 0)),
            # 思考模型（doubao-seed-2.x 等）把推理 token 计入 completion_tokens，
            # 且**不受 max_tokens 约束**（实测：max_tokens=8 时 reasoning 也能跑
            # 到 1.9k）。不带这个字段（非思考模型/老响应）就是 0。
            int(completion_details.get("reasoning_tokens", 0)),
            truncated,
        )


_DUMP_DIR = os.environ.get("VISION_DUMP_DIR", "")
"""把送进视觉模型的图写到这个目录。空 = 不写。

    VISION_DUMP_DIR=vision_dump python -m <任一入口脚本> ...

存的是**实际发出去**的字节，也就是模型真正收到的那一份（没有预处理这一步，
发出去的就是感知拿到的原图）。
"""

_dump_seq = 0


def _dump(image_b64: str) -> None:
    """写一张图，文件名按序号递增。**出错就算了，不能影响这一局。**

    入参是 base64 字符串（跟 `VisionDescribeReq.images` 类型一致），落盘前
    先解码回字节——这个函数存在的意义就是让人肉眼能直接打开看，存 base64
    文本没有这个用处。
    """
    global _dump_seq
    try:
        _dump_seq += 1
        d = pathlib.Path(_DUMP_DIR)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{_dump_seq:04d}.png").write_bytes(base64.b64decode(image_b64))
    except Exception:  # noqa: BLE001  排查工具不该让实验挂掉
        pass


class _MultimodalMixin:
    """`.complete()`/`.describe()` 的共同实现，混进各供应商类。

    两个方法都只调 `self._post()`/`self._unpack()`（`_OpenAICompatibleBase`
    提供），差别只是要不要带图、以及 `describe()` 多一步"静默丢图"检测——
    这部分逻辑跟"打的是哪个供应商"无关，抽出来避免每个供应商类各写一遍。
    """

    _floor: int  # 由 __init__ 设置，见各 Provider 类

    def _prepare_images(self, images: list[str]) -> list[str]:
        """豆包专属：多帧拼一张网格图（保证发出去的**永远是一张图**）。

        `ArkProvider` 覆写为**多帧拼一张网格图**：豆包的图像 token 按"张"
        计费且与分辨率无关（0908 实测：160×144 到 2584×2300 六档全部
        1,294 tok，官方文档公式 宽×高/784 对 seed-2.x 不适用），多帧拼一张
        之后图费与帧数解耦——这条保证做在 provider 层，任何调用方误传多图
        给豆包都会被自动打包，不存在"忘了拼"这回事。
        """
        return list(images)

    def complete(self, req: LlmCompleteReq) -> LlmCompleteResp:
        """见 `LLMProvider.complete` 的契约。本方法不为输出格式负责。"""
        prompt = req.prompt
        assert prompt, "complete() got an empty prompt"

        text, n_in, n_out, n_cached, n_reason, cut = self._unpack(self._post(prompt))
        if not text.strip():
            # 有输出 token 但正文为空：思考模式把输出全占了（或安全过滤）。
            # 抛 ParseFailure 而不是裸空串——调用方（plan/choose 的重试）按
            # 类型归类，错误信息要能直接指向"模型没给正文"而不是"模型不会写 JSON"。
            raise ParseFailure(
                text,
                f"模型返回空正文（completion_tokens={n_out}，truncated={cut}）——"
                "已请求关闭思考模式；若仍复现，检查该模型是否真的支持这个关闭参数",
            )
        return LlmCompleteResp(
            text=text,
            prompt_tokens=n_in,
            completion_tokens=n_out,
            cached_tokens=n_cached,
            reasoning_tokens=n_reason,
            truncated=cut,
        )

    def describe(self, req: VisionDescribeReq) -> VisionDescribeResp:
        """见 `VisionProvider.describe` 的契约，尤其是关于静默丢图的那一段。

        图片是一组（`judge`/`verify_and_summarize` 会带 `StepMemory` 历史里的
        截图一起问），按 `req.images` 的顺序排列。

        **文字块在最前面，图片在最后面**——
        DashScope/火山方舟的隐式缓存都是从请求
        **最开头**匹配前缀的，而我们的 `prompt` 里前面一大截是静态规则文字
        （`perceive_screen.md`/`judge_success.md` 那种，每次调用几乎一字不
        变），后面才是这一帧才有的动态内容；`images` 却是每一步都不同的一
        帧截图。图片摆在最前面时，这个天天不变的静态前缀永远排在"会变的
        图片"后面，前缀匹配从第一个 token 起就断了，静态部分**一分钱缓存
        都吃不到**。文字块在最前面，静态规则那一段才是真正的开头，才有机会
        被跨调用复用、按标准价的 20% 计费。**图在前/图在后会改变视觉模型实际
        读到的 token 顺序**，对识别准确率的影响没有实测数据，需要真机跑几局
        观察 `ModelCall.payload["cached_tokens"]` 涨没涨、以及识别准确率
        （`ImageNotDelivered`/`ParseFailure` 频率、judge/perception 的实际判断
        质量）有没有退化（调整决策记录见 `CHANGELOG.md` 2026-09-05 条目）。
        """
        assert req.images, "describe() got no images"
        assert req.prompt, "describe() got an empty prompt"

        # 发送前最后一道处理（`ArkProvider` 在这里把多帧拼成一张，见
        # `_prepare_images`）——后续的落盘、floor 校验、content 组装全部
        # 基于**实际发出去**的图片组。
        images = self._prepare_images(list(req.images))

        # **把真正送出去的图落盘。** 感知出错时，唯一没被任何日志覆盖的东西
        # 就是模型实际看到的像素——人盯着模拟器窗口看到的是 `scale=4` 的 SDL 窗口，
        # 和这里送出去的是两条不同的路径，肉眼比对不能当证据。
        # 实测卡过一整轮：人看得清光标在 RUN，模型始终报 FIGHT，而当时没有任何办法
        # 分辨是"图里没有"还是"模型没看"。
        #
        # 靠环境变量开，默认不写：这是排查用的，不该在正常实验里生成上千张图。
        if _DUMP_DIR:
            for image_b64 in images:
                _dump(image_b64)

        content: list[dict[str, object]] = [{"type": "text", "text": req.prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            }
            for image_b64 in images
        )
        text, n_in, n_out, n_cached, n_reason, _cut = self._unpack(self._post(content))

        # 这一行是整个感知链路最重要的一行：没有它，丢图会表现为"一切正常"。
        # 多图按张数等比放大阈值——`_floor` 本来就是"一张图真被处理时至少这么
        # 多 token"的经验值，N 张图理应至少是它的 N 倍，不然大概率是漏发了。
        # 这只是量级判断，不是精确会计：真实 token 数还跟每张图内容有关，
        # 阈值定得宽松（`_floor` 本身已经留了余量），不要求恰好等比。
        floor = self._floor * len(images)
        if n_in < floor:
            raise ImageNotDelivered(n_in, floor)

        return VisionDescribeResp(
            text=text,
            input_tokens=n_in,
            output_tokens=n_out,
            cached_tokens=n_cached,
            reasoning_tokens=n_reason,
        )


class QwenProvider(_MultimodalMixin, _OpenAICompatibleBase):
    """DashScope（阿里云百炼）——`qwen3.8-max`（当前默认，语言+视觉两用）、
    历史上的 `qwen-plus`（纯文本）等都走这个类，换模型只改 `model=`。
    """

    BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    API_KEY_ENVS = ("DASHSCOPE_API_KEY", "ANTHROPIC_AUTH_TOKEN")

    def __init__(
        self,
        model: str = "qwen3.8-max",
        *,
        temperature: float,
        max_tokens: int = 25600,
        token_floor: int = IMAGE_TOKEN_FLOOR,
        **kw: object,
    ) -> None:
        """**max_tokens 比基类的默认值大得多，这是有实测依据的。**

        `ActionFromBrain.thought` 刻意不设上限（它的长度就是模型这一步的算力）。1024 时
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

        `token_floor`：只有走 `.describe()`（当视觉用）才会检查，当纯文本用时
        （`.complete()`）不涉及，传不传都没关系。
        """
        super().__init__(model, temperature=temperature, max_tokens=max_tokens, **kw)  # type: ignore[arg-type]
        self._floor = token_floor

    def _disable_thinking_payload(self) -> dict[str, object]:
        """DashScope（Qwen）关思考模式的写法：顶层一个布尔字段。"""
        return {"enable_thinking": False}


def image_grid_dims(n: int) -> tuple[int, int]:
    """N 张帧拼图用的网格 `(rows, cols)`——**列数固定 3**，行数 `ceil(n/3)`。

    3 列是布局契约：`pack_images_grid`（实际打包）按它算画布尺寸；
    prompt 文案（`prompts/calls/verify_and_summarize.md` 截图一节）静态写死
    3 列，行数由模型看图自己数——两边描述的是同一张图。
    """
    cols = 3
    return math.ceil(n / cols), cols


def pack_images_grid(images: list[str]) -> str:
    """把 N 张 base64 PNG 帧拼成一张网格图，返回拼接图的 base64。

    每帧保持**原始分辨率**（160×144，不做上采样——0909 拍板去掉，豆包按张
    计费与分辨率无关，上采样白付显存不省一分钱图费）、帧间 4px 黑线分隔、
    行优先排列。0908 实测：拼接图从 2 帧到 16 帧 token 恒为 1,294——
    图费与帧数解耦，每帧等效成本随帧数摊薄。
    """
    assert images, "pack_images_grid() got no images"
    if len(images) == 1:
        return images[0]
    frames = [Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB") for b64 in images]
    w, h = frames[0].size
    rows, cols = image_grid_dims(len(frames))
    sep = 4
    canvas = Image.new("RGB", (cols * w + (cols - 1) * sep, rows * h + (rows - 1) * sep), (0, 0, 0))
    for i, f in enumerate(frames):
        canvas.paste(f, ((i % cols) * (w + sep), (i // cols) * (h + sep)))
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class ArkProvider(_MultimodalMixin, _OpenAICompatibleBase):
    """火山方舟（Volcengine Ark）——`doubao-seed-2-1-pro`/`doubao-seed-2-1-turbo`
    都走这个类，换模型只改 `model=`，url/key 不用动。

    接入点：`https://ark.cn-beijing.volces.com/api/v3`，
    走图片时的 messages 结构跟 DashScope 完全一致（同为 OpenAI 兼容格式），
    真实调用示例见 ROADMAP 对应记录。**模型名带日期后缀**（比如
    `doubao-seed-2-1-pro-260628`）——这不是可选项，是火山方舟的命名惯例，
    调用时必须带上完整字符串，缺了会 404。

    **多帧入参会在此处自动拼成一张网格图再发送**（`_prepare_images`）——
    豆包图像按张计费且与分辨率无关，拼接是 provider 层的结构保证，
    调用方（verify/judge/未来的 plan 带图）传几张都不多花钱。
    """

    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    API_KEY_ENVS = ("ARK_API_KEY",)

    def _prepare_images(self, images: list[str]) -> list[str]:
        return [pack_images_grid(images)] if len(images) > 1 else list(images)

    def __init__(
        self,
        model: str,
        *,
        temperature: float,
        max_tokens: int = 25600,
        token_floor: int = IMAGE_TOKEN_FLOOR,
        **kw: object,
    ) -> None:
        """`model` 没有默认值——跟 `QwenProvider` 不同，火山方舟这边目前有
        两个候选（pro/turbo），刻意不替调用方选一个，装配处必须显式写清楚
        用的是哪一个（带完整日期后缀）。其余参数含义同 `QwenProvider`。
        """
        assert model, "ArkProvider 的 model 必须显式给出（pro/turbo 两个候选，不设默认值）"
        super().__init__(model, temperature=temperature, max_tokens=max_tokens, **kw)  # type: ignore[arg-type]
        self._floor = token_floor

    def _disable_thinking_payload(self) -> dict[str, object]:
        """火山方舟关思考模式的写法：嵌套对象，跟 DashScope 的扁平布尔字段
        不是同一个形状——**这正是不能把这个字段塞进共享 `_post()`
        的原因**，见模块 docstring。
        """
        return {"thinking": {"type": "disabled"}}

class DeepSeekProvider(_MultimodalMixin, _OpenAICompatibleBase):
    """DeepSeek 官方 API——默认模型 `deepseek-flash`（即 DeepSeek-V4.1-Flash，
    原生多模态，文本+视觉两用），换模型只改 `model=`。

    接入点：`https://api.deepseek.com`（OpenAI 兼容格式，见官方文档
    https://api-docs.deepseek.com/zh-cn/ ），messages 结构与 DashScope/
    火山方舟一致，走的都是同一套 `POST /chat/completions`。

    **关思考模式的写法与火山方舟同形**：`{"thinking": {"type": "disabled"}}`，
    嵌套对象——DeepSeek 官方文档同时给了 `thinking.type` 与顶层
    `reasoning_effort` 两条路，这里固定走前者，跟 `_disable_thinking_payload()`
    钩子的既有形状（"要么扁平布尔，要么嵌套对象"）对齐，不额外引入第三种形状。

    **`model` 默认值定为 `deepseek-flash`，不再留成"两个候选都不选"。**
    这一点跟最初接入时（0911 早些时候）的判断不同——当时 `deepseek-v4-pro`
    还是并行在用的候选，比照 `ArkProvider` 的 pro/turbo 两候选不预设默认；
    但官方文档已明确 2026-09-14 起 `deepseek-v4-pro` 全量路由到 V4.1 Flash
    （等于官方替我们把选择做掉了，不是项目自己猜的），且 flash 在效果/成本/
    速度上全面优于 v4-pro——这时候还坚持不给默认值，就是揣着明白装糊涂。
    `deepseek-v4-pro` 仍可传（走的是同一个类，只是最终会被官方路由到同一个
    模型），只是不再是构造函数的默认。

    **`token_floor` 沿用基类默认值（`IMAGE_TOKEN_FLOOR = 100`），未针对
    DeepSeek 单独实测过。** 官方文档给出的是图片消耗 token 的量级（每张
    上限约 1024，按尺寸折算），不是"图片真被处理时的下界"——`QwenVision`/
    `ArkProvider` 的 100 是从各自实测的"丢图 vs 正常"两种场景的数量级差异
    里定出来的，DeepSeek 还没有等价的实测数据。这个默认值先借用同一套判据
    （"差一个数量级就够用，不需要精调"），真机跑出数据后应按 3.4 节同样的
    方法重新标定，而不是假设它天然适用。
    """

    BASE_URL = "https://api.deepseek.com"
    API_KEY_ENVS = ("DEEPSEEK_API_KEY",)

    def __init__(
        self,
        model: str = "deepseek-flash",
        *,
        temperature: float,
        max_tokens: int = 25600,
        token_floor: int = IMAGE_TOKEN_FLOOR,
        **kw: object,
    ) -> None:
        """`model` 默认 `deepseek-flash`，理由见类 docstring（官方已把
        v4-pro 路由到它，不是项目单方面替调用方拍板）。`max_tokens` 默认值
        沿用 `QwenProvider` 的实测依据（`Action.thought` 刻意不设上限，
        1024/3072 均实测不够，见该类 `__init__` docstring）——这个理由与
        "打的是哪家供应商"无关，是"decide 这条链路本身需要多少输出余量"的
        问题，DeepSeek 侧没有理由更少。**注意 DeepSeek 官方文档给出的
        `max_tokens` 硬上限是 384K**，比 Qwen/Ark 都宽松得多，但这里不因此
        抬高默认值——真正控成本的是 `max_steps` 和 prompt 长度，不是这个数
        （同 `QwenProvider` 的理由）。
        """
        assert model, "DeepSeekProvider 的 model 不能是空字符串"
        super().__init__(model, temperature=temperature, max_tokens=max_tokens, **kw)  # type: ignore[arg-type]
        self._floor = token_floor

    def _disable_thinking_payload(self) -> dict[str, object]:
        """DeepSeek 关思考模式的写法：嵌套对象，与火山方舟同形、与 DashScope
        的扁平布尔字段不同——同一个理由：这正是不能把这个字段塞进共享
        `_post()` 的原因，见模块 docstring。"""
        return {"thinking": {"type": "disabled"}}
