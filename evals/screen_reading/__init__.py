"""task 层无视觉读屏测评：把 task 层执行器看到的观测（解码字段 + 整屏原样）喂给文本模型，
看它能不能读懂屏幕——对话、选项、光标、叠加层、数量。

数据集 `dataset/v1/samples.jsonl` 一帧一条：屏幕缓冲（tile id）+ 人工标注。来源两批：
`experiment/observation_check/` 的 406 帧（只存了截图，缓冲按字形逐块还原，见 `glyphs.py`）
与 0926 探测的 45 帧（存档按键实采，缓冲是真的）。同一份结果里并排给两个分数：
**解码直出**（不调模型，字段原样）与**模型读后**，差值就是整屏原样带来的收益。

命令行：`python -m evals screen <build|run|report>`，见 `cli.py`。产物落 `eval_results/screen/`。
"""
