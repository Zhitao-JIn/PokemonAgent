"""评分模型的统一构造：配置 → Inspect Model；缺密钥只报变量名。"""

import os

from inspect_ai.model import GenerateConfig, Model, get_model

from evals.runconfig import ResultGraderConfig


def build_grader_model(grader: ResultGraderConfig) -> Model:
    """按配置构造评分模型；密钥只从 `api_key_env` 读，缺失时只报变量名。"""
    api_key = os.environ.get(grader.api_key_env)
    if not api_key:
        raise ValueError(f"独立结果评分员缺少密钥环境变量：{grader.api_key_env}")
    thinking = {"type": "enabled" if grader.thinking else "disabled"}
    native_openai = grader.model.startswith("openai/")
    return get_model(
        grader.model,
        config=GenerateConfig(
            temperature=grader.temperature,
            max_tokens=grader.max_tokens,
            timeout=grader.timeout_s,
            reasoning_effort=("medium" if grader.thinking else "none") if native_openai else None,
            extra_body={} if native_openai else {"thinking": thinking},
        ),
        base_url=grader.base_url,
        api_key=api_key,
    )


__all__ = ["build_grader_model"]
