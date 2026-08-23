from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, Any, List

import jinja2

from pokemon_agent.interfaces.llm import LLMProvider
from pokemon_agent.schemas.memory_episode_summary import EpisodeContext
from pokemon_agent.schemas.memory_episode_summary import EpisodeSummaryResponse
from pokemon_agent.schemas.memory_episodic import MemoryEntry
from pokemon_agent.memory.utils import _memory_entry_to_episode_steps, _create_memory_entry
from pokemon_agent.schemas.trace import ModelCall, Source
from pokemon_agent.trace import utils as trace_utils



class EpisodeMemoryGenerator:
    """情景记忆生成器 - 从已有记忆生成新记忆

    工作流程:
    1. 接收MemoryEntry列表（来自MemoryTool）
    2. 转换为EpisodeStep
    3. 构建EpisodeContext发送给LLM
    4. 解析LLM响应
    5. 返回结果（新MemoryEntry和model_call）
    """

    def __init__(self, llm_provider: LLMProvider) -> None:
        """
        前置条件: llm_provider非空
        """
        self.llm_provider = llm_provider

        # 加载提示模板
        template_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "episode_summary.md")
        with open(template_path, "r", encoding="utf-8") as f:
            self.template = jinja2.Template(f.read())

    def generate_summary(
        self,
        episode_id: str,
        run_id: str,
        goal: str,
        outcome: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成情景记忆

        前置条件: episode_id非空，outcome包含success和steps
        后置条件: 返回包含memory_entry和model_call的字典

        Args:
            episode_id: episode标识符
            run_id: run标识符
            goal: 任务目标
            outcome: 任务执行结果

        Returns:
            Dict包含:
                - memory_entry: 新的MemoryEntry对象
                - model_call: ModelCall对象
        """
        # 1. 构建请求内容
        context = self._build_context(episode_id, run_id, goal, outcome)
        prompt = self._build_prompt(context)

        # 2. 调用LLM
        start_time = datetime.now()
        completion = self.llm_provider.complete(prompt)
        latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # 3. 创建调用记录
        call = {
            "ok": "True",
            "raw": completion.text,
            "input_tokens": completion.prompt_tokens,
            "output_tokens": completion.completion_tokens,
            "latency_ms": latency_ms
        }

        # 4. 解析LLM响应
        try:
            response = self._parse_response(completion.text)
        except Exception as e:
            # 创建失败的调用记录
            call = {
                "ok": "False",
                "raw": completion.text,
                "error_kind": "MemorySummaryParseFailure",
                "error": f"{type(e).__name__}: {str(e)[:200]}",
                "input_tokens": completion.prompt_tokens,
                "output_tokens": completion.completion_tokens,
                "latency_ms": latency_ms
            }
            raise

        # 5. 创建情景记忆条目
        memory_entry = _create_memory_entry(
            episode_id,
            run_id,
            goal,
            outcome,
            response.content.dict()
        )

        # 6. 创建模型调用记录
        model_call = ModelCall(
            source=Source.MEMORY,
            input_tokens=int(call.get("input_tokens", 0)),
            output_tokens=int(call.get("output_tokens", 0)),
            latency_ms=int(call.get("latency_ms", 0)),
            attempt=1,
            ok=call.get("ok") == "True",
            depth=0,
            request="memory-summary-prompt",
            response=call.get("raw", "")
        )

        return {
            "memory_entry": memory_entry,
            "model_call": model_call
        }


    def _build_context(
        self,
        episode_id: str,
        run_id: str,
        goal: str,
        outcome: Dict[str, Any]
    ) -> EpisodeContext:
        """构建情景记忆生成所需的上下文"""
        # 此方法应在MemoryTool中实现
        # 这里使用简化版本
        return EpisodeContext(
            episode_id=episode_id,
            run_id=run_id,
            goal=goal,
            success=outcome.get("success", False),
            steps=outcome.get("steps", 0),
            max_steps=outcome.get("max_steps", 100),
            initial_state="初始状态摘要",
            final_state="最终状态摘要",
            key_steps=[],
            applicable_scenes=["真新镇"]
        )

    def _build_prompt(self, context: EpisodeContext) -> str:
        """使用模板构建prompt"""
        steps_text = ""
        for i, step in enumerate(context.key_steps, 1):
            steps_text += f"- **决策点 #{i}**\n"
            steps_text += f"  - **思考**: {step.thought}\n"
            steps_text += f"  - **动作**: {step.action} ×{step.action_times}\n"
            steps_text += f"  - **结果**: {step.result_summary}\n"
            steps_text += f"  - **场景**: {step.scene}\n\n"

        return self.template.render(
            goal=context.goal,
            success=context.success,
            steps=context.steps,
            max_steps=context.max_steps,
            initial_state=context.initial_state,
            final_state=context.final_state,
            steps_text=steps_text
        )

    def _parse_response(self, response_text: str) -> EpisodeSummaryResponse:
        """解析LLM响应"""
        # 简化实现，实际应使用trace_utils中的JSON提取逻辑
        try:
            # 提取JSON块
            import re
            json_match = re.search(r'\{[\s\S]*?\}', response_text)
            if not json_match:
                raise ValueError("无法从响应中提取JSON对象")


            # 解析JSON
            data = json.loads(json_match.group(0))

            # 验证quality数据
            if "quality" not in data:
                data["quality"] = {"score": 0.5}
            elif not isinstance(data["quality"], dict):
                data["quality"] = {"score": 0.5}


            # 确保score在0.0-1.0范围内
            score = data["quality"].get("score", 0.5)
            data["quality"]["score"] = max(0.0, min(1.0, score))


            # 创建EpisodeSummaryResponse
            return EpisodeSummaryResponse(
                content={
                    **data,
                    "quality": data.get("quality", {})
                },
                rationale=data.get('rationale', f"成功完成目标'{data.get('summary', '')[:50]}...'")
            )
        except Exception as e:
            raise ValueError(f"LLM响应解析失败: {str(e)}") from e