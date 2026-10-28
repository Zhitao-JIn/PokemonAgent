"""共享片段及三个 plan 的块序、空块、固定前缀与全文契约。"""

import ast
import json
from collections.abc import Callable
from os.path import commonprefix
from pathlib import Path

import pytest
from pydantic import BaseModel

from pokemon_agent.prompt import (
    GoalParams,
    KnowledgeParams,
    PromptGateway,
    PromptLayoutParams,
)

from .layout_examples import examples
from .unit_fixtures import ExampleParams, make_unit

Compose = Callable[[str, BaseModel], str]

REGISTRY = Path(__file__).resolve().parents[2] / "pokemon_agent/prompt/registry.json"
TASKS = ("run_plan", "decompose", "decide_action")


BLOCK_NAMES = (
    "规则",
    "检索知识",
    "目标",
    "背景索引",
    "本层历史",
    "状态与反馈",
    "当前现场",
    "预算与进度",
    "人类插话",
)


@pytest.fixture(scope="module")
def compose(tmp_path_factory: pytest.TempPathFactory) -> Compose:
    root = tmp_path_factory.mktemp("fragment_wrappers")
    data = json.loads(REGISTRY.read_bytes())
    for name, contract in (
        ("goal", "GoalParams"),
        ("knowledge", "KnowledgeParams"),
        ("prompt_layout", "PromptLayoutParams"),
    ):
        wrapper = f"layout_{name}"
        body = (
            f"from pokemon_agent.prompt import {contract}\n"
            "import json\n"
            f'return json.dumps(compose("{name}", {contract}.model_validate_json(params.value)))'
        )
        make_unit(root, wrapper, body=body)
        data["tasks"][wrapper] = {"active": "v1"}
    path = root / "registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    gateway = PromptGateway(path)

    def render(name: str, params: BaseModel) -> str:
        return json.loads(
            gateway.render(f"layout_{name}", ExampleParams(value=params.model_dump_json())).text
        )

    return render


@pytest.mark.parametrize("criteria", ["", "明确判据"])
def test_goal_preserves_text_and_only_adds_supplied_criteria(
    criteria: str, compose: Compose
) -> None:
    params = GoalParams.model_validate({"entries": [{"goal": "目标全文", "criteria": criteria}]})

    text = compose("goal", params)

    assert "目标全文" in text and not text.startswith("#")
    assert ("判据" in text) == bool(criteria)
    assert not criteria or criteria in text


@pytest.mark.parametrize("entries", [[], ["单篇全文"], ["第一篇\n正文", "第二篇全文"]])
def test_knowledge_preserves_every_article_and_has_no_empty_heading(
    entries: list[str],
    compose: Compose,
) -> None:
    if not entries:
        params = examples()["run_plan"].model_copy(update={"knowledge": []})
        text = PromptGateway(None).render("run_plan", params).text
        assert "## 检索知识\n" not in text
        return
    text = compose("knowledge", KnowledgeParams(entries=entries))

    assert text == "\n\n".join(entries)
    assert not text if not entries else all(entry in text for entry in entries)


def test_layout_owns_order_and_skips_whitespace_blocks(compose: Compose) -> None:
    blocks = {block: f"正文{index}" for index, block in enumerate(reversed(list(BLOCK_NAMES)))}
    blocks["背景索引"] = "  \n"

    text = compose("prompt_layout", PromptLayoutParams(blocks=blocks))

    titles = [line for line in text.splitlines() if line.startswith("## ")]
    expected = [f"## {block}" for block in BLOCK_NAMES if block != "背景索引"]
    expected.insert(1, "## 本次输入")
    assert titles == expected
    assert "## 背景索引" not in text and "（无）" not in text


def test_knowledge_stays_in_shared_prefix_when_only_the_goal_changes(compose: Compose) -> None:
    blocks = {"规则": "共同规则", "检索知识": "知识首句。\n知识全文末句。", "目标": "读取招牌"}
    first = PromptLayoutParams(blocks=blocks)
    second = PromptLayoutParams(blocks={**blocks, "目标": "进入商店"})

    texts = [compose("prompt_layout", params) for params in (first, second)]
    shared = commonprefix(texts)

    knowledge = "## 检索知识\n\n" + blocks["检索知识"]
    assert knowledge in shared
    assert len(shared) >= texts[0].index(knowledge) + len(knowledge)


@pytest.mark.parametrize("task", TASKS)
def test_all_plans_delegate_same_named_blocks_to_the_same_fragments(task: str) -> None:
    data = json.loads(REGISTRY.read_bytes())
    path = REGISTRY.parent / "tasks" / task / data["tasks"][task]["active"] / "assemble.py"
    tree = ast.parse(path.read_bytes())
    calls = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "compose"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }

    assert {
        "goal",
        "knowledge",
        "task_frame",
        "memory_records",
        "prompt_layout",
    } <= calls


@pytest.mark.parametrize("task", TASKS)
def test_three_plans_use_the_same_order_and_move_only_rules_before_input(task: str) -> None:
    text = PromptGateway(None).render(task, examples()[task]).text

    titles = [line for line in text.splitlines() if line.startswith("## ")]

    assert titles == [
        "## 规则",
        "## 本次输入",
        *[
            f"## {b}"
            for b in BLOCK_NAMES
            if b != "规则" and not (task == "decide_action" and b == "状态与反馈")
        ],
    ]
    prefix, dynamic = text.split("## 本次输入", 1)
    assert "知识甲全文" not in prefix and "读取招牌" not in prefix
    assert "可走" in prefix
    if task == "decide_action":
        assert "当前帧只读 RAM，未调用视觉模型。" in prefix
        assert "## 状态与反馈\n" not in dynamic
    assert "example-episode" not in dynamic
    assert text.rfind("## 人类插话") > text.rfind("## 预算与进度")
    assert "FRAME_FIRST" not in text and "FRAME_LAST" not in text


@pytest.mark.parametrize("task", TASKS)
def test_three_plans_omit_all_empty_optional_blocks(task: str) -> None:
    params = examples()[task]
    empty = dict(human_note="", knowledge="" if task == "decide_action" else [])
    if task == "run_plan":
        empty.update(details=[], run_index=[], last_judge=None, plan=[], observation=None)
    elif task == "decompose":
        empty.update(task_memories=[], episode_index=[], last_judge=None, task_table=[])
    else:
        empty.update(memories=[], task_index=[])

    text = PromptGateway(None).render(task, params.model_copy(update=empty)).text

    for block in ("检索知识", "背景索引", "本层历史", "人类插话"):
        assert f"\n## {block}\n" not in text
    assert "（没有检索到相关知识）" not in text.split("## 本次输入", 1)[1]


def test_decompose_auxiliary_history_needs_no_rules_or_terrain() -> None:
    params = examples()["decompose"].model_copy(update={"terrain_meanings": {}})

    history = PromptGateway(None).render_history("decompose", params)

    assert len(history) == 2
    assert "完整招牌原文。" in history[0]
    assert "（无正文）" in history[1]
    assert "局首句。" not in history[1] and "局全文末句。" not in history[1]
    assert all("取得招牌文字" not in part and "继续核对" not in part for part in history)
