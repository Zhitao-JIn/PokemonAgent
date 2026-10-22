"""trace 单元测试共用的样本拼装：一份签名信息齐了的 `meta`。

`LocalTrace` 没有需要替身的依赖（它只认落盘根），所以这里不放假件，只放
`signed_meta()`——契约、序号与 `local/` 三组的 Arrange 都要"签名齐了"的 `meta`，
同一份六键字典抄十几遍不值当。要改哪个键就传 `overrides`。

**不给"去掉某个键"的参数**：缺键本身是被测行为之一（"缺键不匹配任何筛选"），
那种用例里自己写一份短字典比调用一个 `without=` 更读得懂。
"""

from __future__ import annotations

from typing import Any

_SIGNATURE: dict[str, Any] = {
    "run_id": "run-1",
    "branch": "main",
    "source": "test",
    "episode_id": "ep-1",
    "task_id": "ep-1",
    "step": 0,
}


def signed_meta(**overrides: Any) -> dict[str, Any]:
    """返回签名齐了的 `meta`：`run_id` / `branch` / `source` / `episode_id` / `task_id` / `step`。

    `overrides` 逐个覆盖同名键（值可以是任何类型——`step` 故意给字符串的用例也在用）。
    """
    return {**_SIGNATURE, **overrides}
