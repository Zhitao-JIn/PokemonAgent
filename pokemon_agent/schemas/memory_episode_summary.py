from __future__ import annotations

import datetime
from enum import Enum
from typing import List, Dict, Optional, Literal

from pydantic import BaseModel, Field


class MemoryQualityLevel(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    UNRELIABLE = "UNRELIABLE"


class EpisodeStep(BaseModel):
    """Episode中的关键步骤"""
    thought: str = Field(..., description="决策思考过程")
    action: str = Field(..., description="执行的动作")
    action_times: int = Field(1, description="动作执行次数", ge=1)
    result_summary: str = Field(..., description="动作执行结果的简要描述")
    scene: str = Field(..., description="发生场景（游戏地图）")
    step_number: int = Field(..., description="在episode中的步骤序号")


class EpisodeContext(BaseModel):
    """情景记忆生成所需的上下文信息"""
    episode_id: str = Field(..., description="Episode唯一标识")
    run_id: str = Field(..., description="所属run的标识符")
    goal: str = Field(..., description="任务目标描述")
    success: bool = Field(..., description="Episode是否成功完成")
    steps: int = Field(..., description="实际完成步数", ge=0)
    max_steps: int = Field(..., description="最大允许步数", ge=1)
    initial_state: str = Field(..., description="初始状态摘要")
    final_state: str = Field(..., description="最终状态摘要")
    key_steps: List[EpisodeStep] = Field(..., description="关键决策步骤列表")
    applicable_scenes: List[str] = Field(default_factory=list, description="涉及的游戏场景")

class EpisodeSummaryRequest(BaseModel):
    """发送给LLM的情景记忆生成请求协议"""
    version: Literal["1.0"] = "1.0"
    context: EpisodeContext = Field(..., description="生成记忆所需的上下文")
    instruction: str = Field(
        default="你是一个资深宝可梦玩家，正在总结一次游戏经历。请基于提供的游戏过程生成有价值的情景记忆，特别注意提取可重复利用的游戏策略和经验。",
        description="给LLM的指令"
    )
    format_spec: str = Field(
        default="请严格按以下JSON Schema输出，不要添加额外内容：{'summary': 'str', 'reusable_patterns': 'list[str]', ...}",
        description="输出格式规范"
    )

class MemoryQualityScore(BaseModel):
    """记忆质量评分结构"""
    score: float = Field(..., ge=0.0, le=1.0, description="记忆质量评分(0.0-1.0)")
    level: MemoryQualityLevel = Field(..., description="质量等级")
    rationale: str = Field(..., description="质量评分的理由")

class EpisodeMemoryContent(BaseModel):
    """情景记忆的核心内容"""
    summary: str = Field(..., description="Episode的简明总结(100字以内)", max_length=200)
    reusable_patterns: List[str] = Field(default_factory=list, description="可重复利用的游戏策略和经验模式")
    critical_decisions: List[str] = Field(default_factory=list, description="关键决策点及其效果")
    failure_points: List[str] = Field(default_factory=list, description="可能导致失败的环节及规避方法")
    quality: MemoryQualityScore = Field(..., description="记忆质量评分")
    applicable_scenes: List[str] = Field(default_factory=list, description="此记忆适用的游戏场景")
    tags: List[str] = Field(default_factory=list, description="记忆标签（导航/战斗/物品收集等）")

class EpisodeSummaryResponse(BaseModel):
    """从LLM返回的情景记忆内容协议"""
    content: EpisodeMemoryContent = Field(..., description="生成的情景记忆内容")
    rationale: str = Field(..., description="为什么这条记忆有价值（用于episodic memory的rationale字段）")
    model_metadata: Dict[str, str] = Field(
        default_factory=dict,
        description="模型元数据（模型名称、温度等）"
    )
    tokens_used: Dict[str, int] = Field(
        default_factory=lambda: {"input": 0, "output": 0},
        description="LLM调用的token使用情况"
    )
    confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="LLM对生成内容的置信度"
    )
    filename: str = Field(default="episode_memory", description="用于保存 Markdown 记忆的文件名")
    markdown: str = Field(default="", description="要原样保存的 Markdown 记忆正文")
