from __future__ import annotations

import json
import os
from typing import Dict, Any

import jinja2

from pokemon_agent.interfaces.llm import LLMProvider
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.memory.utils import _create_episode_memory
from pokemon_agent.schemas.memory_episode import EpisodeMemory
from pokemon_agent.schemas.memory_episode_summary import EpisodeContext, EpisodeSummaryResponse
from pokemon_agent.schemas.trace import EventType, Source


class EpisodeMemoryGenerator:
    """一局结束后，把这一局蒸馏成一条跨局摘要记忆（`EpisodeMemory`）。

    依赖从构造函数传入（CLAUDE.md 依赖注入原则）：`trace_port` 用来给这次蒸馏
    留一条 trace（成功写 `EPISODE_MEMORY_WRITE`，解析失败写 `ERROR`，两者的
    `source` 都是 `Source.MEMORY`——这条链的 token 花费和决策链分开记账，
    见 `schemas/trace.py` 里 `Source.MEMORY` 的注释）；`llm_provider` 用来做蒸馏。

    工作流程：
    1. 调用方给一份 `EpisodeContext`（这一局的目标、结果、关键步骤）
    2. 渲染成 prompt，调 LLM
    3. 解析成 `EpisodeSummaryResponse`；解析失败不吞、直接抛并留痕
    4. 组装成 `EpisodeMemory`，连同这次调用的 trace 事件 id 一起返回
    """

    def __init__(self, trace_port: TracePort, llm_provider: LLMProvider) -> None:
        """前置条件：`trace_port`、`llm_provider` 均非空——两者都是必须的依赖，
        缺一个说明装配（`build.py`）出了 bug，不是运行期该处理的情况。
        """
        assert trace_port is not None, "EpisodeMemoryGenerator needs a trace_port"
        assert llm_provider is not None, "EpisodeMemoryGenerator needs an llm_provider"
        self._trace_port = trace_port
        self._llm_provider = llm_provider

        template_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "episode_summary.md")
        with open(template_path, "r", encoding="utf-8") as f:
            self._template = jinja2.Template(f.read())

    def generate_summary(
        self,
        episode_id: str,
        run_id: str,
        goal: str,
        outcome: Dict[str, Any],
        context: EpisodeContext,
    ) -> EpisodeMemory:
        """蒸馏这一局，返回一条 `EpisodeMemory`。

        前置条件：`episode_id` 非空；`outcome` 至少含 `success`/`steps`。
        后置条件：成功时返回值的 `episode_id`/`goal` 与入参一致；
            过程中产生的这次 LLM 调用会留下恰好一条 trace 事件
            （成功是 `EPISODE_MEMORY_WRITE`，解析失败是 `ERROR`，二选一，不会两条都没有）。
        失败：LLM 输出解析不出合法 JSON 时抛 `ValueError`，不吞——
            解析失败是预期内的运行时情况（CLAUDE.md 第八节），调用方决定要不要重试。
        """
        assert episode_id, "generate_summary() needs a non-empty episode_id"

        prompt = self._build_prompt(context)
        completion = self._llm_provider.complete(prompt)

        try:
            response = self._parse_response(completion.text)
        except ValueError as e:
            self._trace_port.append(
                episode_id, context.steps, EventType.ERROR, Source.MEMORY,
                {"kind": "EpisodeSummaryParseFailure", "reason": str(e)[:200]},
            )
            raise

        episode_memory = _create_episode_memory(
            episode_id, run_id, goal, outcome,
            response.content, response.rationale, stamp=f"{run_id}#{episode_id}",
        )

        self._trace_port.append(
            episode_id, context.steps, EventType.EPISODE_MEMORY_WRITE, Source.MEMORY,
            {
                "summary": episode_memory.content.summary,
                "quality_score": str(episode_memory.content.quality.score),
                "applicable_scenes": " ".join(episode_memory.content.applicable_scenes),
                "input_tokens": str(completion.prompt_tokens),
                "output_tokens": str(completion.completion_tokens),
            },
        )

        assert episode_memory.episode_id == episode_id, "generate_summary must preserve episode_id"
        return episode_memory

    def _build_prompt(self, context: EpisodeContext) -> str:
        """用模板渲染出蒸馏用的 prompt。"""
        steps_text = ""
        for i, step in enumerate(context.key_steps, 1):
            steps_text += f"- **决策点 #{i}**\n"
            steps_text += f"  - **思考**: {step.thought}\n"
            steps_text += f"  - **动作**: {step.action} ×{step.action_times}\n"
            steps_text += f"  - **结果**: {step.result_summary}\n"
            steps_text += f"  - **场景**: {step.scene}\n\n"

        return self._template.render(
            goal=context.goal,
            success=context.success,
            steps=context.steps,
            max_steps=context.max_steps,
            initial_state=context.initial_state,
            final_state=context.final_state,
            steps_text=steps_text,
        )

    @staticmethod
    def _parse_response(response_text: str) -> EpisodeSummaryResponse:
        """把 LLM 输出解析成 `EpisodeSummaryResponse`。

        失败：提不出 JSON、或 JSON 不满足 schema，都统一包成 `ValueError` 抛出——
        调用方（`generate_summary`）只需要知道"解析失败了"，不需要区分是哪一种。
        """
        import re

        json_match = re.search(r"\{[\s\S]*\}", response_text)
        if not json_match:
            raise ValueError("无法从响应中提取 JSON 对象")

        try:
            data = json.loads(json_match.group(0))
            return EpisodeSummaryResponse(
                content=data,
                rationale=data.get("rationale", f"成功完成目标'{data.get('summary', '')[:50]}...'"),
            )
        except Exception as e:
            raise ValueError(f"LLM 响应解析失败: {str(e)}") from e
