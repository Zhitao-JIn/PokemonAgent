"""真实三图、Web Reviewer 后端和脚本网页的确定性集成用法。"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from _fake_run import GOAL, build_fake, every  # noqa: E402
from websockets.asyncio.client import connect

from pokemon_agent.harness.web_reviewer import WebReviewer  # noqa: E402
from pokemon_agent.review_backend import ReviewBackend  # noqa: E402

Policy = Callable[[dict], dict | None]
"""网页的答题脚本：拿到一问，回答案（`AnswerReq` 的字段）；None = 不答。"""


class _Loop:
    """一条线程里跑一个事件循环，给后端与扮网页的客户端用。"""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.backends: list[_Backend] = []
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def run(self, coro: object, timeout: float = 10) -> object:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)  # type: ignore[arg-type]


class _Backend:
    """后台线程里的真后端；`stop()` 关掉它（模拟后端进程没了）。"""

    def __init__(self, loop: _Loop) -> None:
        async def _open() -> object:
            return await ReviewBackend().serve("127.0.0.1", 0).__aenter__()

        self._loop = loop
        loop.backends.append(self)
        self._server = loop.run(_open())
        self.url = f"ws://127.0.0.1:{next(iter(self._server.sockets)).getsockname()[1]}"

    def stop(self) -> None:
        async def _close() -> None:
            self._server.close()
            await self._server.wait_closed()

        self._loop.run(_close())


class _Page:
    """扮网页：连 `/ui`，收推送、按脚本答，记下看到的问与实时事件。"""

    def __init__(self, loop: _Loop, url: str, policy: Policy) -> None:
        self.asks: list[dict] = []
        self.feed: list[dict] = []
        self._policy = policy
        self._ready = threading.Event()
        asyncio.run_coroutine_threadsafe(self._serve(url), loop.loop)
        if not self._ready.wait(5):
            raise TimeoutError("扮网页的客户端没连上后端")

    async def _serve(self, url: str) -> None:
        async with connect(f"{url}/ui", proxy=None) as page:
            self._ready.set()
            async for raw in page:
                message = json.loads(raw)
                if message["msg"] == "feed":
                    self.feed.append(message["event"])
                elif message["msg"] == "ask":
                    self.asks.append(message)
                    answer = self._policy(message)
                    if answer is not None:
                        await page.send(
                            json.dumps({"msg": "answer", "seq": message["seq"], **answer})
                        )


def _events(fake) -> list[dict]:  # noqa: ANN001
    return [json.loads(e.model_dump_json()) for e in fake.trace.read_events({"run_id": "r1"})]


def _content(event: dict) -> dict:
    return json.loads(event["content"])


def _human() -> Policy:
    """第一次拆解插一句、第一次 episode「已达成」推翻，其余没意见 / 认账。"""
    seen: dict[str, int] = {}

    def answer(ask: dict) -> dict:
        key = ask["form_kind"] + ("@run" if ask.get("episode_id") == "r1" else "")
        seen[key] = seen.get(key, 0) + 1
        if ask["kind"] == "inject":
            first_decompose = ask["form_kind"] == "Decomposition" and seen[key] == 1
            return {"text": "先进门再说" if first_decompose else ""}
        if ask["form_kind"] == "JudgeVerdict" and key == "JudgeVerdict" and seen[key] == 1:
            return {"verdict": "overturn", "note": "球还没拿到"}
        return {"verdict": "accept"}

    return answer


def test_human_answers(review_loop: _Loop, tmp_path: Path) -> None:
    """真实三图、后端与脚本网页核验 human_answers 场景。"""
    loop, work = review_loop, tmp_path
    backend = _Backend(loop)
    page = _Page(loop, backend.url, _human())
    reviewer = WebReviewer("r1", backend.url, timeout=5)
    fake = build_fake(
        work, episode=every(2), run=every(1), reviewer=reviewer, live_feed_url=backend.url
    )
    fake.harness.run("r1", [GOAL])
    reviewer.close()
    events = _events(fake)

    reviews = [e for e in events if e["kind"] in ("review_inject", "review_audit")]
    assert reviews
    for event in reviews:
        content = _content(event)
        expected = event["kind"] == "review_audit" or bool(content["reply"])
        assert content["answered"] == str(expected).lower()
    assert len(page.asks) == len(reviews), f"网页看到 {len(page.asks)} 问，账上 {len(reviews)} 笔"
    notes = [_content(e)["human_note"] for e in events if e["kind"] == "decompose_verdict"]
    assert "先进门再说" in notes, "拆解被插话后没有带话重问"
    overturned = [_content(e) for e in events if e["kind"] == "judge_verdict"]
    assert any(v["audit"] == "overturn" for v in overturned), "episode 的「已达成」没被推翻"
    assert any(e["kind"] == "sense_frame" for e in page.feed), "网页没收到画面"
    for _ in range(50):
        if len(page.feed) >= len(events):
            break
        time.sleep(0.1)
    assert [e["uuid"] for e in page.feed] == [e["uuid"] for e in events], (
        f"实时事件 {len(page.feed)} 条与盘上 {len(events)} 条对不上"
    )
    backend.stop()
    print(f"PASS  人在答：{len(reviews)} 问按填写状态记账，重拆带话、推翻生效")


def test_nobody_answers(review_loop: _Loop, tmp_path: Path) -> None:
    """真实三图、后端与脚本网页核验 nobody_answers 场景。"""
    loop, work = review_loop, tmp_path
    backend = _Backend(loop)
    page = _Page(loop, backend.url, lambda ask: None)
    reviewer = WebReviewer("r1", backend.url, timeout=0.3)
    fake = build_fake(work, reviewer=reviewer)
    fake.harness.run("r1", [GOAL])
    reviewer.close()
    reviews = [e for e in _events(fake) if e["kind"] in ("review_inject", "review_audit")]
    assert reviews and all(_content(e)["answered"] == "false" for e in reviews)
    assert all(_content(e).get("verdict", "accept") in ("", "accept") for e in reviews)
    backend.stop()
    print(f"PASS  没人答：{len(reviews)} 问全部按默认值，网页看到 {len(page.asks)} 问")


def test_backend_goes_away(review_loop: _Loop, tmp_path: Path) -> None:
    """真实三图、后端与脚本网页核验 backend_goes_away 场景。"""
    loop, work = review_loop, tmp_path
    backend = _Backend(loop)
    stopped = threading.Event()

    def answer_then_die(ask: dict) -> dict:
        if not stopped.is_set():
            stopped.set()
            threading.Thread(target=backend.stop, daemon=True).start()
        return {"text": ""} if ask["kind"] == "inject" else {"verdict": "accept"}

    _Page(loop, backend.url, answer_then_die)
    reviewer = WebReviewer("r1", backend.url, timeout=5)
    fake = build_fake(work, reviewer=reviewer, live_feed_url=backend.url)
    fake.harness.run("r1", [GOAL])
    reviews = [e for e in _events(fake) if e["kind"] in ("review_inject", "review_audit")]
    assert len(reviews) > 1 and _content(reviews[-1])["answered"] == "false"
    print(f"PASS  后端中途没了：run 跑完，{len(reviews)} 问里最后一问按默认值")


@pytest.fixture()
def review_loop():
    """每个场景独立事件循环；退出时关闭服务、任务和线程。"""
    loop = _Loop()
    yield loop
    for backend in loop.backends:
        backend.stop()

    async def cancel_pending() -> None:
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    loop.run(cancel_pending())
    loop.loop.call_soon_threadsafe(loop.loop.stop)
    loop.thread.join(timeout=5)
    loop.loop.close()
