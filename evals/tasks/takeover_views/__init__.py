"""接管视图测评：从存档停到各接管场合的初态帧，逐字段核对视图（`TaskObservation.takeover`）与屏幕一致。

期望值是对着那一帧的屏幕（与进一步翻开的列表、能力页）人工核过的；另核一组"屏上必须看得到"的字，
防止视图读的是残留内存。不调模型、不花钱，只经 world 的公开接口。

命令行：`python -m evals views run [--cases a,b]`。产物落 `eval_results/views/`。
"""
