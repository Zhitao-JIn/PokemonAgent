"""memory provider 契约：本地实现满足协议、构造不加载模型、前置条件在导入前断言、config 自报。

不测真实推理/向量维度/分数质量（D4）。「不加载模型」经 `sys.modules["fastembed"] = None`
让导入失败来证明（D1）：构造与断言前置都不触发 `_ensure_loaded`，所以两种环境
（fastembed 已装/未装）下都通过。
"""

from __future__ import annotations

import sys

import pytest
from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import (
    EmbeddingProviderPort,
    LocalEmbeddingProvider,
    LocalMemoryStore,
    LocalRerankerProvider,
    MemoryStorePort,
    RerankerProviderPort,
)


@pytest.fixture
def no_fastembed(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `fastembed` 从 sys.modules 里换成 None——任何 `from fastembed import …` 都会失败。"""
    monkeypatch.setitem(sys.modules, "fastembed", None)


def test_local_embedding_provider_satisfies_embedding_port() -> None:
    """`isinstance` 用 runtime_checkable 协议判定为真（结构检查，不需显式继承）。"""

    # Arrange / Act
    provider = LocalEmbeddingProvider()

    # Assert
    assert isinstance(provider, EmbeddingProviderPort)


def test_local_reranker_provider_satisfies_reranker_port() -> None:
    """同上，`RerankerProviderPort`。"""

    # Arrange / Act
    provider = LocalRerankerProvider()

    # Assert
    assert isinstance(provider, RerankerProviderPort)


def test_local_memory_store_satisfies_memory_store_port(tmp_path) -> None:
    """`LocalMemoryStore` 满足 `MemoryStorePort`（本机探针确认该协议是 runtime_checkable）。"""

    # Arrange / Act
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)

    # Assert
    assert isinstance(store, MemoryStorePort)


def test_local_embedding_provider_construction_does_not_import_fastembed(no_fastembed) -> None:
    """fastembed=None 下构造成功——构造只记模型名，不触发懒加载。"""

    # Arrange / Act
    provider = LocalEmbeddingProvider()

    # Assert
    assert provider.config() == {"model": "BAAI/bge-small-zh-v1.5", "runtime": "fastembed"}


def test_local_reranker_provider_construction_does_not_import_fastembed(no_fastembed) -> None:
    """同上，reranker 子模块。"""

    # Arrange / Act
    provider = LocalRerankerProvider()

    # Assert
    assert provider.config() == {"model": "BAAI/bge-reranker-base", "runtime": "fastembed"}


def test_embed_rejects_empty_text_list(no_fastembed) -> None:
    """空文本列表在导入模型之前即触发断言。"""

    # Arrange
    provider = LocalEmbeddingProvider()

    # Act / Assert
    with pytest.raises(AssertionError):
        provider.embed([])


def test_embed_rejects_empty_string_in_texts(no_fastembed) -> None:
    """texts 里的空字符串在导入模型之前即触发断言。"""

    # Arrange
    provider = LocalEmbeddingProvider()

    # Act / Assert
    with pytest.raises(AssertionError):
        provider.embed(["", "非空"])


def test_rerank_rejects_empty_query(no_fastembed) -> None:
    """空 query 在导入模型之前即触发断言。"""

    # Arrange
    provider = LocalRerankerProvider()

    # Act / Assert
    with pytest.raises(AssertionError):
        provider.rerank("", ["候选"])


def test_rerank_rejects_empty_documents(no_fastembed) -> None:
    """空候选列表在导入模型之前即触发断言。"""

    # Arrange
    provider = LocalRerankerProvider()

    # Act / Assert
    with pytest.raises(AssertionError):
        provider.rerank("query", [])


def test_embedding_config_reports_default_model_and_runtime() -> None:
    """embedding 默认模型 `BAAI/bge-small-zh-v1.5`，runtime `fastembed`。"""

    # Arrange / Act
    config = LocalEmbeddingProvider().config()

    # Assert
    assert config == {"model": "BAAI/bge-small-zh-v1.5", "runtime": "fastembed"}


def test_reranker_config_reports_default_model_and_runtime() -> None:
    """reranker 默认模型 `BAAI/bge-reranker-base`，runtime `fastembed`。"""

    # Arrange / Act
    config = LocalRerankerProvider().config()

    # Assert
    assert config == {"model": "BAAI/bge-reranker-base", "runtime": "fastembed"}


def test_config_reports_custom_model_name_passed_to_constructor() -> None:
    """构造时传入的自定义模型名被 config 如实报告。"""

    # Arrange / Act
    config = LocalEmbeddingProvider("custom/model").config()

    # Assert
    assert config == {"model": "custom/model", "runtime": "fastembed"}
