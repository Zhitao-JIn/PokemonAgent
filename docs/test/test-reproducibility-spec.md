# spec —— 主线测试环境隔离（565）

## 一、基线与证据

分支 codex/test-reproducibility，独立worktree：
C:/Users/GummiGu/.codex/worktrees/test-reproducibility/Pokemon_Agent。
基线实现HEAD c2080f82e8e5daf941c8c33bacc5a37b4cf334fc。
本轮测试设计先提交，执行者起点以交接给出的设计提交完整HEAD为准。

本机探针在主仓库 .coordination/test-reproducibility/：
dotenv-0/1-stdout.txt、pytest-plugin-False/True-stdout.txt、
reviewer-guarded-absent/dummy-stdout.txt、capture-copy-sha256.json、audit-copy-sha256.json。
SDK源码实证：deepeval.__init__调用autoload_dotenv，插件deepeval.plugins.plugin会触发包导入；
DEEPEVAL_DISABLE_DOTENV=1可禁止该加载，-p no:deepeval可阻止pytest自动装载该插件。
合成.env只含非秘密哨兵和dummy key，探针未读取或输出真实密钥。
受控无key、禁止dotenv/遥测且禁止外网的N0完整默认全量：1848 passed、3 deselected，
91.05秒；JUnit1848、failures/errors/skipped均0，证据baseline-complete.xml。
这是外部受控条件下的基线，不代表S1–S4已实现。

## 二、已恢复的离线工件

位置均相对于新worktree，复制源为主仓库同路径，不从其他会话worktree取数据。
复制后逐文件SHA-256相同；不改源数据，不提交eval_results。

| 工件 | 文件数 | 字节 | 树摘要/文件SHA-256 |
|---|---:|---:|---|
| eval_results/brain_choose_action/task_capture_20261018_102238 | 5551 | 154608479 | e43f9a18ec3b52ab8a9b610133bc2b347edd9089317844e069717e494492ac6d |
| eval_results/brain_choose_action/supplement_20261018_172952 | 1937 | 59834101 | 5984dedb85c1566060433d4a71c1dbd664f1774dcdd54088a6d9ac7f32fed3f7 |
| eval_results/brain_goal_judge/cp0_audit.json | 1 | 417463 | 1bf77733c5ccf6d0c5d0c8b69430de1e334c5fff6494d5c0465afa530ef78ac2 |

树摘要算法：逐文件内容做SHA-256；相对路径用POSIX斜线，按路径排序；
拼接每行“相对路径+NUL+文件摘要+LF”的UTF-8字节，再SHA-256。
校验必须同时比文件集合，不能只比文件数/大小。不得写入新的捕获结果或重新调用模型。

恢复后choose/history的32项与goal audit的11项均已运行通过。
恢复两批目录会启用原有7条数据审计测试，必须同步恢复cp0_audit，不能放宽skip条件掩盖缺口。

## 三、实现契约

### S1 pytest插件启动隔离 → pyproject.toml

仅修改现有tool.pytest.ini_options.addopts，追加 -p no:deepeval。
保留现有-q、basetemp和not slow选择规则，不关闭其他插件，不全局设置PYTEST_DISABLE_PLUGIN_AUTOLOAD。
目的：在pytest11自动加载前屏蔽DeepEval插件，阻止其提前读取dotenv。
保留显式import DeepEval及原生evaluate()的使用能力；评测统计仍由现有测试验证。

### S2 显式评测导入隔离 → tests/conftest.py（新增）

在模块加载时、任何评测SDK导入前，以标准库os设置：
DEEPEVAL_DISABLE_DOTENV=1；DEEPEVAL_TELEMETRY_OPT_OUT=YES。
这里需要强制设置，不能用setdefault保留调用者的“0”。
不使用autouse fixture替代早期设置，不导入生产模块或第三方SDK。
不全局删除/覆盖用户API key，不把本规则植入生产env.py或评测CLI。
这是pytest进程的隔离策略，不改变生产命令的部署环境读取。

### S3 reviewer无效配置用例 → tests/reviewer/test_reviewer_entrypoint.py

仅修改test_invalid_entrypoint_configuration_fails_before_serve，保留函数名、三个参数值及nodeid。
允许增加monkeypatch fixture参数。

- --seats ai分支显式monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)；
  断言RuntimeError且消息匹配DEEPSEEK_API_KEY。
- http://localhost监听地址分支断言ValueError且消息匹配ws://。
- langfuse+trace-root分支断言ValueError且消息匹配--trace-root。
- 不继续使用宽泛异常集合来接受任意RuntimeError；
  不以超时、服务启动失败、缺可选SDK依赖或事件循环错误代替预期的配置错误。
- 继续使用tmp_path下不存在的env-file，三个分支均须在服务与AI构造之前退出。
- 不改生产校验逻辑，不调用私有_ai_settings，不替换生产私有函数，不安装新依赖。

### S4 新进程回归 → tests/test_test_environment.py（新增）

两个公开测试函数，参数展开3项，不引入共用假件或其他新文件。

E1 test_evaluation_import_does_not_load_dotenv（1项）：
在测试体内显式import evals.common.run，确认专用合成dotenv哨兵未进入进程环境。
若子进程携带“预期dummy key是否存在”的非秘密标志，同时确认显式继承的key存在性未被全局清除。
不输出key值；标准全量执行不要求任何真实key。

E2 test_fresh_pytest_ignores_dotenv_and_ambient_api_key（2项：absent/present）：
在tmp_path合成.env，仅写POKEMON_PYTEST_DOTENV_SENTINEL=synthetic-marker，不写真实凭据。
E1用同一哨兵名称；子进程预期key存在性标志为POKEMON_PYTEST_EXPECT_DEEPSEEK_KEY，值为0或1。
用subprocess.run启动全新python -X utf8 -m pytest，cwd为实际仓库根，
只选择本文件E1和S3的三个现有reviewer参数节点。
- ENV_DIR_PATH指向合成.env目录。
- 清除子环境中的DEEPEVAL_DISABLE_DOTENV、DEEPEVAL_TELEMETRY_OPT_OUT，
  以及PYTEST_ADDOPTS、PYTEST_DISABLE_PLUGIN_AUTOLOAD、PYTEST_CURRENT_TEST和专用哨兵，
  确保检验仓库配置本身，而不是继承父pytest已设置的保护。
- absent场景删除子环境的DEEPSEEK_API_KEY；present设为固定无效dummy值；
  不读取或记录真实key。设置非秘密的预期存在性标志供E1核对。
- 子进程MCP_MEMORY_SERVER_URL置空，避免测试回归时误接本机服务。
- 不在子命令显式加-p no:deepeval或全局禁插件，否则会掩盖S1缺失。
- 捕获UTF-8 stdout/stderr，独立basetemp，超时30秒；
  返回码必须0，并报告四个子节点均通过。超时直接失败，不skip/xfail。
- 不做整个测试文件递归执行；只选择E1，禁止子进程再运行E2。
- 不构造真实AI SDK，不连接真实模型；正常路径应在配置校验处退出。

E1默认全量1项、E2参数化2项；子pytest的4项不并入外层JUnit计数。
测试材料写在tmp_path，结束后由pytest管理；不在仓库根生成.env。

## 四、验收

- 永久实现diff仅pyproject.toml、tests/conftest.py、
  tests/test_test_environment.py、tests/reviewer/test_reviewer_entrypoint.py、CHANGELOG.md。
- S3三个原nodeid与参数值不变，新外层测试恰好3项；
  当前基线默认选中1848项，预期N1=1851项，原3条slow仍deselected。
  数据完整时不得保留原7条数据审计skip，不新增skip/xfail。
- 执行前先在受控无key、明确禁止dotenv/遥测的子环境重跑N0并留JUnit，
  不冒险在未修正用例上直接用dummy key运行完整原始全量。
  禁止靠deselect reviewer节点获得N0或N1。
- N1分别在DEEPSEEK_API_KEY缺失和固定dummy值两种环境运行默认完整pytest，
  不通过外部命令预设DEEPEVAL_DISABLE_DOTENV或DEEPEVAL_TELEMETRY_OPT_OUT来代替S1/S2。
  两轮均应1851 passed、3 deselected，failures/errors/skipped均0。
- E2两个新进程场景通过；原生DeepEval统计用例
  tests/test_evals_choose.py及tests/evals/test_evals_tasks.py通过；
  tests/world 244、tests/mcp_servers 42继续通过，Ruff check与format --check通过。
- 禁止修改pokemon_agent/、evals/、原始数据、其他测试或用例分母。
  数量偏离先报告，不改断言/标记凑绿。

## 五、检出力检查

只做两处临时配置破坏，分别备份并逐字节还原，不改SDK安装目录。
1. 去掉S1的-p no:deepeval，运行E2的absent场景：
   DeepEval插件提前把哨兵加载，E1应断言失败，从而E2失败。
2. S1保留，将S2的DEEPEVAL_DISABLE_DOTENV暂改成0：
   E1显式导入评测模块时加载合成.env，同样应失败。
只接受哨兵隔离断言失败；SDK缺失、收集错误、语法错误、超时不是有效检出。
还原后E1/E2及S3全部通过；配置/源码diff仅保留批准实现。
