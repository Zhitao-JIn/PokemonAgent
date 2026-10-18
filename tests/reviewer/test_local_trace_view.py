"""本地 trace 经真实存储与门面，在另一个进程中可查且没有查询写账。"""

import json
import subprocess
import sys
from pathlib import Path

from pokemon_agent.schemas.reviewer import ViewAnswer
from pokemon_agent.trace import LocalTrace


def test_another_process_can_query_a_flushed_local_trace_without_writing_events(
    tmp_path: Path,
) -> None:
    trace = LocalTrace(root=tmp_path)
    event_uuid = trace.append(
        "view",
        "sense_frame",
        {
            "run_id": "r1",
            "branch": "main",
            "episode_id": "e1",
            "task_id": "t1",
            "source": "perceive",
            "step": 1,
        },
        {"frame": "data:image/png;base64,YQ=="},
    )
    trace.flush()
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    script = """
import sys
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.reviewer.view import ViewReaders
from pokemon_agent.schemas.reviewer import FrameQuery
trace = TraceTool.build(run_id='r1', trace_root=sys.argv[1])
answer = ViewReaders(trace, None).read_frame(FrameQuery(which='latest'), default_run_id='r1')
sys.stdout.buffer.write(answer.model_dump_json().encode('utf-8'))
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, check=True
    )
    answer = ViewAnswer.model_validate(json.loads(result.stdout))

    assert answer.ok and answer.images == ["data:image/png;base64,YQ=="]
    assert event_uuid in answer.text
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
