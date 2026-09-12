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
def _find_root() -> pathlib.Path:
    """从本文件向上找仓库根（以 pyproject.toml 为界标）。

    不写死 `parents[N]`——目录层级一变（比如 0910 从 pokemon_agent/ 包内
    上移到根级）静默指错层，读产物路径全体偏移还难以察觉。
    """
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise FileNotFoundError("repo root (pyproject.toml) not found from real_check/common.py")


ROOT = _find_root()


def load_env_file(path: pathlib.Path = ROOT / ".env") -> None:
    """把项目根 `.env` 的 KEY=VALUE 注入 os.environ。

    契约：外部环境已有的同名变量优先，文件值不覆盖（`setdefault` 语义）；
    空值行、注释行、解析不了的行一律跳过；`.env` 不存在则静默跳过——
    核对脚本在没配密钥的机器上也能 import，缺密钥由 provider 自己报错。
    前置条件：path 存在时必须是 UTF-8 文本。
    后置条件：文件里每个非空 KEY=VALUE 都已进入 os.environ（除非外部已有同名变量）。
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, sep, value = line.partition("=")
        if not sep or not key.strip().isidentifier() or not value.strip():
            continue
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

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
    `DataCenterReviewer` 才等得到 run 图 `review` 节点发布的请求（与
    `api.py` 的装配完全同构）。延迟 import：让纯路径/纯函数的使用方
    （维度 2/3/4）不必拖起 harness 依赖。
    """
    from pokemon_agent.harness.run_data_center import DataCenterReviewer, RunDataCenter

    data_center = RunDataCenter(review_timeout=REVIEW_TIMEOUT)
    return data_center, DataCenterReviewer(data_center, timeout=REVIEW_TIMEOUT)


TRACE_ROOT = ROOT / "trace_data"
CHECKPOINT_ROOT = ROOT / "checkpoints"
"""0909 起 checkpoint 根目录独立于 trace_data（见 `EpisodeCheckpoint` 类
docstring）——`checkpoints/<run_id>/`，不再是 `trace_data/<run_id>/checkpoints/`。"""
LAST_RUN = TRACE_ROOT / ".last_realcheck.json"

MEMORY_ROOT = ROOT / "memory"
"""0910 起记忆落盘根：`memory/<kind>/<uuid>.json|.md`（一条记录一个文件，
不按 run 分层，run_id 在记录 metadata 里），不再有包内目录。"""


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
    按 mtime 取最新，再取它 events 里最近修改且非空的事件文件（0910 起一条
    事件一个 `<run_id>-<event_id>.json`，文件主名带 run_id 前缀）。
    会话重启会丢后台进程和指针文件，产物本身还在——回退扫描让维度 2/3/4
    不依赖"上一个脚本恰好跑完了最后一行"。

    指针也要过产物校验：目标 run 目录没有 `events/`（旧格式落盘，或指针悬空）
    就视为失效，穿透到回退扫描——和索引的自愈重建同一哲学，指针只是缓存。
    """
    if LAST_RUN.is_file():
        meta = json.loads(LAST_RUN.read_text(encoding="utf-8"))
        if (
            meta.get("run_id")
            and meta.get("episode_id")
            and (TRACE_ROOT / meta["run_id"] / "events").is_dir()
        ):
            return meta

    prefixes = ("restorecheck-", "realcheck-")
    candidates = sorted(
        (p for p in TRACE_ROOT.iterdir() if p.is_dir() and p.name.startswith(prefixes)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for run_dir in candidates:
        events_dir = run_dir / "events"
        if not events_dir.is_dir():
            continue
        event_files = [
            p
            for p in events_dir.glob(f"{run_dir.name}-*.json")
            if p.stat().st_size > 0 and not p.name.endswith(".tmp")
        ]
        if not event_files:
            continue
        # episode_id 从事件内容里取：文件名只有 run_id + event_id，没有局号。
        episode_id = ""
        for path in sorted(event_files, key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            eid = raw.get("episode_id", "")
            if eid and eid != run_dir.name:  # run 级事件 episode_id 位放 run_id，跳过
                episode_id = eid
                break
        if episode_id:
            return {"run_id": run_dir.name, "episode_id": episode_id}

    raise SystemExit("trace_data 下没有任何 realcheck/restorecheck 产物——先跑 check_harness")


def write_last_run(run_id: str, episode_id: str) -> None:
    """check_harness 跑完后把 (run_id, episode_id) 落成指针，供后三个脚本定位产物。"""
    LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN.write_text(
        json.dumps({"run_id": run_id, "episode_id": episode_id}, ensure_ascii=False),
        encoding="utf-8",
    )
