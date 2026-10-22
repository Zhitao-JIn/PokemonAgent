# intent —— 主线测试可复现性收敛（565）

## 目标

在 main 基线 c2080f82e8e5daf941c8c33bacc5a37b4cf334fc 上，恢复完整的本机离线证据，
让默认 pytest 不读取部署 dotenv，不因调用者是否配置 DEEPSEEK_API_KEY 而进入常驻服务。
恢复真实证据，不修改评测真值、请求、历史、标签或游戏逻辑。

## 已核验问题

1. choose/history 用例缺少被忽略的采集文件；恢复两批数据后，相关32项已过。
2. 两批采集目录恢复后，goal judge审计的7项由原先skip转为执行，暴露第三个缺口：
   eval_results/brain_goal_judge/cp0_audit.json。恢复该文件后审计11项已过。
3. DeepEval安装了pytest11插件。pytest自动加载插件时先import deepeval，包初始化执行autoload_dotenv；
   即使只收集reviewer文件，合成dotenv哨兵也会进入os.environ。
   发生时机早于测试收集，autouse fixture不足以解决。
4. reviewer的“无效配置”用例将 --seats ai 当作必然失败，却没有声明缺key前置条件。
   用手写AI替身及服务构造哨兵实证：缺key正常提前拒绝；dummy key存在时越过校验到达服务构造。
   不需要真实密钥、真实模型或真实常驻服务就能证明该路径。

## 边界

- 本轮设计/实现只处理测试启动配置及测试环境隔离，不改pokemon_agent或evals生产代码。
- 不新增skip/xfail、不deselect挂死节点，不删用例或改冻结数据以换取绿灯。
- pytest的本地loopback集成测试继续保留；禁止外网和真实模型调用。
- 不清理其他会话工作树，不处理world门事件缺陷，不修改main现有未提交内容。
- 本机原始证据仍是未跟踪的离线工件。新机器需要先恢复并校验这三份工件；
  本轮不声称无工件也能重建真实历史，不上传工件到外部服务。
- 设计侧写文档、验收和提交；执行者不执行任何git写操作。
