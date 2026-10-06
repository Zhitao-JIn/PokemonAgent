"""`AgentReviewer`：独立进程内的有状态视觉 LLM 复核席（deepseek-flash 视觉）。

坐在后端 `/ui` 这一侧：harness 照旧发 `ask`、收 `answer`，不知道背后是人或 AI。
agent 按 `seq` 持有每段对话（进程内存，随 agent 重启即失），后端只经跳 C WS 发增量 delta。

**不是自治 agent**：没有工具、不自停、不自决——只是"人就着一份已给的结论与画面表态"
的视觉 LLM 调用，把结论封进 `ProposedAnswer` 推回后端。人在网页上看到后改、或点「发给 AI」再磨一轮。
"""

from __future__ import annotations

from pokemon_agent.agent_reviewer.provider import (
    DeepSeekProvider,
    EmptyCompletion,
    ImageNotDelivered,
    LlmResult,
    ProviderRejected,
    ToolTimeout,
    build_deepseek,
)
from pokemon_agent.schemas.agent_reviewer.communication import ChatTurn
from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict
from pokemon_agent.schemas.review_backend.communication.FromReviewBackendToFrontendAskReq import (
    FromReviewBackendToFrontendAskReq,
)
from pokemon_agent.schemas.review_backend.communication.ProposedAnswer import ProposedAnswer

_SYSTEM = (
    "你是「人和 AI 复核席」里的 AI 复核者。harness 会推来一份**已给出的结论**与它的证据 / 画面。"
    "你的任务只表态：**这份结论与证据 / 画面一不一致**。"
    "\n- 审（verdict）：结论说「目标已达成 / 任务通过」时，你要么**认账**（同意），"
    "要么**推翻**（不同意），推翻**必须**给一句理由；你不替 harness 决定下一步。"
    "\n- 插话（inject）：只输出一句改进意见，或「无意见」。"
    "\n只输出结论本身，不要解释你的思考过程。"
)

# 推翻类关键词 → OVERTURN；认账类 → ACCEPT；取不到明确词默认 ACCEPT（误判"没成"代价小）。
_OVERTURN_WORDS = ("推翻", "不同意", "不通过", "没达成", "未达到", "不成立", "错误", "错")
_ACCEPT_WORDS = ("认账", "同意", "通过", "达成", "认可", "正确", "对")


def _seed_user(ask: FromReviewBackendToFrontendAskReq, has_frame: bool) -> str:
    """把 pending 的那封 ask 拼成一则给模型的指令文本；帧由 `describe` 单独传，不进文本。"""
    kind_label = "审（判断结论是否成立）" if ask.kind == "audit" else "插话（给一句改进意见）"
    lines = [
        ask.prompt,
        f"类型：{kind_label}（{ask.form_kind or '—'}）",
        "内容：",
        ask.body,
    ]
    if ask.kind == "audit" and ask.events:
        lines.append("被审对象的事件：")
        lines.extend(ask.events)
    lines.append("画面已随附（若有），请结合画面判断。" if has_frame else "（本次无画面。）")
    return "\n".join(lines)


def _render(conv: list[ChatTurn]) -> str:
    """把整段对话压成一段文本（视觉模型走单 user message）。system 在最前，其余按角色加标记。"""
    parts: list[str] = []
    for turn in conv:
        if turn.role == "system":
            parts.append(turn.text)
            continue
        label = {
            "human": "复核请求",
            "agent": "你上一轮的结论",
        }.get(turn.role, turn.role)
        parts.append(f"【{label}】\n{turn.text}")
    return "\n\n".join(parts)


def _parse(text: str, kind: str) -> ProposedAnswer:
    """模型自由文本 → `ProposedAnswer`。"""
    body = (text or "").strip()
    if kind == "audit":
        lowered = body
        if any(w in lowered for w in _OVERTURN_WORDS):
            # 取「理由：…」后文作 note；没有就整段留作理由。
            note = body
            if "理由" in body:
                note = body.split("理由", 1)[1].lstrip("：: ").strip() or body
            return ProposedAnswer(verdict=AuditVerdict.OVERTURN, note=note)
        # 认账类词、或取不到明确词 → ACCEPT（保守）。
        return ProposedAnswer(verdict=AuditVerdict.ACCEPT)
    # 插话：原样作 text；空 → None（"无意见"）。
    return ProposedAnswer(text=body or None)


class AgentReviewer:
    """进程内持有每段对话的 AI 复核席。用法：后端经跳 C WS 调 `seed`/`turn`/`close`。"""

    def __init__(
        self, model: str = "deepseek-flash", *, llm: DeepSeekProvider | None = None
    ) -> None:
        # `llm` 仅测试注入用；缺省造真实 DeepSeek provider（温度 0、超时 20）。
        self._llm = llm if llm is not None else build_deepseek(model, temperature=0, timeout=20)
        self._convs: dict[str, list[ChatTurn]] = {}
        self._kinds: dict[str, str] = {}

    def seed(self, ask: FromReviewBackendToFrontendAskReq, frame: str | None) -> ProposedAnswer:
        """开一问：建该 seq 对话 + 全量渲染 + 调模型；返回首轮结论。"""
        seq = str(ask.seq)
        self._kinds[seq] = ask.kind
        conv = [
            ChatTurn(role="system", text=_SYSTEM),
            ChatTurn(role="human", text=_seed_user(ask, frame is not None)),
        ]
        self._convs[seq] = conv
        return self._call(seq, frame)

    def turn(self, seq: str | int, delta: ChatTurn, frame: str | None) -> ProposedAnswer:
        """增量：只追加人这一轮的话，调模型；返回新一轮结论。"""
        seq = str(seq)
        # 同一 seq 若已了结（被 close）则忽略本轮（先答先得）。
        if seq not in self._convs:
            return ProposedAnswer()
        self._convs[seq].append(delta)
        return self._call(seq, frame)

    def close(self, seq: str | int) -> None:
        """了结一问：释放该 seq 的对话状态。"""
        seq = str(seq)
        self._convs.pop(seq, None)
        self._kinds.pop(seq, None)

    def _call(self, seq: str, frame: str | None) -> ProposedAnswer:
        kind = self._kinds.get(seq, "inject")
        conv = self._convs[seq]
        prompt = _render(conv)
        images = [frame] if frame else []
        try:
            res: LlmResult = (
                self._llm.describe(prompt, images) if images else self._llm.complete(prompt)
            )
        except (EmptyCompletion, ImageNotDelivered, ProviderRejected, ToolTimeout):
            # 失败 = 空提案（后端不推，前端照常等人或倒计时）。
            return ProposedAnswer()
        prop = _parse(res.text, kind)
        # 把这次结论回灌成 agent 角色，便于下一轮 turn 看到上下文。
        line = prop.text or (prop.verdict.value if prop.verdict else "")
        if line:
            self._convs[seq].append(ChatTurn(role="agent", text=line))
        return prop


__all__ = ["AgentReviewer"]
