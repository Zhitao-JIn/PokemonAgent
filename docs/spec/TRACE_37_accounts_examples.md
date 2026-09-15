# 35 种 trace 账的例子（由渲染函数真实产出）

> 生成方式：每条都调用 `tools/trace/render.py` 里对应 kind 的渲染函数，
> 封套（uuid / ts / meta / content 的字符串化）按 `trace/store.py` 的落盘规则拼——
> **形状与代码逐字一致，不是手写的**。
>
> 阅读说明：
>
> - 落盘时**一条事件一个 json 文件**（`trace_data/<run_id>/events/<uuid>.json`），
>   `meta` 与 `content` 落盘时是 **JSON 字符串（一层转义）**；
>   下文为了可读，把这两个字段**展开**显示。
> - `run` 级账（run_* / plan_*）沿用项目约定：`meta.episode_id` 位放 `run_id`、`step` 恒 0。
> - 排序真源 = `(ts, uuid)`；文件名就是 `uuid`。
>
> 下面第一条附**未展开的原样形态**（真落盘的样子），其余条目展开。

## `run_start`（type=`lifecycle`）

**落盘原样**（一行、meta/content 是转义过的 JSON 字符串）：

```json
{
  "uuid": "01a0a4a6-f7e8-75e9-8bf0-7809bde9a4aa",
  "kind": "run_start",
  "type": "lifecycle",
  "ts": 1789468801.0,
  "meta": "{\"run_id\": \"run-20260914-a\", \"source\": \"run_entry.new_run\", \"episode_id\": \"run-20260914-a\", \"step\": 0}",
  "content": "{\"goals\": [\"从真新镇出发，沿一号道路向北，打赢二号道馆\"], \"success_criteria\": [\"馆主战胜利且拿到徽章\"]}"
}
```

**展开后**：

```json
{
  "uuid": "01a0a4a6-f7e8-75e9-8bf0-7809bde9a4aa",
  "kind": "run_start",
  "type": "lifecycle",
  "ts": 1789468801.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "run_entry.new_run",
    "episode_id": "run-20260914-a",
    "step": 0
  },
  "content": {
    "goals": [
      "从真新镇出发，沿一号道路向北，打赢二号道馆"
    ],
    "success_criteria": [
      "馆主战胜利且拿到徽章"
    ]
  }
}
```

## `run_end`（type=`lifecycle`）

```json
{
  "uuid": "01a0a4a6-fbd0-74ab-adf1-cfbe15b44683",
  "kind": "run_end",
  "type": "lifecycle",
  "ts": 1789468802.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "run_entry.close",
    "episode_id": "run-20260914-a",
    "step": 0
  },
  "content": {
    "total": "3",
    "succeeded": "1"
  }
}
```

## `run_error`（type=`lifecycle`）

```json
{
  "uuid": "01a0a4a6-ffb8-7042-9571-2e188274df1d",
  "kind": "run_error",
  "type": "lifecycle",
  "ts": 1789468803.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "run_entry.new_run",
    "episode_id": "run-20260914-a",
    "step": 0
  },
  "content": {
    "error": "GraphRecursionError: Recursion limit of 25 was exceeded while dispatching task"
  }
}
```

## `episode_start`（type=`lifecycle`）

```json
{
  "uuid": "01a0a4a7-03a0-7123-a781-cf50a26ad016",
  "kind": "episode_start",
  "type": "lifecycle",
  "ts": 1789468804.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "episode_entry.begin_episode",
    "episode_id": "run-20260914-a-ep1",
    "step": 0
  },
  "content": {
    "goal": "从真新镇出发，沿一号道路向北，打赢二号道馆",
    "success_criteria": "馆主战胜利且拿到徽章",
    "max_steps": "300"
  }
}
```

## `episode_end`（type=`lifecycle`）

```json
{
  "uuid": "01a0a4a7-0788-761e-98e0-0dcdfde26468",
  "kind": "episode_end",
  "type": "lifecycle",
  "ts": 1789468805.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "close_episode",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "success": "true",
    "steps": "27",
    "reason": "success"
  }
}
```

## `episode_error`（type=`lifecycle`）

```json
{
  "uuid": "01a0a4a7-0b70-74fb-bc5b-02baadc6bcba",
  "kind": "episode_error",
  "type": "lifecycle",
  "ts": 1789468806.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "episode_entry.run_new",
    "episode_id": "run-20260914-a-ep1",
    "step": 14
  },
  "content": {
    "error": "MaxRetriesExceeded: judge 链重试 3 次均解析失败"
  }
}
```

## `step_advance`（type=`lifecycle`）

```json
{
  "uuid": "01a0a4a7-0f58-7a7e-b20d-b28fbb37b2ac",
  "kind": "step_advance",
  "type": "lifecycle",
  "ts": 1789468807.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "close_step",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "next_step": "4"
  }
}
```

## `perception_call`（type=`model_call`）

```json
{
  "uuid": "01a0a4a7-1340-7c25-83b8-1d843a7f69c2",
  "kind": "perception_call",
  "type": "model_call",
  "ts": 1789468808.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "perceive_after_action",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "input_tokens": "312",
    "output_tokens": "74",
    "cached_tokens": "0",
    "reasoning_tokens": "0",
    "ok": "true",
    "raw": "场景：野外草地；主角面朝上；无对话框。",
    "prompt": "（视觉 prompt：这一帧截图 + 结构化字段清单）"
  }
}
```

## `decide_call`（type=`model_call`）

```json
{
  "uuid": "01a0a4a7-1728-7233-919a-38e7af46e953",
  "kind": "decide_call",
  "type": "model_call",
  "ts": 1789468809.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "think_action",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "input_tokens": "1220",
    "output_tokens": "74",
    "cached_tokens": "0",
    "reasoning_tokens": "0",
    "ok": "true",
    "raw": "{\"thought\":\"沿路向北\",\"sequence\":[{\"name\":\"up\",\"times\":1}]}",
    "prompt": "（发给模型的完整 prompt 原文，几百到几千 token，此处截略）"
  }
}
```

## `plan_call`（type=`model_call`）

```json
{
  "uuid": "01a0a4a7-1b10-77c6-8afe-df413a6f0917",
  "kind": "plan_call",
  "type": "model_call",
  "ts": 1789468810.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "plan",
    "episode_id": "run-20260914-a",
    "step": 0
  },
  "content": {
    "input_tokens": "1220",
    "output_tokens": "74",
    "cached_tokens": "0",
    "reasoning_tokens": "0",
    "ok": "true",
    "raw": "{\"thought\":\"沿路向北\",\"sequence\":[{\"name\":\"up\",\"times\":1}]}",
    "prompt": "（发给模型的完整 prompt 原文，几百到几千 token，此处截略）"
  }
}
```

## `judge_call`（type=`model_call`）

```json
{
  "uuid": "01a0a4a7-1ef8-797e-a06e-795492f4f1a7",
  "kind": "judge_call",
  "type": "model_call",
  "ts": 1789468811.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "judge",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "input_tokens": "1220",
    "output_tokens": "74",
    "cached_tokens": "0",
    "reasoning_tokens": "0",
    "ok": "true",
    "raw": "{\"thought\":\"沿路向北\",\"sequence\":[{\"name\":\"up\",\"times\":1}]}",
    "prompt": "（发给模型的完整 prompt 原文，几百到几千 token，此处截略）",
    "why": "目标未达成：主角仍在 1 号道路，未抵达道馆"
  }
}
```

## `verify_call`（type=`model_call`）

```json
{
  "uuid": "01a0a4a7-22e0-797c-b40f-48a0126003e3",
  "kind": "verify_call",
  "type": "model_call",
  "ts": 1789468812.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "verify_and_summarize",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "input_tokens": "1220",
    "output_tokens": "74",
    "cached_tokens": "0",
    "reasoning_tokens": "0",
    "ok": "true",
    "raw": "{\"thought\":\"沿路向北\",\"sequence\":[{\"name\":\"up\",\"times\":1}]}",
    "prompt": "（发给模型的完整 prompt 原文，几百到几千 token，此处截略）",
    "verdicts": [
      {
        "index": 0,
        "reliable": true,
        "why": "按 up 后位置北移一格，一致"
      },
      {
        "index": 1,
        "reliable": false,
        "why": "记录说进屋，画面仍在野外"
      }
    ]
  }
}
```

## `summarize_call`（type=`model_call`）

```json
{
  "uuid": "01a0a4a7-26c8-7ff0-a479-b19b8e71fc95",
  "kind": "summarize_call",
  "type": "model_call",
  "ts": 1789468813.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "verify_and_summarize",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "input_tokens": "1220",
    "output_tokens": "74",
    "cached_tokens": "0",
    "reasoning_tokens": "0",
    "ok": "true",
    "raw": "{\"thought\":\"沿路向北\",\"sequence\":[{\"name\":\"up\",\"times\":1}]}",
    "prompt": "（发给模型的完整 prompt 原文，几百到几千 token，此处截略）"
  }
}
```

## `extract_call`（type=`model_call`）

```json
{
  "uuid": "01a0a4a7-2ab0-7958-823b-2e87fd715cad",
  "kind": "extract_call",
  "type": "model_call",
  "ts": 1789468814.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "extract_knowledge",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "input_tokens": "1220",
    "output_tokens": "74",
    "cached_tokens": "0",
    "reasoning_tokens": "0",
    "ok": "true",
    "raw": "{\"thought\":\"沿路向北\",\"sequence\":[{\"name\":\"up\",\"times\":1}]}",
    "prompt": "（发给模型的完整 prompt 原文，几百到几千 token，此处截略）"
  }
}
```

## `call_failed`（type=`error`）

```json
{
  "uuid": "01a0a4a7-2e98-7f6e-bae8-cbe78cdf320a",
  "kind": "call_failed",
  "type": "error",
  "ts": 1789468815.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "think_action",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "link": "decide",
    "exception": "ParseFailure",
    "reason": "Action 字段不合法：sequence.0.name: Input should be a valid string"
  }
}
```

## `call_exhausted`（type=`error`）

```json
{
  "uuid": "01a0a4a7-3280-7268-b6ed-9e32250c9ec3",
  "kind": "call_exhausted",
  "type": "error",
  "ts": 1789468816.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "judge",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "link": "judge"
  }
}
```

## `summary_parse_error`（type=`error`）

```json
{
  "uuid": "01a0a4a7-3668-7b6b-8740-633a28180fef",
  "kind": "summary_parse_error",
  "type": "error",
  "ts": 1789468817.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "verify_and_summarize",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "link": "summarize",
    "reason": "蒸馏 JSON 缺 summary 字段"
  }
}
```

## `observe`（type=`view`）

```json
{
  "uuid": "01a0a4a7-3a50-7f8f-958b-45ae9240a512",
  "kind": "observe",
  "type": "view",
  "ts": 1789468818.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "record_observation",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "status": "field · 1 号道路 · (13,8) 朝上",
    "facts": {
      "scene": null,
      "overlay": null,
      "where": "1 号道路，主角在草丛边上",
      "facing": "up",
      "neighbors": "上：可走；左：草丛；右：草丛；下：可走",
      "landmarks": [],
      "dialog_text": "",
      "options": [],
      "cursor": null,
      "overview": "小径向北延伸，两侧是高草丛，没有 NPC",
      "walk_map": "…（RAM 读出的地形网格文本）",
      "map_id": 12
    },
    "goals": [
      "沿一号道路向北走到常磐市"
    ],
    "frame": "（base64 PNG——从帧槽按 obs.step 取；跨进程槽空时此键不出现）"
  }
}
```

## `after_action`（type=`view`）

```json
{
  "uuid": "01a0a4a7-3e38-74bf-a87f-f5b7d21dfc9b",
  "kind": "after_action",
  "type": "view",
  "ts": 1789468819.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "perceive_after_action",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "place": {
      "map_id": 12,
      "x": 13,
      "y": 7
    },
    "facts": {
      "scene": null,
      "overlay": null,
      "where": "1 号道路 (13,7)",
      "facing": "up",
      "neighbors": "上：可走；下：可走",
      "landmarks": [],
      "dialog_text": "",
      "options": [],
      "cursor": null,
      "overview": "",
      "walk_map": "…（RAM 读出的地形网格文本）",
      "map_id": 12
    },
    "done": "false",
    "perceived": "false",
    "frame": "（base64 PNG——本格刚产出的那一帧；RAM 档也照截，链中间的键也有）"
  }
}
```

## `think`（type=`llm_outcome`）

```json
{
  "uuid": "01a0a4a7-4220-72b2-98ca-d71ed26b746b",
  "kind": "think",
  "type": "llm_outcome",
  "ts": 1789468820.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "think_action",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "sequence": [
      {
        "name": "up",
        "times": 1,
        "rationale": [
          "目标在北边，先试探一步"
        ]
      }
    ],
    "thought": "目标在北边，先向上走一格试试",
    "input": "（发给决策模型的 prompt 原文）",
    "output": "{\"thought\":\"沿路向北\",\"sequence\":[{\"name\":\"up\",\"times\":1}]}"
  }
}
```

## `judge_verdict`（type=`llm_outcome`）

```json
{
  "uuid": "01a0a4a7-55a8-72b8-b4ab-150018a9226d",
  "kind": "judge_verdict",
  "type": "llm_outcome",
  "ts": 1789468825.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "judge",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "done": "false",
    "success": "false",
    "stalled": "false",
    "why": "目标未达成：主角仍在 1 号道路",
    "input": "（发给判定模型的 prompt 原文）",
    "output": "{\"done\":false,\"why\":\"目标未达成\"}"
  }
}
```

## `verify_verdict`（type=`llm_outcome`）

```json
{
  "uuid": "01a0a4a7-5990-7d67-be70-f1ee641b0d54",
  "kind": "verify_verdict",
  "type": "llm_outcome",
  "ts": 1789468826.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "verify_and_summarize",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "checked": "5",
    "unreliable": "1",
    "input": "（发给校验模型的 prompt 原文）",
    "output": "{\"verdicts\":[{\"index\":0,\"reliable\":true}]}"
  }
}
```

## `plan_verdict`（type=`llm_outcome`）

```json
{
  "uuid": "01a0a4a7-5d78-7ffe-a285-ca12405a9bef",
  "kind": "plan_verdict",
  "type": "llm_outcome",
  "ts": 1789468827.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "plan",
    "episode_id": "run-20260914-a",
    "step": 0
  },
  "content": {
    "done": "false",
    "pushed_goals": [
      "先去商店买 5 个精灵球"
    ],
    "why": "当前预算不足以直接挑战道馆，先补充物资",
    "input": "（发给规划模型的 prompt 原文；无模型路径时这两个键不出现）",
    "output": "{\"done\":false,\"push_goals\":[...]}"
  }
}
```

## `do_action`（type=`act`）

```json
{
  "uuid": "01a0a4a7-4608-73a2-ace2-c30947a60848",
  "kind": "do_action",
  "type": "act",
  "ts": 1789468821.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "act",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "sequence": [
      {
        "name": "up",
        "times": 1,
        "rationale": [
          "链首段直行"
        ]
      }
    ]
  }
}
```

## `get_action_space`（type=`act`）

```json
{
  "uuid": "01a0a4a7-49f0-75e8-9e8e-287d6ced072a",
  "kind": "get_action_space",
  "type": "act",
  "ts": 1789468822.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "get_action_space",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "names": [
      "up",
      "down",
      "left",
      "right",
      "a",
      "b"
    ]
  }
}
```

## `stall_check`（type=`act`）

```json
{
  "uuid": "01a0a4a7-4dd8-7197-99f6-faa74a904a19",
  "kind": "stall_check",
  "type": "act",
  "ts": 1789468823.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "detect_stall",
    "episode_id": "run-20260914-a-ep1",
    "step": 5
  },
  "content": {
    "stall_key": "12:13:8:up",
    "stall_count": "3"
  }
}
```


## `read_step`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-6160-7797-85c4-84146b1a6993",
  "kind": "read_step",
  "type": "memory_io",
  "ts": 1789468828.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "retrieve_step_episode_memory",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "query": "episode_id=run-20260914-a-ep1",
    "refs": [
      "(run-20260914-a-ep1, 1)",
      "(run-20260914-a-ep1, 2)"
    ]
  }
}
```

## `read_global`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-6548-7934-95ef-ef258fb4482e",
  "kind": "read_global",
  "type": "memory_io",
  "ts": 1789468829.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "retrieve_global_episode_memory",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "query": "run_id=run-20260914-a",
    "refs": [
      "run-20260912-x-ep2",
      "run-20260912-x-ep3"
    ]
  }
}
```

## `read_knowledge`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-6930-76f6-b2c6-dd753e26e136",
  "kind": "read_knowledge",
  "type": "memory_io",
  "ts": 1789468830.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "retrieve_knowledge_semantic_memory",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "query": "scene:town overlay:dialog 目标：和店员对话买东西",
    "refs": [
      "2026-08-30_shop.md",
      "2026-08-30_dialog.md"
    ]
  }
}
```

## `read_object`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-6d18-7718-b51d-2ed6a5b9c3c4",
  "kind": "read_object",
  "type": "memory_io",
  "ts": 1789468831.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "retrieve_object_semantic_memory",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "query": "map_id=12 before_step=3",
    "refs": [
      "12:13:8"
    ]
  }
}
```

## `read_verify_step`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-7100-7e94-84bb-7b84e955aca5",
  "kind": "read_verify_step",
  "type": "memory_io",
  "ts": 1789468832.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "retrieve_verify_step_memory",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "query": "episode_id=run-20260914-a-ep1",
    "refs": [
      "(run-20260914-a-ep1, 0)",
      "(run-20260914-a-ep1, 1)",
      "(run-20260914-a-ep1, 2)",
      "(run-20260914-a-ep1, 3)",
      "(run-20260914-a-ep1, 4)",
      "(run-20260914-a-ep1, 5)",
      "(run-20260914-a-ep1, 6)",
      "(run-20260914-a-ep1, 7)",
      "(run-20260914-a-ep1, 8)",
      "(run-20260914-a-ep1, 9)",
      "(run-20260914-a-ep1, 10)",
      "(run-20260914-a-ep1, 11)",
      "(run-20260914-a-ep1, 12)",
      "(run-20260914-a-ep1, 13)",
      "(run-20260914-a-ep1, 14)",
      "(run-20260914-a-ep1, 15)",
      "(run-20260914-a-ep1, 16)",
      "(run-20260914-a-ep1, 17)",
      "(run-20260914-a-ep1, 18)",
      "(run-20260914-a-ep1, 19)",
      "(run-20260914-a-ep1, 20)",
      "(run-20260914-a-ep1, 21)",
      "(run-20260914-a-ep1, 22)",
      "(run-20260914-a-ep1, 23)",
      "(run-20260914-a-ep1, 24)",
      "(run-20260914-a-ep1, 25)",
      "(run-20260914-a-ep1, 26)"
    ]
  }
}
```

## `read_verify_knowledge`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-74e8-7f4f-9f05-3bf10ab789ae",
  "kind": "read_verify_knowledge",
  "type": "memory_io",
  "ts": 1789468833.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "retrieve_verify_knowledge",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "query": "二号道馆 馆主 属性",
    "refs": [
      "2026-08-30_gym2.md"
    ]
  }
}
```

## `write_step`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-78d0-75a1-afc5-f7e0f1adab0b",
  "kind": "write_step",
  "type": "memory_io",
  "ts": 1789468834.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "store_step_episode_memory",
    "episode_id": "run-20260914-a-ep1",
    "step": 3
  },
  "content": {
    "before": {
      "step": 3,
      "place": {
        "map_id": 12,
        "x": 13,
        "y": 8
      },
      "status": "field · 1 号道路 · (13,8) 朝上",
      "facts": {
        "scene": null,
        "overlay": null,
        "where": "1 号道路",
        "facing": "up",
        "neighbors": "",
        "landmarks": [],
        "dialog_text": "",
        "options": [],
        "cursor": null,
        "overview": "小径向北",
        "walk_map": "",
        "map_id": 12
      },
      "done": false,
      "perceived": true
    },
    "rationale": [
      "链首：先向北试探一步",
      "位置从 (13,8) 变为 (13,7)，无异常"
    ],
    "action": "up",
    "after": {
      "step": 3,
      "place": {
        "map_id": 12,
        "x": 13,
        "y": 7
      },
      "status": "field · 1 号道路 · (13,7) 朝上",
      "facts": {
        "scene": null,
        "overlay": null,
        "where": "1 号道路",
        "facing": "up",
        "neighbors": "",
        "landmarks": [],
        "dialog_text": "",
        "options": [],
        "cursor": null,
        "overview": "小径向北",
        "walk_map": "",
        "map_id": 12
      },
      "done": false,
      "perceived": true
    }
  }
}
```

## `write_object`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-7cb8-797f-841f-3e15323cfb69",
  "kind": "write_object",
  "type": "memory_io",
  "ts": 1789468835.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "store_object_semantic_memory",
    "episode_id": "run-20260914-a-ep1",
    "step": 4
  },
  "content": {
    "actor_place": {
      "map_id": 12,
      "x": 13,
      "y": 9
    },
    "place": {
      "map_id": 12,
      "x": 13,
      "y": 8
    },
    "object_kind": "人",
    "button": "a",
    "outcome": "dialog",
    "text": "欢迎来到宝可梦中心！要我为你的宝可梦恢复体力吗？"
  }
}
```

## `write_episode`（type=`memory_io`）

```json
{
  "uuid": "01a0a4a7-80a0-7011-8cb9-73a2eea69d76",
  "kind": "write_episode",
  "type": "memory_io",
  "ts": 1789468836.0,
  "meta": {
    "run_id": "run-20260914-a",
    "source": "verify_and_summarize",
    "episode_id": "run-20260914-a-ep1",
    "step": 26
  },
  "content": {
    "summary": "主角沿 1 号道路北上抵达常磐市，挑战道馆并在第 27 步获胜。",
    "reusable_patterns": [
      "野外遇敌率高的路段贴边走",
      "先补满血再进馆"
    ],
    "critical_decisions": [
      "第 9 步放弃抓怪直奔道馆"
    ],
    "failure_points": [
      "血量低于一半时进馆会被秒"
    ],
    "quality_score": 0.8,
    "quality_rationale": "关键决策与失败点都有具体步骤支撑",
    "applicable_scenes": [
      "道馆挑战",
      "城镇导航"
    ],
    "tags": [
      "导航",
      "战斗"
    ],
    "markdown": "## 本局经过\n（LLM 蒸馏出的完整正文……）"
  }
}
```
