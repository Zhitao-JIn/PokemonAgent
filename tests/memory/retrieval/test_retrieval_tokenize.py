"""retrieval 的 tokenize：中文文本 → 字符 bigram（BM25 的分词入口）。"""

from __future__ import annotations

from pokemon_agent.memory.retrieval import tokenize


def test_tokenize_splits_text_into_character_bigrams() -> None:
    """普通多字符文本切成相邻字符对："甲乙丙" → ["甲乙", "乙丙"]。"""

    # Arrange / Act
    tokens = tokenize("甲乙丙")

    # Assert
    assert tokens == ["甲乙", "乙丙"]


def test_tokenize_drops_whitespace_before_bigramming() -> None:
    """空白字符先被剔除再切 bigram：" a b " → ["ab"]（空白不参与相邻对）。"""

    # Arrange / Act
    tokens = tokenize(" a b ")

    # Assert
    assert tokens == ["ab"]


def test_tokenize_returns_single_char_for_one_char_input() -> None:
    """单字符输入原样返回单元素列表（不足两个字符，切不出 bigram）。"""

    # Arrange / Act
    tokens = tokenize("a")

    # Assert
    assert tokens == ["a"]


def test_tokenize_returns_empty_list_for_empty_input() -> None:
    """空输入返回空列表（不是 None、也不是报错）。"""

    # Arrange / Act
    tokens = tokenize("")

    # Assert
    assert tokens == []
