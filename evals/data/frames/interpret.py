"""从已核标注准备文本读屏的真值解码观测，不运行待测解码器。"""

import json
from pathlib import Path

from evals.data.screen_reading.build import load_samples

INTERPRET_INPUTS = Path(__file__).with_name("interpret_inputs.json")


def freeze_interpret_inputs(version: str = "v2") -> None:
    """真值字段作为解码观测；overlay 不入输入，由文本模型读观测判。"""
    inputs: dict[str, str] = {}
    for frame in load_samples(version):
        if not frame.label_checked:
            continue
        label = frame.label
        fields = {
            "dialog_text": label.dialog_text,
            "options": label.options,
            "cursor": label.cursor,
        }
        if label.quantity is not None:
            fields["quantity"] = label.quantity
        inputs[frame.sample_id] = json.dumps(fields, ensure_ascii=False)
    INTERPRET_INPUTS.write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    freeze_interpret_inputs()
