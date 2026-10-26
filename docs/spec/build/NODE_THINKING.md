# 模型调用节点的 thinking 配置

`models.node_thinking` 按逻辑模型调用节点覆盖 `models.text/judge/verify/plan.thinking`。
它只控制是否开启思考，不改变模型、温度、输出上限或超时；不是独立的思考token预算。
未列出的节点继承对应模型链路的开关。节点名拼错、值不是JSON布尔值时，配置加载即拒绝。

```json
{
  "models": {
    "node_thinking": {
      "run.plan": true,
      "episode.decompose": true,
      "task.verify": false,
      "episode.verify": false,
      "task.summarize": false,
      "episode.summarize": false,
      "run.summarize": false
    }
  }
}
```

将上述内容写成普通settings覆盖文件，交给`load_config`或`build_real(config=...)`。
覆盖字典遵循settings原有递归合并规则；后加载文件中同名节点覆盖前者。
当前默认 `node_thinking={}`，verify链路关闭、plan开启，保留用户选择。

| 节点 | 逻辑操作 | 缺省链路 |
| --- | --- | --- |
| `run.plan` | L0规划L1目标 | plan |
| `run.judge` | run目标判定 | judge |
| `run.summarize` | 整个run摘要 | verify |
| `episode.decompose` | L1拆成L2任务 | plan |
| `episode.judge` | episode目标判定 | judge |
| `episode.verify` | 校验task记忆 | verify |
| `episode.summarize` | episode摘要 | verify |
| `task.choose` | 动作选择 | text |
| `task.judge` | task目标判定 | judge |
| `task.verify` | 校验act记忆 | verify |
| `task.summarize` | task摘要 | verify |

这些键标识模型调用能力，不是LangGraph所有节点的枚举。不调用模型的perceive、执行按键、
写记忆等节点没有thinking开关。独立reviewer及eval结果评分员不在这张表内，沿用自己的配置。

`build_real`把run/episode/task层名传给tool装配工厂。显式覆盖节点在tool层复制选型、
装配独立provider，不修改共享provider，也不向brain传入harness节点名。
run摘要借episode的装配能力，但其配置与trace标签固定为`run.summarize`。

Qwen、DeepSeek、Ark、Claude、OpenAI全部经过已有统一provider工厂，使用厂商原生开关：
Qwen发送`enable_thinking`；DeepSeek/Ark发送`thinking.type`；Claude发送自适应/禁用模式；
OpenAI选择已配置effort或`none`。文本与带图调用均使用节点选定实例，不靠prompt模拟开关。
模型本身若不支持相应模式，仍按已有provider错误语义报错，不假装开启成功。

每次model_call的payload增加`thinking_node`、`thinking_configured`和`thinking_effective`，
值沿用trace载荷的字符串格式。配置完整内容仍进run的config快照。plan/decompose原有
EmptyCompletion后的纯文本重试关闭思考规则保留，trace分别记录配置值和当次覆盖值；
不把失败请求及其用量从报告里删掉。开关不承诺模型必定产生非零reasoning token，真实用量仍读usage。

本改动用HTTP替身核对五家provider的文本/带图请求、不同层节点隔离、默认继承、
verify与摘要的独立开关、run/task摘要归属、空正文重试及trace；不以离线测试宣称真实任务质量或费用改善。
