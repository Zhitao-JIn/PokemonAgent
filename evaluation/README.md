# evaluation/

测评子系统：跨 run 的每链路 token/延迟/失败聚合报表。规范见
[`SPEC.md`](SPEC.md)——指标定义、判据 rubric、目录/CI 约定都在那份文档里，
这里只放一句话导航。

- `eval_report.py` —— 读 `trace_data/`，按 `Source` 聚合 token/延迟/失败/
  降级，出一份跨 run 的 Markdown 报表。
- `tests/` —— 用合成事件序列验证聚合逻辑（Δt 口径、跨文件归并等）。

（曾经有一个 `audit_verdicts.py`——19 条短任务的机械复核规则，2026-09-02
已删除，见 `SPEC.md` 五节。）

不 `import pokemon_agent`：这个子系统只解析 trace JSONL 的字面结构，独立于
主包的依赖（`agent-permission`/`fastembed`），CI 里单独、快速地跑。

```bash
python -m pytest evaluation/tests -q                       # 跑这个子系统的测试
python -m evaluation.eval_report --prefix <base_run_id>     # 按批次前缀出报表
python -m evaluation.eval_report --run id1,id2              # 按显式 run_id 清单出报表
```
