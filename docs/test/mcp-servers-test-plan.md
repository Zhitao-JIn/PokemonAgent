# plan —— mcp_servers 单元测试：检查点、编号与验收

> 依据：`docs/test/mcp-servers-test-intent.md`（已确认）、`docs/test/mcp-servers-spec.md`。
> 分支：`tests/mcp-servers`，基线 `5964222`（= main）。worktree：`.worktrees/mcp-servers-test`。

## 一、检查点

| 序 | 编号 | 内容 | 依赖 |
|---|---|---|---|
| CP1 | 500 | 连接性收敛：删无效断言、拆 read_wram、待迁用例加 docstring 标注、CHANGELOG 500 | 无 |

只有一个检查点：mcp 线不迁入、不删除任何用例。世界逻辑迁移归 world 线（`claude/world-test-intent.md` 尚未确认，不在本分支）。

## 二、验收核对点（设计侧）

1. `git diff --stat` 只涉及 spec 第四节允许的 4 个文件。
2. 用例名集合：除 `test_read_wram_preserves_bytes_and_lease` 拆成两个新名字外，名字完全一致；总数 +1（junit 实测）。
3. 三项检查全绿；`tests/mcp_servers/` 耗时 ≤ 3 秒。
4. 破坏验证结果与还原。
5. CHANGELOG 500 与实际改动相符。
6. 行尾：`git diff --stat` 与 `--ignore-cr-at-eol --stat` 一致。

## 三、允许改动的文件

- `tests/mcp_servers/test_mcp_world_server.py`
- `tests/mcp_servers/test_mcp_script_tools.py`
- `tests/mcp_servers/test_mcp_health.py`（仅 docstring）
- `CHANGELOG.md`

## 四、回退

一个检查点一个提交，回退用 `git revert`。

## 五、耗时

约 1 轮验收。无真实模型，无 ROM，无联网。

## 六、PR 组织

整条分支一个 PR，提交顺序：先 docs 设计提交（intent/spec/plan），再 CP1 的实现提交。

## 七、遗留（另案）

- world 线迁移（`claude/world-test-intent.md` 草案，未确认）；
- K1：`_lease_owner` 模块级私有访问；
- `test_load_env_file_*` 的归属；
- `mcpclient/world_tool/` 的世界逻辑用例迁移（归 world 线）。
