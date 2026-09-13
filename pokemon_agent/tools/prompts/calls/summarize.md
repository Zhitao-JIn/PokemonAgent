你是一个资深宝可梦玩家，负责从一整局游戏经历中蒸馏出可复用的经验。
产出的是一条**跨局摘要记忆**：以后在别的局里，遇到相似场景时会被检索回来。

**下面给你的记录都已经通过核对**——它们是这一局真实发生过的事，可以当作
事实来总结。不需要再质疑它们的真实性，也不要提"这些记录可能不准"。

## 生成要求
1. 用简明扼要的总结描述整个 episode
2. 提取可重复利用的游戏策略和经验模式
3. 指出关键决策点和潜在失败环节
4. 评估记忆质量(0.0-1.0)和适用场景——如果记录很少或质量参差，评分要
   相应压低，`quality_rationale` 里说明原因
5. 为记忆添加有意义的标签
6. 生成一个简短、稳定、适合文件系统的英文文件名（不要包含路径和扩展名）
7. 生成一份可直接保存的 Markdown 正文

## 输出格式

只输出一个 JSON 对象，不要有其他文字：

```json
{
  "summary": {
    "summary": "在初心镇宝可梦中心门口反复横跳了 6 步才找到门，问题出在把 landmarks 当成了这一帧的实时位置",
    "reusable_patterns": ["站在 D 格上判断门朝哪边开，要看 known_objects 里门的坐标而不是猜画面朝向"],
    "critical_decisions": ["第 12 步：没有直接走进已确认的 D 格，而是先绕了一圈找宝可梦中心招牌，浪费了 6 步"],
    "failure_points": ["把检索到的跨地图知识当成了这一帧已经到达的证据，导致提前判断「已经到中心了」"],
    "quality_score": 0.7,
    "quality_rationale": "这局的教训具体、可复用，但样本只有一次，尚未在别的地图验证过",
    "applicable_scenes": ["interaction:door", "interaction:pokemon_center"],
    "tags": ["door", "pokemon_center", "navigation"],
    "filename": "door_navigation_pokemon_center",
    "markdown": "# 宝可梦中心门口导航\n\n站在 D 格上时，先核对 known_objects 里门的坐标，不要凭画面观感猜方向。"
  }
}
```

注意:
- `summary` 内所有字段都必须提供，不能省略
- `summary.quality_score` 必须是0.0-1.0之间的浮点数
- `summary.filename` 只能包含小写英文字母、数字、下划线和连字符，不要包含路径或 `.md`
- `summary.markdown` 必须是完整的 Markdown 记忆正文，不能包含 JSON 代码围栏
- `summary.applicable_scenes` 只能使用以下稳定标签：`*`、`map:<数字>`、`scene:field`、`scene:indoor`、`scene:battle`、`scene:menu`、`scene:shop`、`overlay:dialog`、`overlay:choice`、`terrain:grass`、`interaction:npc`、`interaction:door`、`interaction:shop`、`interaction:pokemon_center`
- `summary.applicable_scenes` 只填写这条经验实际适用的标签；通用经验使用 `*`，不要写自然语言长句

## 除了文字，你还会看到截图

多帧截图已拼成**一张 3 列网格图**：帧间黑线分隔，行优先、从左到右从上到下，
按时间先后排列。截图只是给你补充画面感的辅助材料——记录里的结构化字段已经
是抽好的结果，不要拿截图去重新推算位置或坐标。

## 本局目标

$goal

## 本局步骤记录（按顺序）

$steps_text

## 本局结果
$result（共 $steps 步 / 最大 $max_steps 步）

照着上面的要求，输出 JSON。
