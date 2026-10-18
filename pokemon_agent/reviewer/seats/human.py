"""人的终端席：输入输出均注入，图片解码后保存 PNG 并显示来源与尺寸。"""

import base64
import binascii
from collections.abc import AsyncIterable, AsyncIterator, Callable
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from pokemon_agent.schemas.reviewer import ViewAnswer
from pokemon_agent.schemas.reviewer.interaction import Activity, Ask

from ..hub.context import ask_text
from ..view.render import text_without_frames


class HumanSeat:
    """不读全局 stdin，不拥有问题状态；调用方注入异步行源、输出函数与图片目录。"""

    def __init__(
        self, lines: AsyncIterable[str], write: Callable[[str], None], *, image_root: Path
    ) -> None:
        self._lines = lines
        self._write = write
        self._image_root = image_root
        self._image_number = 0

    def __aiter__(self) -> AsyncIterator[str]:
        """行源 EOF 结束服务，取消语义由 app 统一处理。"""
        return self._lines.__aiter__()

    def show_ask(self, ask: Ask) -> None:
        """首次展示问题与帮助入口，不将 data URI 打到终端。"""
        self._write(ask_text(ask))
        self.prompt(ask)

    def prompt(self, ask: Ask | None) -> None:
        """查询后仍显示同一个问的编号；空闲时提示等待下一问。"""
        self._write(f"[{ask.seq} {ask.kind}] help / ctx >" if ask else "等待 run 连入 / 等待下一问")

    def activity(self, event: Activity) -> None:
        """可作为 hub 注入的活动回调；只显示进程内消息，不写业务 trace。"""
        self._write(text_without_frames(f"[{event.seq}] {event.action} · {event.text}"))

    def show_result(self, seq: int, answer: ViewAnswer) -> None:
        """查询文字直接展示，图片只落盘；坏图报告失败，不影响下一次输入。"""
        self._write(text_without_frames(answer.text))
        for uri in answer.images:
            try:
                path, size = self._save_image(seq, uri)
            except (OSError, ValueError, binascii.Error, UnidentifiedImageError) as exc:
                self._write(text_without_frames(f"画面保存失败：{exc}"))
            else:
                self._write(f"画面 {path} · {size[0]}×{size[1]} · 来源见上文")

    def _save_image(self, seq: int, uri: str) -> tuple[Path, tuple[int, int]]:
        """显式取帧的副产物只写注入目录；同问多次查询也不覆盖先前图片。"""
        header, separator, encoded = uri.partition(",")
        if not separator or not header.startswith("data:image/") or not header.endswith(";base64"):
            raise ValueError("画面不是 base64 图片 data URI")
        data = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(data)) as image:
            image.load()
            self._image_root.mkdir(parents=True, exist_ok=True)
            self._image_number += 1
            path = self._image_root / f"{seq}-{self._image_number}.png"
            image.save(path, format="PNG")
            return path, image.size
