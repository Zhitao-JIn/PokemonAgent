# plan —— 主线测试可复现性收敛（565）

## 阶段与职责

1. 设计侧：原始冻结工件已恢复到独立worktree并逐文件核验；环境探针完成。
2. 提交intent/spec/plan，使用实际设计提交HEAD发自包含交接。
3. 执行者仅实现spec S1–S4、补CHANGELOG、验证并报告；禁止所有git写操作。
4. 设计侧逐项验收证据，失败退回，不代替执行者改测试。
5. 验收通过后设计侧提交实现；合入main、推送不属于本交接默认动作。

## 允许文件

- 修改pyproject.toml：仅pytest addopts增加-p no:deepeval。
- 新增tests/conftest.py：仅测试启动期dotenv/遥测隔离。
- 修改tests/reviewer/test_reviewer_entrypoint.py：仅spec S3目标函数。
- 新增tests/test_test_environment.py：2函数/3项。
- 修改CHANGELOG.md：仅顶部565条目，固定四段。
- 不改设计文档、生产模块、评测模块或冻结工件内容。

条目标题：2026-10-20（565）—— 默认测试隔离 dotenv 与 reviewer 凭据环境。
后续实现提交带Conventional Commits前缀并逐字复用标题；执行者只写条目不提交。

## 起点与命令

worktree：
C:/Users/GummiGu/.codex/worktrees/test-reproducibility/Pokemon_Agent

显式git路径：
--git-dir="D:/Users/GummiGu/PycharmProjects/Pokemon_Agent/.git/worktrees/Pokemon_Agent2"
--work-tree="C:/Users/GummiGu/.codex/worktrees/test-reproducibility/Pokemon_Agent"

解释器：
D:/Users/GummiGu/PycharmProjects/Pokemon_Agent/.venv/Scripts/python.exe（3.12.10）

始终cwd=该worktree，先确认pokemon_agent.__file__指向C盘新worktree。
按绝对路径跑外部脚本会受editable安装影响，不可依赖默认导入位置。
执行前核对完整HEAD/父提交、暂存区空、工作区受跟踪文件干净及基线N0。
本次不接触主仓库当前工作分支，它可能属于其他会话。

## 验证顺序与报告

N0：无key、禁dotenv/遥测的受控子环境，完整默认pytest，不排除任何默认选中节点。
然后新增实现；先跑S3和新测试，再两轮N1完整默认pytest（缺key/dummy key）。
受测N1不能由启动脚本提前设置S2保护，否则无法证明仓库配置有效。
日志UTF-8，stdout/stderr分开、使用独立basetemp，测试子进程必须有超时。
密钥只用固定dummy；只报告名称或存在性，不打印真实值。

完成两处配置破坏与还原；Ruff两项通过。
报告HEAD/父、status、stat、每文件改动、N0/N1 JUnit、新增3项证明、
原nodeid集合不变、两处失败与还原证据、生产零改动、数据摘要保持一致。
pyproject与CHANGELOG是共享文件，合并前重新核对main，不提前合并或重编号。
冻结数据仍属本机离线工件；交接不携带真实密钥，不上传数据，不提交eval_results。

设计侧已核验基线：三份离线工件完整；受控无key/禁dotenv/遥测/外网条件下默认全量1848 passed、3 deselected，91.05秒。执行者仍须在开始实现前重跑并留存自己的N0。
