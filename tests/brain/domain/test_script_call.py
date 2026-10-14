"""`ScriptSignature` / `ScriptArg` / `ScriptCall`：脚本调用形状的约束与默认值。

脚本调用是大脑吐出的带参数动作：签名声明脚本名、参数名、类型、是否必填，调用只保证
名字在空间里、参数类型对。本文件钉项目自己声明的约束：`required` 缺省必填、`type`
只允许 str/int、`args` 值只能是 str/int、名字非空。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pokemon_agent.brain.interface.domain import ScriptArg, ScriptCall, ScriptSignature


def test_a_script_argument_is_required_by_default_and_may_be_optional() -> None:
    assert ScriptArg(name="x", type="int").required is True
    assert ScriptArg(name="x", type="int", required=False).required is False


def test_a_script_argument_type_is_limited_to_str_and_int() -> None:
    with pytest.raises(ValidationError):
        ScriptArg(name="x", type="float")


def test_a_script_signature_defaults_to_no_parameters() -> None:
    signature = ScriptSignature(name="w")

    assert signature.params == []


def test_a_script_call_argument_value_must_be_a_string_or_integer() -> None:
    with pytest.raises(ValidationError):
        ScriptCall(name="walk_to", args={"x": 1.5})


def test_a_script_call_keeps_a_digit_string_as_a_string() -> None:
    call = ScriptCall(name="walk_to", args={"x": "5"})

    assert call.args["x"] == "5"


def test_a_script_call_name_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        ScriptCall(name="")


def test_a_script_argument_name_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        ScriptArg(name="", type="str")
