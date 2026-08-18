"""一次性探针：问 DashScope 的 Anthropic 兼容端点「你到底是谁」，以及吃不吃图片。

回答两个问题：
  1. `qwen-plus` 这类别名实际被解析成什么型号 —— 看返回体的 `model` 字段
  2. 这个端点接不接受 Anthropic 格式的 image content block

用法（PowerShell）：
    $env:ANTHROPIC_AUTH_TOKEN = "sk-..."
    python probe/whoami.py                                  # 只测文本，跑全部候选
    python probe/whoami.py "screenshots/xxx.png"            # 带图，跑全部候选
    python probe/whoami.py "screenshots/xxx.png" qwen3-vl-plus   # 只测一个模型

**注意 `图片被吃掉了吗` 这一行。** 网关可能静默丢弃 image block 然后凭空编造描述，
不报任何错误。判据是 input_tokens：真处理了图片，输入至少是几百 token；
塌回纯文本量级就说明图根本没进去。

不写死任何 key，只从环境变量读。**别把 key 写进这个文件。**
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("ANTHROPIC_BASE_URL", "https://dashscope.aliyuncs.com/apps/anthropic")
KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("DASHSCOPE_API_KEY") or ""

# 别名 + 显式型号一起测：别名解析成什么，正是这次要看的
CANDIDATES = ["qwen-plus", "qwen3-vl-flash", "qwen3-vl-plus", "qwen3.7-plus"]


def call(model: str, image_path: str | None, prompt: str) -> dict:
    content: list[dict] = []
    if image_path:
        with open(image_path, "rb") as f:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(f.read()).decode(),
                },
            })
    content.append({"type": "text", "text": prompt})

    req = urllib.request.Request(
        BASE.rstrip("/") + "/v1/messages",
        data=json.dumps({
            "model": model,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": content}],
        }).encode(),
        headers={
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            # 两种鉴权头都带上：不同网关认的不一样，一次试完省得来回猜
            "x-api-key": KEY,
            "authorization": f"Bearer {KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode("utf-8", "ignore")[:500]}
    except Exception as e:  # noqa: BLE001  探针脚本，任何失败都只需看清楚原因
        return {"_err": f"{type(e).__name__}: {e}"}


# 一张 160x144 的截图真被处理时，输入 token 至少是这个量级。
# 低于它说明 image block 被静默丢弃了 —— 这是最危险的失败模式：不报错，只幻觉。
_IMAGE_TOKEN_FLOOR = 100


def show(tag: str, model: str, resp: dict, *, with_image: bool = False) -> None:
    if "_http" in resp:
        print(f"  [{tag}] HTTP {resp['_http']}  {resp['_body']}")
        return
    if "_err" in resp:
        print(f"  [{tag}] {resp['_err']}")
        return
    served = resp.get("model", "(返回体里没有 model 字段)")
    texts = [b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"]
    usage = resp.get("usage", {})
    n_in = usage.get("input_tokens", 0)
    print(f"  [{tag}] 实际服务型号 = {served!r}   （注意：多数网关只是回显请求名）")
    print(f"         回答: {' '.join(texts).strip()[:200]!r}")
    print(f"         用量: input={n_in} output={usage.get('output_tokens', 0)}")
    if with_image:
        ok = n_in >= _IMAGE_TOKEN_FLOOR
        verdict = "是" if ok else (
            f"**否 —— input_tokens 仅 {n_in}，图被静默丢弃，上面的描述是幻觉**"
        )
        print(f"         图片被吃掉了吗: {verdict}")


def main() -> None:
    if not KEY:
        sys.exit("没读到 key。先设 ANTHROPIC_AUTH_TOKEN 或 DASHSCOPE_API_KEY 环境变量。")
    image = sys.argv[1] if len(sys.argv) > 1 else None
    models = [sys.argv[2]] if len(sys.argv) > 2 else CANDIDATES

    print(f"endpoint = {BASE}")
    print(f"图片     = {image or '（本轮不带图，只测文本）'}\n")

    for model in models:
        print(f"── 请求 model={model!r}")
        show("文本", model, call(model, None, "你是什么模型？只回答型号名称，不要别的。"))
        if image:
            vision_prompt = (
                "这是一张 Game Boy 游戏截图。用一句话说明画面里有什么，"
                "并原样抄出你看到的所有文字。"
            )
            show("图片", model, call(model, image, vision_prompt), with_image=True)
        print()


if __name__ == "__main__":
    main()
