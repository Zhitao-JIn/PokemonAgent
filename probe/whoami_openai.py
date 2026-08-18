"""探针之二：走 OpenAI 兼容模式，看图片能不能真的传进去。

为什么要有这个文件：`probe/whoami.py` 走的是 DashScope 的 Anthropic 兼容端点
（`/apps/anthropic`），实测那条链路会**静默丢弃** image block —— 不报错，
模型收不到图，然后凭空编一段描述。OpenAI 兼容模式是另一条链路、另一种图片编码
（`image_url` + data URI），同一个模型换个门进去，结果可能不同。

判据仍然是 token 数，不是回答内容：
`prompt_tokens` 塌回纯文本量级 = 图没进去，回答一定是幻觉。

用法（PowerShell）：
    $env:DASHSCOPE_API_KEY = "sk-..."       # 或复用 ANTHROPIC_AUTH_TOKEN
    python probe/whoami_openai.py "screenshots/xxx.png"
    python probe/whoami_openai.py "screenshots/xxx.png" qwen-plus
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
KEY = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""

CANDIDATES = ["qwen-plus", "qwen-vl-plus", "qwen3-vl-flash", "qwen3-vl-plus"]

# 一张 160x144 截图真被处理时，输入 token 至少是这个量级。
_IMAGE_TOKEN_FLOOR = 100


def call(model: str, image_path: str | None, prompt: str) -> dict:
    content: list[dict] = [{"type": "text", "text": prompt}]
    if image_path:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        content.insert(0, {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    req = urllib.request.Request(
        BASE.rstrip("/") + "/chat/completions",
        data=json.dumps({
            "model": model,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": content}],
        }).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode("utf-8", "ignore")[:500]}
    except Exception as e:  # noqa: BLE001  探针脚本，任何失败都只需看清楚原因
        return {"_err": f"{type(e).__name__}: {e}"}


def show(tag: str, resp: dict, *, with_image: bool = False) -> None:
    if "_http" in resp:
        print(f"  [{tag}] HTTP {resp['_http']}  {resp['_body']}")
        return
    if "_err" in resp:
        print(f"  [{tag}] {resp['_err']}")
        return

    served = resp.get("model", "(无 model 字段)")
    choices = resp.get("choices") or [{}]
    text = (choices[0].get("message") or {}).get("content", "")
    usage = resp.get("usage", {})
    n_in = usage.get("prompt_tokens", 0)

    print(f"  [{tag}] 服务型号 = {served!r}")
    print(f"         回答: {str(text).strip()[:200]!r}")
    print(f"         用量: prompt={n_in} completion={usage.get('completion_tokens', 0)}")
    if with_image:
        verdict = "是" if n_in >= _IMAGE_TOKEN_FLOOR else (
            f"**否 —— prompt_tokens 仅 {n_in}，图被静默丢弃，描述是幻觉**"
        )
        print(f"         图片被吃掉了吗: {verdict}")


def main() -> None:
    if not KEY:
        sys.exit("没读到 key。先设 DASHSCOPE_API_KEY 或 ANTHROPIC_AUTH_TOKEN。")
    image = sys.argv[1] if len(sys.argv) > 1 else None
    models = [sys.argv[2]] if len(sys.argv) > 2 else CANDIDATES

    print(f"endpoint = {BASE}")
    print(f"图片     = {image or '（不带图）'}\n")

    vision_prompt = (
        "这是一张 Game Boy 游戏截图。用一句话说明画面里有什么，"
        "并原样抄出你看到的所有文字。"
    )
    for model in models:
        print(f"── 请求 model={model!r}")
        show("文本", call(model, None, "你是什么模型？只回答型号名称。"))
        if image:
            show("图片", call(model, image, vision_prompt), with_image=True)
        print()


if __name__ == "__main__":
    main()
