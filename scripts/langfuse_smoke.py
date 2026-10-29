"""本机 self-hosted Langfuse smoke：写入普通 run 事件并读回核对。"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pokemon_agent.env import load_env_file
from pokemon_agent.trace import LangfuseTrace
from pokemon_agent.trace.langfuse_support import build_client_from_environment, read_observations

load_env_file(Path(__file__).resolve().parent.parent / ".env")
missing = [
    key
    for key in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    if not os.getenv(key)
]
if missing:
    print("缺少环境变量：" + ", ".join(missing))
    sys.exit(2)
base_url = os.environ["LANGFUSE_BASE_URL"]
host = base_url.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]
if host not in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
    print(f"拒绝连接非本机 Langfuse：{base_url}")
    sys.exit(2)
try:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/public/health", timeout=5) as response:
        health = json.loads(response.read())
except Exception as exc:  # noqa: BLE001
    print(f"Langfuse 健康检查失败：{type(exc).__name__}: {exc}")
    sys.exit(2)

client = build_client_from_environment()
run_id = f"smoke-{uuid.uuid4().hex[:8]}"
trace_id = client.create_trace_id(seed=run_id)
trace = LangfuseTrace(trace_id=trace_id, client=client)


def meta(episode_id: str = "", task_id: str = "", step: int = 0) -> dict[str, Any]:
    return {
        "source": "smoke",
        "run_id": run_id,
        "branch": "main",
        "episode_id": episode_id,
        "task_id": task_id,
        "step": step,
    }


trace.append("lifecycle", "run_start", meta(run_id, run_id), {"smoke": True})
trace.append("lifecycle", "episode_start", meta("ep-1"), {"goal": "synthetic"})
trace.append("lifecycle", "task_start", meta("ep-1", "task-1"), {"goal": "synthetic"})
trace.append("view", "sense_frame", meta("ep-1", "task-1", 1), {"frame": "synthetic"})
trace.append("act", "press_key", meta("ep-1", "task-1", 1), {"key": "a"})
trace.append(
    "model_call",
    "choose_call",
    meta("ep-1", "task-1", 1),
    {"model": "smoke-synthetic", "input_tokens": 10, "output_tokens": 2, "prompt": "synthetic"},
)
trace.append("lifecycle", "task_end", meta("ep-1", "task-1"), {})
trace.append("lifecycle", "episode_end", meta("ep-1"), {})
trace.append("lifecycle", "run_end", meta(run_id, run_id), {})
trace.flush()
expected = {
    "run_start",
    "episode_start",
    "task_start",
    "sense_frame",
    "press_key",
    "choose_call",
    "task_end",
    "episode_end",
    "run_end",
}
deadline = time.monotonic() + 60
events = []
rows = []
while time.monotonic() < deadline:
    events = trace.read_events({"run_id": run_id, "branch": "main"})
    rows = read_observations(client, trace_id)
    if expected <= {event.kind for event in events}:
        break
    time.sleep(2)
actual = {event.kind for event in events}
row_ids = {getattr(row, "id", "") for row in rows}
branch_scopes = [row for row in rows if getattr(row, "name", "") == "branch:main"]
main_run_starts = [
    row
    for row in rows
    if getattr(row, "name", "") == "run_start"
    and isinstance(getattr(row, "metadata", None), dict)
    and row.metadata.get("event_meta", {}).get("branch") == "main"
]
episode_starts = [row for row in rows if getattr(row, "name", "") == "episode_start"]
task_starts = [row for row in rows if getattr(row, "name", "") == "task_start"]
parents_ok = (
    len(branch_scopes) == len(main_run_starts) == len(episode_starts) == len(task_starts) == 1
    and (
        not getattr(branch_scopes[0], "parent_observation_id", None)
        or getattr(branch_scopes[0], "parent_observation_id", None) not in row_ids
    )
    and getattr(main_run_starts[0], "parent_observation_id", None) == branch_scopes[0].id
    and getattr(episode_starts[0], "parent_observation_id", None) == main_run_starts[0].id
    and getattr(task_starts[0], "parent_observation_id", None) == episode_starts[0].id
)
ordered = [(event.ended_at, event.seq) for event in events]
model_events = [event for event in events if event.kind == "choose_call"]
model_content = json.loads(model_events[0].content) if model_events else {}
versions_ok = bool(rows) and all(getattr(row, "version", None) == "0.1.0" for row in rows)
ok = expected <= actual and parents_ok and ordered == sorted(ordered) and versions_ok
print(f"Langfuse {health.get('version', '?')} — {'通过' if ok else '失败'}")
print(f"run_id={run_id}; events={len(events)}/{len(expected)}; missing={sorted(expected - actual)}")
print(
    f"普通层级 span={'通过' if parents_ok else '失败'}；"
    f"事件排序={'通过' if ordered == sorted(ordered) else '失败'}"
)
print(f"choose_call 内容={'通过' if model_content.get('model') == 'smoke-synthetic' else '失败'}")
print(
    f"observation version={'通过' if versions_ok else '失败'}；本地 event trace 文件未由此脚本创建"
)
print(f"Dashboard: {base_url.rstrip('/')}/project/<projectId>/traces/{trace_id}")
trace.shutdown()
sys.exit(0 if ok and model_content.get("model") == "smoke-synthetic" else 1)
