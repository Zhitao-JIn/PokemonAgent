"""记忆索引正文的确定性首句视图。"""


def first_sentence(text: str) -> str:
    """取首个句末标点或换行前的正文，至多八十字符再追加省略号；空白返回无正文。"""
    sentence = text.strip()
    for index, character in enumerate(sentence):
        if character in "。！？.!?":
            sentence = sentence[: index + 1]
            break
        if character in "\r\n":
            sentence = sentence[:index]
            break
    sentence = sentence.strip()
    if not sentence:
        return "（无正文）"
    return sentence[:80] + "…" if len(sentence) > 80 else sentence
