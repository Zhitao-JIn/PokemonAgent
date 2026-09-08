"""run manifest：一次实验的**全部不变量**，每次实验存一份。

和 trace 分两层：trace 是每步一条的事件流，manifest 是全程不变的那些东西
（prompt 原文、模型与温度、git commit、预处理方式、权限配置）。
把它们塞进每条事件，跑一万步就存一万遍同样的内容。

**prompt 和权限配置都存原文，不只存 sha。** sha 只有在查得到内容时才有意义；
这两样都可能没进版本库（改了没提交、或本来就是运行时配置），
只存 sha 就是指向虚空——三周后拿着一批数字，说不清它们是哪一版跑出来的。

**不存 API key。** 它不进任何会被写出去的东西，`config()` 也不返回它。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

from pydantic import BaseModel, Field

from pokemon_agent.prompts import load as load_prompt


def _git_commit() -> str:
    """当前 commit。取不到就记明取不到，不猜、不留空。

    取不到本身是有信息的：说明这次实验跑在一个非 git 环境或脏状态下，
    事后应当对它的可复现性打个折扣。

    取当前 commit，脏工作区会标出来。
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
    permissions: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="配置文件名 -> {sha, text}。和 `prompts` 同一个形状、同一个理由："
        "权限配置决定 agent 能调哪些工具，是实验条件，且不在版本库里",
    )
    preprocess: str = Field(
        default="native",
        description="图像预处理方式。熔断把它当变量（原生 vs 放大），不记就分不清哪组是哪组",
    )
    notes: str = Field(default="", description="这次想验证什么。给三周后的自己看")
    experiment_kind: str = Field(
        default="single_episode", description="single_episode 或 sequential_episodes"
    )
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
        # 权限配置决定 agent 能调哪些工具。缺了它，这批 run 属于哪个消融组
        # 事后**无从判断**——和缺 prompt 原文是同一等级的问题。
        assert self.permissions, "manifest must record the permission config"
        return self

    def with_prompts(self, *names: str) -> RunManifest:
        """把这些 prompt 的原文和 sha 收进来。"""
        for name in names:
            tpl = load_prompt(name)
            self.prompts[name] = {"sha": tpl.sha, "text": tpl.text}
        return self

    def with_permissions(self, config_dir: pathlib.Path = pathlib.Path("config")) -> RunManifest:
        """把权限配置的原文和 sha 收进来。

        前置条件：`config_dir` 下存在 `context.json` 与 `permissions.json`——
            它们是 `agent_permission` 启动的硬要求（见 `harness.run()` 的
            `@initialize`），跑到这里还没有就该当场停，而不是记一份空的
            权限快照、让这批数据事后无法归因。

            这个断言要当场炸：只有 `@initialize` 读这两个文件，缺了要跑到第一次
            `harness.run()` 才炸——那时 world 已经建好、模型已经加载，越晚越贵。

        后置条件：`permissions` 里每个文件都同时有 `sha` 和 `text`。

        把权限配置的原文和 sha 收进 manifest。
        """
        for name in ("context.json", "permissions.json"):
            path = config_dir / name
            assert path.is_file(), f"permission config is missing: {path}"
            text = path.read_text(encoding="utf-8")
            self.permissions[name] = {
                "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
                "text": text,
            }
        return self

    def save(self, path: pathlib.Path) -> pathlib.Path:
        """写盘。**写在 trace 之前**——先有 manifest，后有数据。

        顺序反了的话，实验中途崩溃会留下一堆无法归因的事件。

        把 manifest 写成 JSON。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path
