"""CheckpointTool —— `CheckpointToolPort` 的唯一实现：存、取、废弃归档。

**纯读写编排，不理解游戏**：状态快照（model_dump）与世界快照字节由调用方
（harness）组装递进来；记忆层的范围查询与截断委托 `MemoryTool`（注入实例，
不 import harness）；trace 的截断按游标直接操作 JSONL 文件（按局分文件，
`event_id` 全 run 单调，游标即主前缀长度）。

落盘布局：

    checkpoints/<run_id>/                     （0909 起独立于 trace_data，见下）
    ├── step/<episode_id>/<step>.state      （模拟器世界快照，二进制）
    ├── step/<episode_id>/<step>.json       （EpisodeRunState + RunState 双重
    │                                          dump + 游标，唯一提交点）
    └── voided-<ts>/                        （废弃时间线归档，先归档后截断）

**checkpoint 根目录独立于 `trace_data/`**：`trace_data/<run_id>/`是"这个 run
的可观测事件流"——`episodes/*.jsonl`一次写入、只追加、只回放；`checkpoints/`
是另一种东西——**可变的恢复状态**，会被覆盖、会被`void_after()`整目录搬走
归档。两者语义不同，不该是同一棵树下的兄弟目录（旧布局下`void_after()`里
"改 jsonl 文件内容"和"搬 checkpoint 目录"看着像同一类操作，只是因为路径
恰好挨在一起）。`trace_data/<run_id>/episodes/`与`trace_data/<run_id>/
screenshots/`的截断（本类的另一半职责）仍然要碰，见`__init__`的
`trace_dir`参数。

**没有单独的 run 级文件**：`RunState`（目标栈/结算）跟 `EpisodeRunState` 打包进
同一份 `<step>.json`——同一局内 `RunState` 每一步都相同（只有 `dispatch`/
`reflect` 会改它，均发生在局与局之间），一份文件天然带两层信息，`resume` 只
需读一次就能同时重建两层状态，不必再猜"该读 run 锚点还是 episode 锚点"
（早期设计有一份单独覆盖写的 `run.json`，被 `resume_run()` 里一处查找歧义
坑过一次，改成现在这样彻底消掉了那类歧义，见 0909 CHANGELOG）。

**已知缺口**：一局如果连第 0 步都没跑完就崩（`_begin()` 已经完成，但图入口
`save_checkpoint` 还没来得及写第一份存档），这一局没有任何 checkpoint 可
恢复——原设计想靠一份 run 起点快照兜底这个窗口，但那份快照从来没有被恢复
逻辑读过，是死代码，删除时一并放弃了这个窗口的支持（需要时再补）。

签名原则（PLAN v4 §3）：每份 checkpoint 的 json 显式内嵌三元组
`(run_id, episode_id, step)`——加载时校验签名匹配，不靠目录位置推断。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from pokemon_agent.schemas.communication import (
    FromCheckpointToolToHarnessRestoreResp,
    FromCheckpointToolToHarnessVoidReport,
    FromHarnessToCheckpointToolSaveReq,
)
from pokemon_agent.schemas.datastore import TraceEvent
from pokemon_agent.tools.memory_tool import MemoryTool


def _safe(episode_id: str) -> str:
    """episode_id 压成文件名安全的一段（与记忆层同一规则）。"""
    import re

    return re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_-") or "unknown"


class CheckpointTool:
    """`CheckpointToolPort` 的唯一实现。持有 run 目录与记忆工具，不持有状态。"""

    def __init__(self, checkpoint_dir: Path, trace_dir: Path, memory: MemoryTool) -> None:
        """`checkpoint_dir`：这个 run 自己的 checkpoint 根（`checkpoints/<run_id>/`，
        独立于 trace_data，见类 docstring）。`trace_dir`：这个 run 的
        `trace_data/<run_id>/`——`void_after()`截断 trace/截图要用，本类不
        持有 trace 相关状态，只按这个路径读写。"""
        self._dir = Path(checkpoint_dir)
        self._step_dir = self._dir / "step"
        self._trace_dir = Path(trace_dir)
        self._memory = memory

    # ---- 存 ----

    def save(self, req: FromHarnessToCheckpointToolSaveReq) -> None:
        """存一份 checkpoint：先世界快照，后 json（json 是提交点）。"""
        target_dir = self._step_dir / _safe(req.episode_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        # 步骤 1：世界快照（先写——json 才是提交点）。
        (target_dir / f"{req.step}.state").write_bytes(req.emulator_state)
        # 步骤 2：json 提交点（原子写）。
        self._atomic_write_json(target_dir / f"{req.step}.json", self._meta(req))

    # ---- 取 ----

    def load(
        self, run_id: str, episode_id: str, step: int
    ) -> FromCheckpointToolToHarnessRestoreResp | None:
        """按三元组取 checkpoint；不成对/签名不匹配返回 None。"""
        step_json = self._step_dir / _safe(episode_id) / f"{step}.json"
        if not step_json.is_file():
            return None
        return self._read_checkpoint(step_json, run_id, episode_id, step)

    # ---- 废弃归档 ----

    def void_after(
        self, run_id: str, episode_id: str, step: int, cursor: int
    ) -> FromCheckpointToolToHarnessVoidReport:
        """废弃时间线处理（PLAN §6）：先归档后截断，主前缀外零残留。"""
        voided_dir = self._dir / f"voided-{time.strftime('%Y%m%d-%H%M%S')}"
        voided_dir.mkdir(parents=True, exist_ok=True)
        trace_events_voided = 0
        future_episodes: list[str] = []
        screenshots_voided = 0

        # 步骤 1：trace 按局分文件逐个处理——游标前的行保留，之后的行归档。
        episodes_dir = self._trace_dir / "episodes"
        kept_episodes: set[str] = set()
        voided_episodes: set[str] = set()
        if episodes_dir.is_dir():
            for path in sorted(episodes_dir.glob("*.jsonl")):
                kept_lines: list[str] = []
                voided_lines: list[str] = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        event = TraceEvent.model_validate_json(line)
                    except Exception:
                        continue  # 残行跟归档一起走
                    if event.event_id <= cursor:
                        kept_lines.append(line)
                        kept_episodes.add(event.episode_id)
                    else:
                        voided_lines.append(line)
                        voided_episodes.add(event.episode_id)
                        trace_events_voided += 1
                if voided_lines:
                    (voided_dir / path.name).write_text(
                        "\n".join(voided_lines) + "\n", encoding="utf-8"
                    )
                if kept_lines:
                    tmp = path.with_suffix(".jsonl.tmp")
                    tmp.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
                    os.replace(tmp, path)
                else:
                    path.unlink(missing_ok=True)

        # 步骤 2：废弃局 = 只出现在游标之后的事件里的局。
        future_episodes = sorted(voided_episodes - kept_episodes)
        # 目标局本身也可能整个废弃（run 级恢复放弃半途进度时它的 step≥N 都废弃）。
        target_scope: list[tuple[str, int]] = [(episode_id, step)]
        for eid in future_episodes:
            target_scope.append((eid, -1))

        # 步骤 3：记忆层截断（目标局截到 step；废弃局整局清）。
        step_memories_voided = 0
        object_events_voided = 0
        for eid, keep_step in target_scope:
            counts = self._memory.void_memory_after(eid, keep_step)
            step_memories_voided += counts["step_memories"]
            object_events_voided += counts["object_events"]

        # 步骤 4：截图归档（同号重跑会撞名加 (n)，必须搬走）。
        for eid, keep_step in target_scope:
            screenshots_voided += self._void_screenshots(run_id, eid, keep_step, voided_dir)

        # 步骤 5：废弃局的 step checkpoint 目录整体归档；目标局 step>N 的也归档。
        for eid, keep_step in target_scope:
            eid_dir = self._step_dir / _safe(eid)
            if eid_dir.is_dir():
                dst = voided_dir / f"step-{_safe(eid)}"
                shutil.move(str(eid_dir), str(dst))
            elif keep_step >= 0:
                pass  # 目录不存在 = 无可归档

        return FromCheckpointToolToHarnessVoidReport(
            run_id=run_id,
            episode_id=episode_id,
            step=step,
            cursor=cursor,
            trace_events_voided=trace_events_voided,
            future_episodes=future_episodes,
            step_memories_voided=step_memories_voided,
            object_events_voided=object_events_voided,
            screenshots_voided=screenshots_voided,
            voided_dir=str(voided_dir),
        )

    # ---- 内部 ----

    def _meta(self, req: FromHarnessToCheckpointToolSaveReq) -> dict:
        """json 提交点的内容：签名三元组 + 两层快照 + 游标 + 时间。"""
        return {
            "run_id": req.run_id,
            "episode_id": req.episode_id,
            "step": req.step,
            "state_dump": req.state_dump,
            "run_state_dump": req.run_state_dump,
            "last_event_id": req.last_event_id,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def _atomic_write_json(self, path: Path, meta: dict) -> None:
        """json 提交点原子写：临时文件 + rename，不留半截 json。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def _read_checkpoint(
        self,
        json_path: Path,
        run_id: str | None,
        episode_id: str | None,
        step: int | None,
    ) -> FromCheckpointToolToHarnessRestoreResp | None:
        """读 json + 配对世界快照，校验签名；不成对/不匹配返回 None。

        后置条件：返回的 Resp 三元组与请求一致（调用方传入的定位参数核对）。
        """
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        if run_id is not None and meta.get("run_id") != run_id:
            return None
        if episode_id is not None and meta.get("episode_id") != episode_id:
            return None
        if step is not None and meta.get("step") != step:
            return None
        state_path = json_path.with_suffix(".state")
        if not state_path.is_file():
            return None  # state/json 不成对 = 提交点未完成
        return FromCheckpointToolToHarnessRestoreResp(
            run_id=meta["run_id"],
            episode_id=meta["episode_id"],
            step=meta["step"],
            state_dump=meta["state_dump"],
            run_state_dump=meta["run_state_dump"],
            last_event_id=meta["last_event_id"],
            emulator_state=state_path.read_bytes(),
            saved_at=meta.get("saved_at", ""),
        )

    def _void_screenshots(
        self, run_id: str, episode_id: str, keep_step: int, voided_dir: Path
    ) -> int:
        """把一局 step > keep_step 的人眼截图搬进 voided（keep_step=-1 = 整局）。

        截图现在按 run 分文件夹（`trace_data/<run_id>/screenshots/`），一个 run
        内仍然是扁平的（多个 episode 共享同一个目录），按 `screenshot_filename()`
        的命名规则逐个核对 episode_id 前缀搬移；`_save_screenshot` 撞名生成的
        `(n)` 后缀文件一并搬。
        """
        screenshots_dir = self._trace_dir / "screenshots"

        moved = 0
        prefix = f"{run_id}_{episode_id}_"
        target_dir = voided_dir / "screenshots"
        for path in sorted(screenshots_dir.glob(f"{prefix}*.png")):
            stem = path.stem  # {run_id}_{eid}_{step} 或带 (n)
            suffix_part = stem[len(prefix) :]
            step_token = suffix_part.split("(")[0]
            if not step_token.lstrip("-").isdigit():
                continue  # 命名规则外的文件不动
            if int(step_token) > keep_step:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target_dir / path.name))
                moved += 1
        return moved
