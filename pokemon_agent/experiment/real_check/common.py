"""真实链路核对脚本的公共件：路径常量、episode_id 安全化、last-run 指针读写。

四个核对脚本各司其职、互不 import 对方的执行逻辑，只共享这里的一小撮
纯函数与路径——让每个脚本都能被独立跑（`python -m`），崩溃时能精确归因
到"哪个脚本在哪个阶段挂的"。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokemon_agent.harness.run_data_center import DataCenterReviewer, RunDataCenter

# 项目根目录：real_check/common.py → experiment → pokemon_agent → 项目根
ROOT = pathlib.Path(__file__).resolve().parents[3]

ROM = "assets/rom"
STATE = "assets/rom.state"
STEPS = 3
GOAL = "向北走一步看看反应"

# 判据直给：看到 step=STEPS-1 就停——judge 问到当前帧（第 STEPS 步）时该帧
# 还没落库，history 里最大的步号是 STEPS-1，所以判据必须按模型实际能看到的
# 步号写，"step=3" 这个字面串在 prompt 里永远不会出现。
SUCCESS_CRITERIA = (
    f"看到 step={STEPS - 1} 就停（why 写「步数用尽」）。"
    "没到之前，看到目标所述动作完成且画面出现反应才判完成，没看到就判 false。"
)

# human review 等待时长（秒）：与 api.py 同一环境变量同一缺省——核对脚本
# 没有前端，review 请求没人答，等满这一段按 STOP 收场（沉默≠继续）。
REVIEW_TIMEOUT = float(os.environ.get("POKEMON_REVIEW_TIMEOUT", "60"))


def make_review_pair() -> tuple[RunDataCenter, DataCenterReviewer]:
    """造一对共占同一个 `RunDataCenter` 的 (数据中心, 审查者)——直接给
    `build_real(reviewer=..., data_center=...)` 用。同一个实例传两处，
    `DataCenterReviewer` 才等得到 `RunHarness.review()` 发布的请求（与
    `api.py` 的装配完全同构）。延迟 import：让纯路径/纯函数的使用方
    （维度 2/3/4）不必拖起 harness 依赖。
    """
    from pokemon_agent.harness.run_data_center import DataCenterReviewer, RunDataCenter

    data_center = RunDataCenter(review_timeout=REVIEW_TIMEOUT)
    return data_center, DataCenterReviewer(data_center, timeout=REVIEW_TIMEOUT)


TRACE_ROOT = ROOT / "trace_data"
CHECKPOINT_ROOT = ROOT / "checkpoints"
"""0909 起 checkpoint 根目录独立于 trace_data（见 `CheckpointTool` 类
docstring）——`checkpoints/<run_id>/`，不再是 `trace_data/<run_id>/checkpoints/`。"""
LAST_RUN = TRACE_ROOT / ".last_realcheck.json"

STEP_MEMORY_DIR = ROOT / "pokemon_agent" / "memory" / "episode" / "memory"
OBJECT_EVENTS_DIR = ROOT / "pokemon_agent" / "memory" / "semantic" / "object_events"


def safe(episode_id: str) -> str:
    """episode_id 压成文件名安全的一段（与 checkpoint/memory 层同一规则）。"""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_-") or "unknown"


def read_last_run() -> dict[str, str]:
    """读 check_harness 写下的 run/episode 指针；没有就说明产物还没生成。"""
    if not LAST_RUN.is_file():
        raise SystemExit(f"找不到 {LAST_RUN} —— 先跑 check_harness 生成产物")
    return json.loads(LAST_RUN.read_text(encoding="utf-8"))


def resolve_run() -> dict[str, str]:
    """定位最近一次真实 run 的产物：优先 last-run 指针，指针缺失/失效时回退扫描。

    回退规则：`trace_data/` 下名字以 `restorecheck-` / `realcheck-` 开头的目录
    按 mtime 取最新，再取它 episodes 里最近修改且非空的 episode 级 jsonl
    （run 级文件名是 `<run_id>.jsonl`，episode 级是 `<run_id>-ep*.jsonl`）。
    会话重启会丢后台进程和指针文件，产物本身还在——回退扫描让维度 2/3/4
    不依赖"上一个脚本恰好跑完了最后一行"。
    """
    if LAST_RUN.is_file():
        meta = json.loads(LAST_RUN.read_text(encoding="utf-8"))
        if meta.get("run_id") and meta.get("episode_id"):
            return meta

    prefixes = ("restorecheck-", "realcheck-")
    candidates = sorted(
        (p for p in TRACE_ROOT.iterdir() if p.is_dir() and p.name.startswith(prefixes)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for run_dir in candidates:
        episodes = run_dir / "episodes"
        if not episodes.is_dir():
            continue
        ep_files = [p for p in episodes.glob(f"{run_dir.name}-ep*.jsonl") if p.stat().st_size > 0]
        if not ep_files:
            continue
        ep_file = max(ep_files, key=lambda p: p.stat().st_mtime)
        return {"run_id": run_dir.name, "episode_id": ep_file.stem}

    raise SystemExit("trace_data 下没有任何 realcheck/restorecheck 产物——先跑 check_harness")


def write_last_run(run_id: str, episode_id: str) -> None:
    """check_harness 跑完后把 (run_id, episode_id) 落成指针，供后三个脚本定位产物。"""
    LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN.write_text(
        json.dumps({"run_id": run_id, "episode_id": episode_id}, ensure_ascii=False),
        encoding="utf-8",
    )
