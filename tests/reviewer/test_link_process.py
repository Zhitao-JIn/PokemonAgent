"""真正启动独立 reviewer 子进程，经 WS 询问并经 stdin 查询帧、提交答复。"""

import asyncio
import base64
import os
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from _doubles.reviewer import inject_request
from PIL import Image

from pokemon_agent.reviewer_link import RemoteReviewer


async def read_until(process: subprocess.Popen, marker: str) -> str:
    """只等待有限行，超时由测试报错并在 finally 终止子进程。"""
    for _ in range(100):
        line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 5)
        if not line:
            raise RuntimeError("reviewer 提前退出")
        if marker in line:
            return line
    raise RuntimeError(f"未收到预期输出：{marker}")


def start_process(root: Path) -> subprocess.Popen:
    """子进程使用独立路径与空的外部 memory 地址，不读任何真实密钥文件。"""
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pokemon_agent.reviewer",
            "--seats",
            "human",
            "--url",
            "ws://127.0.0.1:0",
            "--trace-root",
            str(root / "trace"),
            "--image-root",
            str(root / "images"),
            "--env-file",
            str(root / "no.env"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8", MCP_MEMORY_SERVER_URL=""),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_independent_reviewer_process_supports_stdin_answers_and_png_queries(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        process = start_process(tmp_path)
        client = None
        try:
            started = await read_until(process, "已启动：")
            url = re.search(r"ws://127\.0\.0\.1:\d+", started).group()
            client = RemoteReviewer(url, flush=lambda: None, lost_timeout_s=0.01)
            request = inject_request(frames=True)
            png = BytesIO()
            Image.new("RGB", (3, 2), "red").save(png, format="PNG")
            uri = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
            for memory in request.context.brain_input.history:
                memory.before_frame = memory.after_frame = uri
            asking = asyncio.create_task(asyncio.to_thread(client.inject, request))
            await read_until(process, "[1 inject]")
            process.stdin.write("brain-frames\n")
            process.stdin.flush()
            await read_until(process, "画面 ")
            process.stdin.write("say 子进程原话\n")
            process.stdin.flush()
            response = await asyncio.wait_for(asking, 4)
            assert response.text == "子进程原话" and response.by == "human"
            assert len(list((tmp_path / "images").glob("*.png"))) == 1
            with Image.open(next((tmp_path / "images").glob("*.png"))) as image:
                assert image.size == (3, 2)
            await asyncio.to_thread(client.close)
            process.stdin.close()
            assert await asyncio.to_thread(process.wait, 4) == 0
        finally:
            if client is not None:
                await asyncio.to_thread(client.close)
            if process.poll() is None:
                process.terminate()
                await asyncio.to_thread(process.wait, 4)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    asyncio.run(scenario())
