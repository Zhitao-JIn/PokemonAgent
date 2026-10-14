"""视觉 provider 的测试替身：连不上网关的 `DownVision`。"""

from __future__ import annotations

from pokemon_agent.world import VisionDescribeResp


class DownVision:
    """连不上的视觉替身。"""

    def describe(self, req: object) -> VisionDescribeResp:
        """总是失败。"""
        raise ConnectionError("gateway down")
