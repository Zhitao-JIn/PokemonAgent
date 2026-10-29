"""用假大脑 / 假世界 / 假记忆跑真实 harness，并在本机 Langfuse 展示普通层级 span。"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from _fake_run import GOAL, build_fake  # noqa: E402

from pokemon_agent.env import load_env_file  # noqa: E402
from pokemon_agent.trace.langfuse_support import (  # noqa: E402
    build_client_from_environment,
    read_observations,
)

load_env_file(REPO / ".env")
base_url = os.environ.get("LANGFUSE_BASE_URL", "")
host = base_url.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]
if host not in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
    print(f"拒绝：LANGFUSE_BASE_URL 非本机（{base_url or '未设置'}）")
    sys.exit(2)

run_id = f"tree-{uuid.uuid4().hex[:6]}"
tmp = Path(tempfile.mkdtemp(prefix="lf_tree_"))
fake = build_fake(tmp, run_id=run_id, backend="langfuse")
fake.harness.run(run_id, [GOAL])
fake.trace.flush()
time.sleep(5)
client = build_client_from_environment()
trace_id = client.create_trace_id(seed=run_id)
rows = read_observations(client, trace_id)

print(f"run_id={run_id}\ntrace_id={trace_id}\n临时目录={tmp}\n")
for observation in rows:
    metadata = getattr(observation, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    parent = getattr(observation, "parent_observation_id", None)
    print(f"{getattr(observation, 'name', '?')}  parent={parent or '-'}")

names = {getattr(observation, "name", "") for observation in rows}
required = {"branch:main", "run_start", "episode_start", "task_start"}
missing = sorted(required - names)
print(f"\n{'通过' if not missing else '缺少层级锚点: ' + ', '.join(missing)}")
print(f"Dashboard: {base_url.rstrip('/')}/project/<projectId>/traces/{trace_id}")
fake.trace.shutdown()
sys.exit(0 if not missing else 1)
