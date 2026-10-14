# brain/factory 测试 spec

状态：已确认（2026-10-14）。上位文档：`docs/test/brain-test-intent.md` 第 10 节（本 spec 按探针结果细化，并去掉与现有测试重复的部分）。

## 被测对象

- `pokemon_agent/brain/build_llm_providers.py`：`build_llm_providers(config, *, plan_timeout_s=None) -> (decide, judge, verify, plan)`。
  把 `BrainLlmConfig`（`pokemon_agent/brain/interface/llm_config.py`，纯数据）里的型号名造成四个 provider，返回顺序就是 `Brain.__init__` 的形参顺序。
- `pokemon_agent/brain/vision_factory.py`：`build_vision_provider(model="qwen3.8-max", temperature=0.0, json_mode=PROVIDER_JSON_MODE)`，给 world 造一个视觉 provider。

不在本目录测的：`provider_for`（型号前缀→厂商类）和各厂商类本身，归后面的 `providers` 目录。

## 怎么观察（不碰私有属性）

- provider 的 `config()` 是公开的自报配置，返回 dict：`provider`（类名）、`model`、`temperature`、`max_tokens`、`json_mode`、`thinking`、`base_url`，值都是字符串。
- 超时没有出现在 `config()` 里。观察办法：用 `monkeypatch` 把 `urllib.request.urlopen` 换成一个记下 `timeout` 实参的假实现（`tests/brain/providers/test_provider_json_mode.py` 里 `sent_bodies` 夹具的做法，假响应是 `{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}],"usage":{}}`），再对 provider 调 `complete(LlmCompleteReq(prompt="hi"))`，读它收到的 `timeout`。四个厂商的 key 环境变量用 `monkeypatch.setenv` 设上：`DASHSCOPE_API_KEY`、`ARK_API_KEY`、`DEEPSEEK_API_KEY`。
- 不连网、不用 mock 库；这个假 `urlopen` 是手写的小替身，只写在本目录的测试文件里。

## 探针（真实代码，输入→实际输出）

| 输入 | 实际 |
|---|---|
| `build_llm_providers(BrainLlmConfig())`（四个位置都不给） | `(None, None, None, None)` |
| `text="qwen3.8-max", judge="qwen3.8-max"`，其余不给 | `(QwenProvider, QwenProvider, None, None)` |
| `text=qwen3.8-max, judge=qwen3.8-max, verify=doubao-seed-1-6-250615, plan=deepseek-v4-flash` | 类名依次 `QwenProvider`、`QwenProvider`、`ArkProvider`、`DeepSeekProvider`；`config()["model"]` 各是传入的型号名；四个实例互不相同 |
| 四个位置填同一个型号 `qwen-a` | 仍是 4 个互不相同的实例 |
| 温度（`config()["temperature"]`）按位置 | decide `'0.3'`，judge/verify/plan 都是 `'0.0'` |
| `max_tokens=7, plan_max_tokens=9` | decide/judge/verify 的 `config()["max_tokens"]` 是 `'7'`，plan 是 `'9'` |
| 不给 `max_tokens` | 都是 `'25600'` |
| 单请求 `timeout`（假 urlopen 收到的值） | decide 10；judge 45；verify 45；plan 缺省 45 |
| `plan_thinking=True`，不给 `plan_timeout_s` | plan 的超时 420，`config()["thinking"]` 是 `'true'`；其余位置仍是 10 / 45 / 45 |
| `plan_timeout_s=99`，`plan_thinking=True` | plan 的超时 99 |
| `plan_timeout_s=99`，`plan_thinking=False` | plan 的超时 99 |
| 某个位置的型号名前缀不认识（`text="gpt-4"` 或 `plan="llama"`） | `ValueError`，消息里有该型号名，且含认得的前缀 `deepseek*` / `doubao*` / `qwen*` |

`build_vision_provider` 我在沙箱里没能执行（沙箱 Python 3.10 导入不了 `pokemon_agent.world`），下表按代码读出，**执行方在写测试前必须先用项目解释器逐条跑一遍探针，与下表比对，不一致就停下汇报**：

| 输入 | 预期 |
|---|---|
| `build_vision_provider()` | `QwenProvider`；`config()["model"]=="qwen3.8-max"`；`temperature=="0.0"`；假 urlopen 收到的 `timeout==20` |
| `build_vision_provider("doubao-x")` / `("deepseek-x")` | 类名 `ArkProvider` / `DeepSeekProvider` |
| `build_vision_provider("qwen-a", json_mode=True)` 与 `json_mode=False` | `config()["json_mode"]` 分别是 `'true'` / `'false'` |
| `build_vision_provider("llama")` | `ValueError` |

## 要钉的契约（测试清单）

文件 `tests/brain/factory/test_build_llm_providers.py`
1. 不配的位置不造：四个位置都不给时全是 `None`；只配 text 和 judge 时 verify、plan 是 `None`（每个位置各有一条"只配这一个"的参数化用例）。
2. 返回顺序就是 `(decide, judge, verify, plan)`：四个位置填四个不同型号名，各自 `config()["model"]` 对得上。
3. 厂商按型号名前缀选，位置之间可以任意混搭：把 qwen / doubao / deepseek 型号名放到不同位置（至少一组交叉搭配，参数化），类名与前缀配套。
4. 每个位置各造一个实例：四个位置填同一型号名，仍是四个互不相同的对象。
5. 温度分层：decide 是 `'0.3'`，judge/verify/plan 是 `'0.0'`。
6. 输出上限：decide/judge/verify 用 `max_tokens`，plan 用 `plan_max_tokens`；不改配置时都是 `'25600'`。
7. 单请求超时（经假 urlopen 观察）：decide 10、judge 45、verify 45、plan 45；`plan_thinking=True` 时 plan 变 420、其余不变；传 `plan_timeout_s` 时，无论是否开思考，plan 都用它，且其余三个位置不受影响。
8. 型号名前缀不认识时在装配期抛 `ValueError`，消息含该型号名；对四个位置各一条（参数化）。

文件 `tests/brain/factory/test_build_vision_provider.py`
9. 缺省造一个 Qwen 视觉 provider：型号 `qwen3.8-max`、温度 `'0.0'`、超时 20（经假 urlopen）。
10. 按型号名前缀选厂商（`doubao-*`→`ArkProvider`，`deepseek-*`→`DeepSeekProvider`）；`json_mode` 显式传 `True`/`False` 时落到 `config()["json_mode"]`；不认识的前缀抛 `ValueError`。

## 不测

- `json_mode` 与 `thinking` 是否传到四个位置、`plan_thinking` 只对 plan 位置生效：`tests/brain/providers/test_provider_json_mode.py` 已有 `test_build_llm_providers_hands_json_mode_to_every_chain` 与 `test_build_llm_providers_turns_thinking_on_for_plan_only`，不重复，不搬动。
- 函数尾部"实例互不相同"的出口 `assert`：在正常输入下触发不了，契约 4 从外部行为验证它。
- `DECIDE_TIMEOUT_SECONDS` / `THINKING_TIMEOUT_SECONDS` 两个常量本身不进 `__all__`，不 import 它们；超时只经假 urlopen 观察。
- `build_vision_provider` 的 `json_mode` 缺省值取自 `pokemon_agent.config.PROVIDER_JSON_MODE`，不测缺省（随项目配置变）。
- `provider_for`、厂商类的构造期契约、HTTP 错误分类：归 `providers` 目录。

## 已知观察（不写测试，由我与用户裁决）

- O12：`pokemon_agent/brain/vision_factory.py` 位于 brain 目录，顶部却 `from pokemon_agent.world import VisionProvider`，模块自己的 docstring 也写着"这个函数住在 tools 层"。brain 要"能被整体拷走、不欠外部任何东西"，这个文件的位置与依赖方向和该原则冲突。是文件放错目录，还是 docstring 过期，待定。
- O13：`provider_for` 在 `temperature=1.7` 时不报错，温度的 0–2 范围没有被校验。意图文档里写过"温度越界被拒"的构造期用例，这与现状不符；归 `providers` 目录处理时再裁决。

## 测试风格与规模

用法示范：Arrange / Act / Assert 以空行分段，句子式测试名；不用 MagicMock，不用 `unittest.mock`，只有上面说的那个手写假 `urlopen`。
预期约 30–40 条（参数化展开后计）。

## 破坏验证（必做，各一次，做完立即还原）

- (a) `DECIDE_TEMPERATURE = 0.3` 临时改成 `0.0`：契约 5 必须失败。
- (b) 在 verify 的 `provider_for(config.verify, ...)` 里临时把 `config.verify` 改成 `config.judge`：契约 2 必须失败。
- (c) `THINKING_TIMEOUT_SECONDS = 420` 临时改成 `45`：契约 7 的"开思考"用例必须失败。
- (d) `vision_factory.py` 里 `timeout=20` 临时改成 `timeout=45`：契约 9 必须失败。
- 每次做完立即还原，确认 `git diff pokemon_agent/` 为空。

## 停止条件

- 实际行为与探针表不符（含 `build_vision_provider` 的预期表）；
- 需要改 `pokemon_agent/` 才能让测试通过；
- 需要引入 `unittest.mock` / `MagicMock`，或需要访问带下划线的私有属性才能观察；
- 在项目解释器下 `import pokemon_agent.brain.vision_factory` 失败。
