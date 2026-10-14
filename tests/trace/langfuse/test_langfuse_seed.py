"""Langfuse trace 寻址的钉子：seed 由 `(run_id, branch)` 共同决定。

依据 `docs/PLAN_trace_branch_addressing.md` §四/§八：一次执行尝试 = 一个 trace；
同 `(run_id, branch)` 重入幂等，异 branch 异 seed。装配形状用 AST 钉住
（与 `test_build.py` 同一条纪律）：防回退成裸 `run_id`。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pokemon_agent.trace.langfuse_support import langfuse_trace_seed

TRACE_PY = Path("pokemon_agent/direct/trace/__init__.py")


def test_seed_combines_run_id_and_branch() -> None:
    """seed = `run_id::branch`。"""
    assert langfuse_trace_seed("r1", "b-aa") == "r1::b-aa"


def test_seed_differs_across_branches() -> None:
    """同 run_id 不同 branch → 不同 seed（一次尝试一个 trace 的根据）。"""
    assert langfuse_trace_seed("r1", "b-aa") != langfuse_trace_seed("r1", "b-bb")


def test_seed_stable_for_same_attempt() -> None:
    """同 (run_id, branch) → seed 相同（重入追加同 trace，幂等）。"""
    assert langfuse_trace_seed("r1", "b-aa") == langfuse_trace_seed("r1", "b-aa")


def test_build_wires_seed_from_run_id_and_branch() -> None:
    """`TraceTool.build` 的 `create_trace_id` 必须 `seed=langfuse_trace_seed(run_id, branch)`。

    防回退成裸 `run_id`——那会把一个 run 的所有执行线重新混进同一个 trace
    （335 首跑的污染根源）。
    """
    tree = ast.parse(TRACE_PY.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_trace_id"
    ]
    assert len(calls) == 1, "create_trace_id 应只出现在 TraceTool.build 的 langfuse 分支"
    seed = calls[0].keywords[0].value if calls[0].keywords else None
    assert isinstance(seed, ast.Call), "seed 必须是 langfuse_trace_seed(...) 的调用"
    assert isinstance(seed.func, ast.Name) and seed.func.id == "langfuse_trace_seed"
    args = [a.id for a in seed.args if isinstance(a, ast.Name)]
    assert args == ["run_id", "branch"], "seed 实参必须是 run_id 与 branch，原样递进"


@pytest.mark.parametrize("run_id, branch", [("r1", "b-aa"), ("eval-s#e2", "b-12ab")])
def test_seed_handles_epoch_and_branch_shapes(run_id: str, branch: str) -> None:
    """epoch 后缀（#eN）与 branch 前缀都在 seed 里原样保留。"""
    assert branch in langfuse_trace_seed(run_id, branch)
    assert run_id in langfuse_trace_seed(run_id, branch)
