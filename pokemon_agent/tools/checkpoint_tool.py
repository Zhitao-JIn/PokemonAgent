"""CheckpointTool —— `CheckpointToolPort` 的唯一实现：存、取、废弃归档。

**纯读写编排，不理解游戏**：状态快照（model_dump）与世界快照字节由调用方
（harness）组装递进来；记忆层的废弃归档委托 `MemoryTool.void_memory_after()`
（注入实例，不 import harness）；trace 的废弃处理按游标直接操作
`events/<uuid>.json` 文件——**原地打 `valid=false`，不搬走不删除**（0910
拍板③：废弃分支也是"发生过什么"的审计记录，且读端靠 valid 过滤就够，
不需要学任何跳区间逻辑）。

落盘布局：

    checkpoints/<run_id>/                     （0909 起独立于 trace_data）
    ├── step/<episode_id>/<step>.state      （模拟器世界快照，二进制）
    ├── step/<episode_id>/<step>.json       （EpisodeRunState + RunState 双重
    │                                          dump + 游标，唯一提交点）
    └── voided-<ts>/                        （废弃局的 step checkpoint 归档）

memory 侧的归档落 `memory/voided-<ts>/<kind>/`（时间戳由 MemoryTool 定），
trace 侧**没有归档**——事件只是被改写 valid 字段，文件原地不动。

**trace 截图不参与废弃处理**（0910 拍板⑨）：截图文件名 = 帧事件的 event_id，
永远递增，resume 重跑零撞名，废弃事件的截图原地保留。

**checkpoint 根目录独立于 `trace_data/`**：`trace_data/<run_id>/`是"这个 run
的可观测事件流"——一条事件一个文件、只写不删；`checkpoints/`是另一种东西
——**可变的恢复状态**，会被覆盖、会被`void_after()`整目录搬走归档。两者语义
不同，不该是同一棵树下的兄弟目录。

**没有单独的 run 级文件**：`RunState`（目标栈/结算）跟 `EpisodeRunState` 打包进
同一份 `<step>.json`——同一局内 `RunState` 每一步都相同（只有 `dispatch`/
`reflect` 会改它，均发生在局与局之间），一份文件天然带两层信息，`resume` 只
需读一次就能同时重建两层状态，不必再猜"该读 run 锚点还是 episode 锚点"。

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

from pokemon_agent.schemas.harness import (
    FromHarnessToCheckpointToolLoadReq,
    FromHarnessToCheckpointToolLoadResp,
    FromHarnessToCheckpointToolSaveReq,
    FromHarnessToCheckpointToolVoidReq,
    FromHarnessToCheckpointToolVoidResp,
    FromHarnessToMemoryToolVoidMemoryAfterReq,
)
from pokemon_agent.schemas.trace import TraceEvent
from pokemon_agent.tools.memory_tool import MemoryTool


def _safe(episode_id: str) -> str:
    """episode_id 压成文件名安全的一段（与记忆层同一规则）。"""
    import re

    return re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_-") or "unknown"


class CheckpointTool:
    """`CheckpointToolPort` 的唯一实现。持有 run 目录与记忆工具，不持有状态。"""

    def __init__(self, checkpoint_dir: Path, trace_dir: Path, memory: MemoryTool) -> None:
        """`checkpoint_dir`：这个 run 自己的 checkpoint 根（`checkpoints/<run_id>/`，
        独立于 trace_data）。`trace_dir`：这个 run 的 `trace_data/<run_id>/`——
        `void_after()` 给废弃事件打 valid 标要用，本类不持有 trace 相关状态，
        只按这个路径读写。"""
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
        self, req: FromHarnessToCheckpointToolLoadReq
    ) -> FromHarnessToCheckpointToolLoadResp | None:
        """按三元组取 checkpoint；不成对/签名不匹配返回 None。"""
        step_json = self._step_dir / _safe(req.episode_id) / f"{req.step}.json"
        if not step_json.is_file():
            return None
        return self._read_checkpoint(step_json, req.run_id, req.episode_id, req.step)

    # ---- 废弃处理 ----

    def void_after(
        self, req: FromHarnessToCheckpointToolVoidReq
    ) -> FromHarnessToCheckpointToolVoidResp:
        """废弃时间线处理（PLAN_memory_trace_layout §7）：四步，先归档后继续。

        1. **trace 打标**：扫 `events/`，`event_id > cursor` 的事件**原地**改写
           `valid=false`（不搬走不删除——废弃分支也是审计记录；读端过滤
           valid 即得干净时间线，不需要任何跳区间逻辑）。
        2. **圈定 memory 作废集合**（走 MemoryTool）：目标局 `step > N-1`（N 是
           恢复步——checkpoint N 是"第 N 步开局"，拍它时完成的只有 step 0..N-1，
           废弃分支写的 step N..M 全要作废）；该局的跨局摘要整条作废（摘要由局
           收尾蒸馏，收尾在最后一个 checkpoint 之后）；废弃局（只出现在游标后
           事件里的局）整局。knowledge 不进作废范围（全局先验、不属任何一局）。
        3. **memory 归档**：MemoryTool 把作废记录搬进 `memory/voided-<ts>/<kind>/`
           并摘出索引（不 unlink——落盘了就不丢）。
        4. **checkpoint 归档**：`target_scope` 里每一局的 step 目录整体搬进
           `checkpoints/<run_id>/voided-<ts>/`——目标局也搬（旧时间线的存档一律
           离场，重跑会写出新的那批）。

        截图不参与（拍板⑨）：event_id 永远递增，resume 重跑零撞名，废弃事件
        的截图原地保留。
        """
        run_id, episode_id, step, cursor = req.run_id, req.episode_id, req.step, req.cursor
        voided_dir = self._dir / f"voided-{time.strftime('%Y%m%d-%H%M%S')}"
        voided_dir.mkdir(parents=True, exist_ok=True)

        # 步骤 1：trace 废弃事件原地打 valid=false；顺路圈定废弃局。
        trace_events_voided = 0
        kept_episodes: set[str] = set()
        voided_episodes: set[str] = set()
        events_dir = self._trace_dir / "events"
        if events_dir.is_dir():
            for path in sorted(events_dir.glob("*.json")):
                if path.name.endswith(".tmp"):
                    continue
                try:
                    event = TraceEvent.model_validate_json(path.read_text(encoding="utf-8"))
                except Exception:
                    continue  # 残文件是预期内的运行期情况，跳过
                if event.event_id <= cursor:
                    kept_episodes.add(event.episode_id)
                    continue
                voided_episodes.add(event.episode_id)
                trace_events_voided += 1
                if not event.valid:
                    continue  # 已经是废弃标记，不重复写
                event = event.model_copy(update={"valid": False})
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(event.model_dump_json(), encoding="utf-8")
                os.replace(tmp, path)

        # 步骤 2：废弃局 = 只出现在游标之后的事件里的局；目标局本身也可能
        # 整个废弃（run 级恢复放弃半途进度时它的 step≥N 都废弃）。
        # 目标局的 keep_step 取 `step - 1`：checkpoint N 是"第 N 步开局"，拍它时
        # 完成的只有 step 0..N-1，所以保留区间是 `step <= N-1`。取 N 会让废弃
        # 分支写下的 step N 漏网——重跑又从 step N 写一条，同一局同一步两条记录。
        # `step=0` 自然落到哨兵 -1（=整局废弃），正是"从第 0 步重跑"该有的语义。
        future_episodes = sorted(voided_episodes - kept_episodes)
        target_scope: list[tuple[str, int]] = [(episode_id, step - 1)]
        for eid in future_episodes:
            target_scope.append((eid, -1))

        # 步骤 2+3：memory 层圈集合并归档（MemoryTool 自己知道 uuid → 路径，
        # 搬进 memory/voided-<ts>/<kind>/ 并摘出索引）。
        step_memories_voided = 0
        object_events_voided = 0
        episode_memories_voided = 0
        for eid, keep_step in target_scope:
            counts = self._memory.void_memory_after(
                FromHarnessToMemoryToolVoidMemoryAfterReq(episode_id=eid, step=keep_step)
            ).removed
            step_memories_voided += counts["step_memories"]
            object_events_voided += counts["object_events"]
            episode_memories_voided += counts["episode_memories"]

        # 步骤 4：target_scope 里每一局的 step checkpoint 目录整体归档（目标局也搬）。
        for eid, _keep_step in target_scope:
            eid_dir = self._step_dir / _safe(eid)
            if eid_dir.is_dir():
                dst = voided_dir / f"step-{_safe(eid)}"
                shutil.move(str(eid_dir), str(dst))

        return FromHarnessToCheckpointToolVoidResp(
            run_id=run_id,
            episode_id=episode_id,
            step=step,
            cursor=cursor,
            trace_events_voided=trace_events_voided,
            future_episodes=future_episodes,
            step_memories_voided=step_memories_voided,
            object_events_voided=object_events_voided,
            episode_memories_voided=episode_memories_voided,
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
    ) -> FromHarnessToCheckpointToolLoadResp | None:
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
        return FromHarnessToCheckpointToolLoadResp(
            run_id=meta["run_id"],
            episode_id=meta["episode_id"],
            step=meta["step"],
            state_dump=meta["state_dump"],
            run_state_dump=meta["run_state_dump"],
            last_event_id=meta["last_event_id"],
            emulator_state=state_path.read_bytes(),
            saved_at=meta.get("saved_at", ""),
        )
