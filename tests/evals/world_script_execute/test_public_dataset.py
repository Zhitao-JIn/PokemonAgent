"""默认数据只测公开接口，旧内部流程及输入期望可以完整追溯。"""

import hashlib
import json

from evals.world_script_execute.dataset import load
from evals.world_script_execute.dataset.build.public_tools import public_tools
from evals.world_script_execute.dataset.loader import DATASET_DIR, DEFAULT_VERSION


def test_default_cases_match_real_registered_tool_names_and_required_arguments():
    tools = {tool.name: tool.inputSchema for tool in public_tools()}

    cases = load()

    assert len(cases) == 93
    assert not {"shop_buy", "shop_sell"} & tools.keys()
    for case in cases:
        schema = tools[case.script]
        assert set(schema.get("required", [])) <= case.args.keys(), case.case_id
        assert case.args.keys() <= schema["properties"].keys(), case.case_id
        for key, value in case.args.items():
            expected = schema["properties"][key].get("type")
            assert expected not in {"string", "integer"} or (
                isinstance(value, str) if expected == "string" else type(value) is int
            ), case.case_id
    assert {"buy_item", "sell_item"} <= {case.script for case in cases}


def test_new_version_keeps_every_public_case_and_records_every_exclusion():
    original = {case.case_id: case for case in load("v1")}
    current = {case.case_id: case for case in load()}
    manifest = json.loads((DATASET_DIR / DEFAULT_VERSION / "manifest.json").read_text("utf-8"))

    assert len(original) == 106
    assert set(original) - set(current) == {row["case_id"] for row in manifest["excluded"]}
    assert len(manifest["excluded"]) == 13
    for identity, case in current.items():
        assert case == original[identity]
    assert (
        manifest["source_cases_sha256"]
        == hashlib.sha256((DATASET_DIR / "v1" / "cases.jsonl").read_bytes()).hexdigest()
    )
    for state, digest in manifest["state_sha256"].items():
        assert (
            hashlib.sha256(
                (DATASET_DIR / DEFAULT_VERSION / "states" / state).read_bytes()
            ).hexdigest()
            == digest
        )
