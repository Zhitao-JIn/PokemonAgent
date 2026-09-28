"""对话类判据：对话文字只认屏幕解码（`Frame.text`）。"""

from __future__ import annotations

from evals.e2e.checks.registry import rule
from evals.e2e.checks.stream import RunStream
from evals.e2e.checks.utils import decoded, failed, first_match, passed, target_frames, unjudgeable
from evals.e2e.schemas import CheckVerdict, EvalSample


@rule("dialog_opened")
def dialog_opened(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """出现过对话文字且当帧没有选单（和 NPC 说上话）。"""
    frames = decoded(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有解码来源的帧，对话文字不可信")
    return first_match(
        frames,
        lambda f: bool(f.text.dialog_text) and not f.text.options,
        found="出现了对话文字",
        missing="解码帧里从没出现对话文字",
    )


@rule("dialog_finished")
def dialog_finished(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """出现过对话文字，且最后一帧解码帧里对话框已经没了。

    每帧都带解码文字，"最后一帧解码帧"就是最后一帧带内存读数的帧。
    """
    frames = decoded(target_frames(stream, sample))
    if not frames:
        return unjudgeable("没有解码来源的帧，对话文字不可信")
    had = [f for f in frames if f.text.dialog_text]
    last = frames[-1]
    if not had:
        return failed("解码帧里从没出现对话文字", last)
    if last.text.dialog_text:
        return failed(f"末帧对话框还在：{last.text.dialog_text!r}", had[0], last)
    return passed("对话出现过，末帧已关", had[0], last)


__all__ = ["dialog_finished", "dialog_opened"]
