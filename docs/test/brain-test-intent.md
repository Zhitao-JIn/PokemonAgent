# intent —— brain 模块单元测试：按功能逐个钉住契约

> 状态：**已确认，逐目录执行**（2026-10-14 用户定：全部都写、一个功能目录一个功能目录地交接；第九节四点按下文“处理”栏办）
> 执行依据：每个功能目录一份 spec（`docs/test/brain-<目录名>-spec.md`），本文件只是总意图；两者不一致以 spec 为准。已出 spec：`brain-choose-spec.md`
> 起草：2026-10-14
> 前置：CHANGELOG（446）（447）——测试已按 模块 → 功能 分目录，共用替身住 `tests/_doubles/`
> 关联：`pokemon_agent/brain/`、`brain/interface/brain_port.py`、AGENTS.md 第三节第 4、5 条（契约 / 测试是用法示范）

---

## 一、一句话意图

把 `brain` 当成一个**第三方库**来测：只经它自己的 `BrainPort` 与两个 provider 契约说话，
用一个按脚本回话的假 provider，证明每个方法**承诺的后置条件成立、每类失败都有名字且带账**——
不连网、不碰模拟器、不依赖时间戳精确值。

## 二、为什么现在做

1. `Brain` 的七个方法目前**没有任何直接测试**。仓库里 `Brain` 只经 `test_p5_script_actions` 的集成路径被碰到一次，
   `choose` 的解析分支（脚本参数、幻觉动作、截断）、`verify` 的"漏条补负样本"、`summarize` 的两种外层写法都没人守。
2. CLAUDE.md 把"大脑不会选出动作空间之外的动作"当作核心主张，出口 assert 是运行时证据，
   但**没有一条测试证明失败时走的是显式异常、而不是 assert**。
3. provider 层只测了 JSON 模式、thinking、空回复；错误映射（4xx / 5xx / 总时长闸）、
   丢图检测（`ImageNotDelivered`）、网格拼图这些**花钱出错的地方**没有测试。
4. 后面要按模块重写 `direct` / `harness` 的测试，它们都以 `brain` 的行为为前提；先把这块钉稳。

## 三、是什么 / 不是什么

**是**：
- 每个功能目录若干"一句话命名"的测试，读起来是 `brain` 的使用说明；
- 一套 `tests/_doubles/llm.py` 的脚本化假 provider（记录收到的每一次调用），所有 `Brain` 测试共用；
- 现有 3 个 brain 测试文件保留并归位，缺口补在旁边。

**不是**：
- 不是 `direct/brain_tool.py` 的重试循环测试（那是 `direct` 模块的事，下一轮写）；
- 不是 prompt 内容测试（`direct/prompts/` 已有）；
- 不测真实模型输出质量（那是 `evals/`）；
- **不把实现缺陷钉成预期**：写测试时若发现行为与 docstring 不符，先报告、定了改法再写，
  不会为了让测试变绿而把错误行为断言下来。

## 四、硬边界

1. 零联网：provider 一律注入假实现，HTTP 层用 `monkeypatch` 换 `urllib.request.urlopen`（沿用 `test_provider_json_mode.py` 的做法）。
2. 不测私有函数（AGENTS.md 第三节第 5 条）：解析器 `_parse*` / `_collect_args` / `_strip_json_fence` 一律**经公开方法**喂文本来测；
   唯一例外是 `json_utils/`：`_load_json` 是所有解析共用的地基，它的容忍边界（前缀杂文、第二个对象、内部语法错误）本身就是契约，单列一组。
3. 一个测试只钉一件事，函数名是一句话；Arrange / Act / Assert 三段空行分开。
4. 不写 mock 套 mock：假 provider 是一个手写小类，不用 `MagicMock`。
5. 不改实现。发现缺陷 → 单独报告 → 经你同意再改，并写 CHANGELOG。

## 五、共用夹具（新增）

`tests/_doubles/llm.py`
- `ScriptedLLM(*replies)`：实现 `LLMProvider.complete`，按顺序回 `LlmCompleteResp`；`replies` 里放异常实例则抛出；
  `.requests` 记下每次收到的 `LlmCompleteReq`；`multimodal` 默认 `False`。
- `ScriptedJudge(*replies)`：在 `ScriptedLLM` 上加 `describe`（回 `VisionDescribeResp`），`.described` 记下每次的 `VisionDescribeReq`。
- 辅助：`text_reply(text, truncated=False)` 一行造一个完整响应，免得每个测试重写 token 字段。

## 六、逐个功能的 intent

### 1. `brain/choose/` —— 决策：模型文本 → 合法 `Action`

**这块在守什么**：`choose` 的后置条件——成功时动作的每个名字都在 `keys` / `scripts` 内；失败时一律是 `DecisionAttemptFailed`，且带这一次的账，"要不要重问"留给调用方。

| 文件 | intent | 用例（一句话） |
|---|---|---|
| `test_choose_parse.py` | 模型怎么写，大脑怎么读 | `test_a_key_name_becomes_a_single_segment_with_times_one`<br>`test_a_json_fence_around_the_answer_is_tolerated`<br>`test_text_before_and_after_the_json_object_is_ignored`<br>`test_a_script_call_reads_args_from_the_nested_object`<br>`test_a_script_call_also_reads_args_flattened_at_the_top_level`<br>`test_integer_arguments_accept_digit_strings`<br>`test_fields_outside_the_signature_are_ignored`<br>`test_optional_script_arguments_may_be_missing`<br>`test_surrounding_whitespace_in_the_action_name_is_stripped` |
| `test_choose_failures.py` | 每类失败都有名字、带账、不吞 | `test_an_action_outside_the_space_fails_as_illegal_action`（账的 `error_kind == "IllegalAction"`，且异常信息里带合法集合）<br>`test_non_json_output_fails_as_parse_failure`<br>`test_a_top_level_array_fails_as_parse_failure`<br>`test_an_empty_action_name_fails_as_parse_failure`<br>`test_a_script_missing_a_required_argument_fails_as_parse_failure`<br>`test_a_non_integer_value_for_an_int_argument_fails_as_parse_failure`（含 `true` 不算整数）<br>`test_a_truncated_completion_fails_as_truncated_even_if_it_would_not_parse`（截断**先于**解析）<br>`test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry`<br>`test_a_failed_attempt_still_records_tokens_and_raw_text` |
| `test_choose_routing.py` | 转发表在 brain 这一层：有图且模型多模态才走 `describe` | `test_images_go_through_describe_when_the_model_is_multimodal`<br>`test_images_are_dropped_to_plain_text_when_the_model_is_not_multimodal`<br>`test_the_ledger_lists_only_images_actually_sent`（"带了图但没发出去"在账上看得见）<br>`test_no_images_means_plain_completion_even_for_a_multimodal_model` |
| `test_choose_contract.py` | 成功路径的后置条件与"一次尝试 = 一条账" | `test_a_successful_attempt_returns_exactly_one_ledger_entry`<br>`test_the_ledger_carries_prompt_raw_and_token_counts_as_strings`（账里标量一律 `str`，布尔小写）<br>`test_choose_never_retries_by_itself`（假 provider 只排一条回复，失败后调用次数仍为 1）<br>`test_calling_choose_without_a_decide_provider_trips_the_entry_assert` |

### 2. `brain/plan/` —— run 级规划与 episode 级拆解

**这块在守什么**：两条都是纯文本链、走 `plan_llm`、不带图；解析出 `RunPlan` / `Decomposition`，字段不合法算解析失败。

| 文件 | 用例 |
|---|---|
| `test_plan.py` | `test_a_valid_plan_object_parses_into_a_run_plan`<br>`test_a_fenced_plan_is_accepted`<br>`test_an_invalid_plan_field_fails_as_parse_failure_with_the_pydantic_reason`<br>`test_plan_never_sends_images_and_the_ledger_images_is_empty`<br>`test_the_thinking_override_reaches_the_request_and_the_ledger`（`True`/`False`/`None` 三态，账里分别是 `true`/`false`/`none`）<br>`test_plan_falls_back_to_the_judge_provider_when_no_plan_provider_is_given`<br>`test_a_provider_exception_becomes_a_plan_attempt_failure` |
| `test_decompose.py` | `test_a_valid_decomposition_parses`<br>`test_a_non_object_top_level_fails_as_parse_failure`<br>`test_a_non_positive_max_tasks_trips_the_entry_assert`<br>`test_decompose_uses_the_same_provider_as_plan`<br>`test_a_failed_decomposition_raises_decompose_attempt_failed_with_its_ledger` |

### 3. `brain/judge_verify/` —— 独立判定、校验、蒸馏

**这块在守什么**：三条链都用 `JudgeProvider`，带得到图走 `describe`、凑不齐退化 `complete`；**解析不出就抛，不再静默降级**（`verify` docstring 明写了这个决定）。

| 文件 | 用例 |
|---|---|
| `test_judge.py` | `test_done_true_is_a_success_verdict`<br>`test_interrupted_is_only_honoured_when_done_is_false`<br>`test_a_missing_why_becomes_the_placeholder_text`<br>`test_a_non_boolean_done_fails_as_judge_attempt_failed`<br>`test_non_json_output_fails_as_judge_attempt_failed`<br>`test_images_go_through_describe_and_no_images_fall_back_to_complete`<br>`test_judge_ledger_has_exactly_one_entry` |
| `test_verify.py` | `test_verdicts_come_back_the_same_length_as_the_entries_and_in_index_order`<br>`test_a_missing_index_is_marked_negative_not_a_parse_failure`<br>`test_out_of_order_and_duplicate_indexes_are_normalised`<br>`test_the_answer_may_be_a_bare_array_or_wrapped_in_verdicts`<br>`test_unparseable_output_raises_instead_of_marking_everything_unreliable`<br>`test_verify_falls_back_to_the_judge_provider`（以及对应的"独立实例"不被混用）<br>`test_verify_does_no_filtering_of_its_own` |
| `test_summarize.py` | `test_a_bare_summary_object_parses`<br>`test_a_summary_wrapped_in_an_outer_object_parses_too`<br>`test_the_markdown_field_is_split_out_of_the_summary_body`<br>`test_a_filename_in_the_output_is_discarded`<br>`test_missing_required_fields_fail_as_summarize_attempt_failed`<br>`test_non_json_output_fails_as_summarize_attempt_failed` |

### 4. `brain/reflect/` —— 记忆整理（本版不调模型）

**intent**：钉住"`reflect` 是纯函数，不调模型、不写库、不盖章坐标"。
用例：`test_reflect_copies_before_action_and_after_into_the_reflection`、`test_reflect_does_not_touch_any_provider`（装配里一个 provider 都不给也能跑）、`test_reflect_leaves_episode_id_and_step_to_the_caller`、`test_an_empty_before_or_after_text_trips_the_entry_assert`。
**备注**：`prompt` 参数收下不读，是接口"将来可能调模型"的预留。**测试不断言它被忽略**，免得把预留钉死；只断言输出字段来自 `before` / `after` / `action_text`。

### 5. `brain/json_utils/` —— 所有解析共用的地基

**intent**：`_load_json` 的容忍边界就是契约——"只容忍值**之外**的多余内容，值内部的错一律抛、交给重试"。
这是本模块唯一直接测私有函数的地方（见硬边界 2）。
用例：`test_a_fence_with_or_without_the_json_tag_is_stripped`、`test_only_the_outermost_fence_is_handled`、`test_text_before_the_first_brace_is_skipped`、`test_a_second_object_after_the_first_is_ignored`、`test_a_top_level_array_is_a_valid_start`、`test_a_missing_comma_still_raises`、`test_single_quotes_still_raise`、`test_a_truncated_value_still_raises`、`test_text_without_any_json_value_raises`、`test_override_spells_none_and_booleans_the_way_the_ledger_expects`。

### 6. `brain/wiring/` —— 四个 provider 的缺省与回退

**intent**：`Brain.__init__` 的装配规则——`verify` / `plan` 缺省回退 `judge`；按需装配时"没配就调"被入口 assert 当场拦下，而不是拖到调用时 `AttributeError`。
用例：`test_verify_and_plan_fall_back_to_judge_when_not_given`、`test_explicit_verify_and_plan_providers_are_used_instead_of_judge`、`test_each_method_names_the_missing_provider_in_its_assert_message`（七个方法里要 provider 的六个，参数化）。

### 7. `brain/domain/` —— 对外数据形状

**intent**：这些模型是 `harness` / `schemas` 内嵌的"数据形状"，字段变动会静默打破外部。
用例：`test_an_action_is_exactly_a_key_chain_or_a_script_call`（两者都空 / 都填都拒绝）、`test_action_describe_names_the_keys_or_the_script`、`test_action_segments_view_of_a_script_action_is_empty`、`test_script_signature_declares_required_and_optional_arguments`、`test_every_result_bag_carries_its_ledger_calls`（六个结果袋参数化）、`test_model_call_error_fields_default_to_empty_strings`。

### 8. `brain/errors/` —— 异常词汇

**intent**：每类失败要有名字（AGENTS.md 第八节），replay 要按类型归类；异常根与继承关系是外部 `except` 的依据。
用例：`test_every_brain_error_descends_from_brain_error`、`test_brain_error_is_not_an_agent_error`（"自成一根"这条架构约束）、`test_all_attempt_failures_share_a_base_and_carry_their_ledger_and_source`（六个子类参数化，`source` 默认值各不相同）、`test_illegal_action_remembers_the_name_and_the_allowed_set`、`test_parse_failure_remembers_the_raw_text_and_reason`、`test_output_truncated_remembers_the_token_count`、`test_empty_completion_remembers_its_token_spend_and_finish_reason`。现有 `test_empty_completion.py` 留在 `providers/`，因为它测的是 provider 产出该异常。

### 9. `brain/providers/` —— 厂商实现（补缺口）

现有：`test_provider_json_mode.py`、`test_empty_completion.py`。新增：

| 文件 | intent | 用例 |
|---|---|---|
| `test_provider_errors.py` | HTTP 失败的归类决定了调用方"值不值得重试" | `test_a_4xx_response_is_rejected_not_retried`（401/403/400/404 → `ProviderRejected`）<br>`test_a_5xx_response_is_a_tool_timeout`<br>`test_a_network_error_is_a_tool_timeout`<br>`test_a_request_that_exceeds_the_total_deadline_is_a_tool_timeout`（用极小 `timeout` 与假的挂起请求）<br>`test_the_api_key_never_appears_in_the_error_message` |
| `test_provider_construction.py` | 构造期的契约 | `test_temperature_must_be_given_explicitly`<br>`test_temperature_outside_zero_to_two_is_refused`<br>`test_an_empty_model_name_is_refused`<br>`test_the_key_is_read_from_the_first_non_empty_env_name`<br>`test_a_missing_key_fails_at_call_time_not_import_time`（待确认实现行为，见第九节） |
| `test_provider_describe.py` | 多模态发送路与"图是花钱发的，发了等于没发更糟" | `test_describe_sends_every_image_in_one_request`<br>`test_a_reply_with_too_few_input_tokens_raises_image_not_delivered`<br>`test_the_token_floor_scales_with_the_number_of_images`<br>`test_describe_requires_images_and_a_prompt`<br>`test_complete_refuses_an_empty_prompt` |
| `test_image_grid.py` | 拼图布局是 prompt 文案的静态契约（3 列） | `test_the_grid_has_three_columns_and_ceil_n_over_three_rows`（1…10 参数化）<br>`test_one_image_is_returned_unchanged`<br>`test_the_packed_canvas_size_matches_frames_plus_four_pixel_separators`<br>`test_the_result_is_a_png_data_uri`<br>`test_packing_no_images_trips_the_entry_assert` |
| `test_provider_for.py` | 型号名前缀 → 厂商类 | `test_prefixes_pick_the_matching_vendor_class`（qwen / doubao / deepseek）<br>`test_an_unknown_prefix_raises_value_error_at_assembly_time` |

### 10. `brain/factory/` —— 接线

| 文件 | intent | 用例 |
|---|---|---|
| `test_build_llm_providers.py` | 返回顺序就是 `Brain.__init__` 的形参顺序；缺省位置返回 `None`；实例互不相同 | `test_the_tuple_order_is_decide_judge_verify_plan`<br>`test_positions_left_empty_in_the_config_come_back_as_none`<br>`test_two_positions_with_the_same_model_still_get_distinct_instances`<br>`test_decide_is_warmer_than_the_deterministic_chains`<br>`test_plan_thinking_widens_the_request_timeout`<br>`test_an_unknown_model_prefix_fails_at_build_time`<br>（json_mode / thinking 两条已有，保留在原文件） |
| `test_vision_factory.py` | 感知 provider 的缺省与收紧的超时 | `test_the_default_vision_provider_is_deterministic`<br>`test_vision_timeout_is_tighter_than_the_text_chains`<br>`test_an_unknown_model_prefix_raises_value_error` |
| `test_llm_config.py` | 选型纯数据，不连带厂商实现 | `test_importing_the_config_does_not_import_the_vendor_module`（`sys.modules` 里没有 `brain.providers`——"只为数据而来的调用方不该连带进口厂商实现面"）<br>`test_the_config_defaults_leave_every_position_unset` |

### 11. `brain/schemas/` —— 补全信封

保留现有 `test_llm_complete_req_roundtrip.py`；新增 `test_envelopes.py`：`test_complete_req_thinking_defaults_to_none`、`test_vision_req_requires_at_least_one_image_field_shape`、`test_responses_default_their_optional_token_fields_to_zero`（具体字段待读 `schemas/completion.py` / `vision.py` 后核对）。

## 七、成功标准

1. 每个功能目录的用例全绿；`pytest tests/brain` 零联网、不超过数秒；
2. `Brain` 七个方法各自：每个**后置条件**至少一条用例，每个**失败名字**至少一条用例；
3. 全量 pytest 与迁移前基线（639 passed / 2 skipped）相比只多不少，ruff check / format 通过；
4. 写测试过程中发现的实现缺陷，全部列在交付说明里，**不静默修改实现**；
5. CHANGELOG 追加一条，commit 不做（由你决定）。

## 八、预估规模

约 11 个功能目录、24 个新测试文件、约 190 条用例，外加 1 个夹具文件。
先做顺序：`choose` → `judge_verify` → `plan` → `json_utils` → `wiring` → 其余。

## 九、拍板的点（已按推荐处理）

1. **入口 assert 要不要测**（处理：测，每个方法一条）：上面我写了"没配 provider 就调会 `AssertionError`"。assert 在 `python -O` 下会被删，
   按 CLAUDE.md 它是"可执行的文档"。我倾向**测，但每个方法只一条**，作为契约示范；你不想测就整组删掉。
2. **`_load_json` / `_override` 直接测**（处理：只在 `json_utils/` 破例）：违反"不测私有函数"，我给的理由是它们是共用地基。你同意破例吗？
3. **`providers/test_provider_construction.py` 里的"缺 key 何时报错"**（处理：写到那一目录时先读实现再定，不明确就停下报告）：我还没读到实现里 `__init__` 对缺 key 的处理，
   写到那条时会先读代码再定断言，行为不明确就报给你。
4. **`reflect` 的 `prompt` 参数**（处理：不断言被忽略）：按上面备注不断言"被忽略"。
