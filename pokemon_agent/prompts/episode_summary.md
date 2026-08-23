# 情景记忆生成指令

你是一个资深宝可梦玩家，负责从游戏经历中提取有价值的情景记忆。请基于以下信息生成结构化的情景记忆：

## 游戏目标
{{ goal }}

## 任务结果
{{ "成功完成" if success else "未能完成" }} (共 {{ steps }} 步 / 最大 {{ max_steps }} 步)

## 游戏过程摘要
初始状态: {{ initial_state }}
最终状态: {{ final_state }}

## 关键决策路径
{{ steps_text }}

## 生成要求
1. 用简明扼要的总结描述整个episode
2. 提取可重复利用的游戏策略和经验模式
3. 指出关键决策点和潜在失败环节
4. 评估记忆质量(0.0-1.0)和适用场景
5. 为记忆添加有意义的标签

## 输出格式要求
请严格按照以下JSON格式输出，不要添加额外内容：

{
  "summary": "str",
  "reusable_patterns": ["str"],
  "critical_decisions": ["str"],
  "failure_points": ["str"],
  "quality": {
    "score": "float",
    "level": "EXCELLENT | GOOD | FAIR | POOR | UNRELIABLE",
    "rationale": "str"
  },
  "applicable_scenes": ["str"],
  "tags": ["str"]
}

注意:
- quality.score必须是0.0-1.0之间的浮点数
- quality.level必须是枚举值之一
- 所有字段必须提供，不能省略