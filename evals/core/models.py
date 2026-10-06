"""测评模型接线：正式选型与测试覆盖分开，密钥仍来自现有环境。"""

import os

from evals.runconfig import load_config
from pokemon_agent.env import load_env_file


def interpretation_model(override: str | None = None) -> str:
    """配置文本读屏服务；显式型号优先，不调用模型也不读取待测答案。"""
    load_env_file()
    os.environ.setdefault("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    os.environ.setdefault("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if key:
        os.environ.setdefault("QWEN_API_KEY", key)
    return override or str(load_config()["evaluation_models"]["screen_interpret"])
