"""节点thinking覆盖的装配：独立provider实例，不在请求之间修改共享开关。"""

from collections.abc import Callable
from dataclasses import replace
from typing import Literal

from pokemon_agent.brain.interface import BrainPort
from pokemon_agent.brain.interface.llm_config import BrainLlmConfig
from pokemon_agent.settings import ModelsConfig

BrainLayer = Literal["run", "episode", "task"]
ModelLinkName = Literal["text", "judge", "verify", "plan"]


class NodeBrainFactory:
    """注入现有brain和接线工厂，仅为显式覆盖的可用节点装配独立依赖。"""

    def __init__(
        self,
        base: BrainPort,
        config: BrainLlmConfig,
        models: ModelsConfig,
        layer: BrainLayer | None,
        build: Callable[[BrainLlmConfig], BrainPort],
    ) -> None:
        """调用方保证config与models描述同一装配；build不发起模型请求。"""
        if models.node_thinking and layer is None:
            raise ValueError("node_thinking requires an explicit brain layer")
        self._base = base
        self._config = config
        self._models = models
        self._layer = layer
        self._build = build

    def node(self, capability: str) -> str | None:
        """返回能力实际服务的逻辑节点；run摘要虽借episode装配，仍归run。"""
        if self._layer is None:
            return None
        fixed = {
            "plan": "run.plan",
            "decompose": "episode.decompose",
            "choose": "task.choose",
            "summarize": "episode.summarize",
            "summarize_run": "run.summarize",
            "summarize_task": "task.summarize",
        }
        return fixed.get(capability, f"{self._layer}.{capability}")

    def thinking(self, capability: str, link: ModelLinkName) -> bool:
        """解析节点覆盖；缺省只继承对应模型链路，不猜测其他节点配置。"""
        node = self.node(capability)
        for name, value in self._models.node_thinking.items():
            if name == node:
                return value
        return getattr(self._models, link).thinking

    def brain(self, capability: str, link: ModelLinkName) -> BrainPort:
        """显式覆盖时复制选型并新建provider；依赖未装配时保持原入口契约。"""
        node = self.node(capability)
        spec = getattr(self._config, link)
        if spec is None or node not in self._models.node_thinking:
            return self._base
        updated = replace(spec, thinking=self.thinking(capability, link))
        return self._build(replace(self._config, **{link: updated}))
