"""只从请求抓取证据；完整值指纹可独立检查，摘要不携带图片数据。"""

import hashlib
import json

from evals.dataset.brain_calls.dataset_contract import InputCase

from .contract import Evidence


def encoded(value: object) -> str:
    """返回稳定 JSON；调用方应传入 JSON 可表示值。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def resolve(request: object, pointer: str) -> object:
    """解析 request 内 JSON pointer；不存在的字段显式失败。"""
    value = request
    for token in pointer.removeprefix("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def proof(request: object, pointer: str) -> Evidence:
    """保存完整值指纹；长值只显示摘要，不能把截断摘要当完整原值。"""
    value = encoded(resolve(request, pointer))
    return Evidence(
        pointer=pointer,
        sha256=hashlib.sha256(value.encode()).hexdigest(),
        excerpt=value[:1200],
    )


def collect(case: InputCase) -> list[Evidence]:
    """记录目标、当前事实、同请求历史与预算；从不访问响应或后续 trace。"""
    request = case.request.model_dump(mode="json")
    pointers = [f"/{key}" for key in ("goal", "goals", "max_push", "max_tasks") if key in request]
    for key in ("obs", "observation"):
        if request.get(key):
            pointers.extend(f"/{key}/{field}" for field in ("place", "facts", "scene"))
    for key in (
        "space",
        "plan",
        "details",
        "task_memories",
        "task_table",
        "episode_index",
        "last_judge",
        "memories",
        "history",
        "last_result",
        "task_index",
        "human_note",
        "objects",
        "knowledge",
        "run_index",
    ):
        if request.get(key):
            pointers.append(f"/{key}")
    return [proof(request, pointer) for pointer in pointers]
