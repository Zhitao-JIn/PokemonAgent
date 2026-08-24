"""run manifest —— 一次实验的全部不变量。

## 为什么要分两层

trace 是**每步一条**的事件流，manifest 是**每次实验一份**的快照。
把 prompt 原文、模型配置这些全程不变的东西塞进每条事件，跑一万步就存一万遍同样的内容。

分层之后各归各位：

| | 放什么 | 判据 |
|---|---|---|
| manifest | prompt 原文、模型与温度、git commit、预处理方式 | 全程不变 |
| trace 事件 | frame_sha、tokens、延迟、模型原始输出 | 每步都变 |

## 为什么 prompt 要存原文而不是只存 sha

`prompt_sha` 只有在**查得到内容**时才有意义。改了 prompt 没提交就跑实验，
那个 sha 就指向虚空——三周后你拿着一批数字，不知道它们是哪一版 prompt 跑出来的。
manifest 里存原文，这个依赖就断了。

## 不存什么

API key。它不进任何会被写出去的东西，`config()` 也不返回它。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from pokemon_agent.prompts import load as load_prompt


@runtime_checkable
class Configurable(Protocol):
    """能自报配置的东西。

    **刻意不放进 `LLMProvider` / `VisionProvider`。** 那两个 Port 描述的是能力，
    自报配置是可复现性的需求，属于另一个关注点。用结构化类型在这里单独表达，
    provider 不需要显式声明实现它，Port 也不用变宽。
    """

    def config(self) -> dict[str, str]: ...


def _git_commit() -> str:
    """当前 commit。取不到就记明取不到，不猜、不留空。

    取不到本身是有信息的：说明这次实验跑在一个非 git 环境或脏状态下，
    事后应当对它的可复现性打个折扣。
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        )
        sha = out.stdout.strip()[:12]
    except Exception:  # noqa: BLE001  取不到 commit 不该让实验跑不起来
        return "unavailable"

    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return sha

    # 脏工作区必须标出来：代码和 commit 对不上时，commit 号是误导性的
    return f"{sha}-dirty" if dirty else sha


class RunManifest(BaseModel):
    """一次实验的可复现性记录。"""

    run_id: str = Field(description="本次实验的标识，trace 事件靠它归组")
    started_at: str = Field(description="ISO 时间戳，由调用方传入")
    git_commit: str = Field(default_factory=_git_commit)

    providers: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="角色 -> 配置。角色至少有 'vision' 和 'text'，配置来自 provider.config()",
    )
    prompts: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="prompt 名 -> {sha, text}。**存原文**，见模块 docstring"
    )
    preprocess: str = Field(
        default="native",
        description="图像预处理方式。熔断把它当变量（原生 vs 放大），不记就分不清哪组是哪组",
    )
    notes: str = Field(default="", description="这次想验证什么。给三周后的自己看")
    experiment_kind: str = Field(default="single_episode", description="single_episode 或 sequential_episodes")
    task_ids: list[str] = Field(default_factory=list, description="本次实验预注册的任务顺序")
    initial_state: str | None = Field(default=None, description="实验起点存档的相对路径")
    memory_policy: str = Field(
        default="session_local",
        description="摘要经验只在当前 session/run 内有效；固定值，不是消融开关",
    )

    def validate_design(self) -> RunManifest:
        """检查实验元数据足以解释成功率分母和记忆自变量。"""
        assert self.experiment_kind in {"single_episode", "sequential_episodes"}
        assert self.memory_policy == "session_local", "episode summaries are run-local"
        assert self.task_ids, "manifest must declare at least one task"
        return self

    def with_prompts(self, *names: str) -> RunManifest:
        """把这些 prompt 的原文和 sha 收进来。"""
        for name in names:
            tpl = load_prompt(name)
            self.prompts[name] = {"sha": tpl.sha, "text": tpl.text}
        return self

    def with_provider(self, role: str, provider: Configurable) -> RunManifest:
        """记一个 provider 的配置。

        配置从 `provider.config()` 取，而不是让 manifest 认识具体的 provider 类型——
        装配处才是"唯一知道具体实现是谁"的地方，这里只负责抄下来。
        """
        assert hasattr(provider, "config"), f"{type(provider).__name__} 没有 config()"
        self.providers[role] = provider.config()
        return self

    def save(self, path: pathlib.Path) -> pathlib.Path:
        """写盘。**写在 trace 之前**——先有 manifest，后有数据。

        顺序反了的话，实验中途崩溃会留下一堆无法归因的事件。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path
