# 一次性诊断脚本（0909）：豆包能不能读 3 列网格拼图（无上采样版）。
# 9 格 = 真机帧轮转 + 每格左上角数字徽章 1-9，问模型行列数 + 行优先报数字。
# 用完即弃，不进 tests/。
import io
import json
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, r"D:\Users\GummiGu\PycharmProjects\Pokemon_Agent")

from pokemon_agent.providers.openai_compatible import ArkProvider, pack_images_grid
from pokemon_agent.schemas.communication import VisionCompletionReq

SRC = (
    r"D:\Users\GummiGu\PycharmProjects\Pokemon_Agent\pokemon_agent"
    r"\memory\episode\memory\steps-run-20260907-194413-154d9e-ep1.jsonl"
)

with open(SRC, encoding="utf-8") as f:
    rec = json.loads(next(l for l in f if l.strip()))
real = [rec["before_frame"], rec["after_frame"]]
print("real frames:", [len(x) for x in real])

def badge(b64: str, num: int) -> str:
    """在帧左上角盖一个数字徽章（白字黑底），返回 base64。"""
    im = Image.open(io.BytesIO(__import__("base64").b64decode(b64))).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle([2, 2, 34, 22], fill=(0, 0, 0), outline=(255, 255, 0), width=2)
    d.text((8, 4), str(num), fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return __import__("base64").b64encode(buf.getvalue()).decode()

frames = [badge(real[i % len(real)], i + 1) for i in range(9)]
grid = pack_images_grid(frames)
canvas = Image.open(io.BytesIO(__import__("base64").b64decode(grid)))
print("grid canvas size:", canvas.size)

prompt = (
    "这张图是一个网格拼图，每格左上角有一个数字徽章。请回答：\n"
    "1) 网格是几行几列？\n"
    "2) 按行优先（从左到右、从上到下）顺序报出每格的数字。\n"
    "3) 用一句话描述第 5 格的画面内容（场景里有什么）。"
)

ark = ArkProvider(model="doubao-seed-2-1-pro-260628", temperature=0.0)
resp = ark.describe(VisionCompletionReq(images=[grid], prompt=prompt))
print("--- 模型回答 ---")
print(resp.text)
print(
    f"tokens: in={resp.input_tokens} out={resp.output_tokens} "
    f"cached={resp.cached_tokens} reasoning={resp.reasoning_tokens}"
)
