# 跨局摘要检索 KeyError：向量缓存与磁盘摘要生命周期不一致

- 日期：2026-08-31
- 关联 commit：删 EventHub 后、事件流轮询化当天
- 系统状态：EventHub 已删（轮询 LocalTrace 单一数据源）、观测台首跑

## 一、分析（现象）

episode 以 `reason=error` 结束，`why: KeyError: 'run-20260831-172417-36d4ff-ep1'`。
**关键线索：报错的 episode_id 前缀是上一个 run（172417），不是当前 run（175235）**——
当前 run 跑到 judge 阶段检索跨局摘要经验时炸了。

## 二、定位（调查路径）

1. 先看 error 事件的 `why` 里 id 前缀：不是当前 run → **跨 run 状态泄漏**的第一信号；
2. 找按 `episode_id` 作 key 的 dict：`MemoryTool._episode_memory_vectors`（`episode_id → 向量`）；
3. 对比两个数据源的生命周期：
   - `_episode_memory_vectors`：**进程内缓存**，只在 `store_episode_summary` 写入
     （只存本 run 蒸馏过的）；
   - `FileEpisodeMemoryStore.all_episode_summaries()`：**磁盘持久**（md 文件），
     `_load_all` 启动时扫目录，**含历史所有 run** 的摘要；
4. 确认磁盘上有上一个 run 落盘的摘要（`detect_upward_platform_...md`，
   `episode_id=run-...172417-...-ep1`，`applicable_scenes` 含 `field`）——当前 run
   的 `scene="field"` 硬过滤把它捞出来，向量缓存里却没有它 → `KeyError`。

## 三、解决（改动与取舍）

- `query_episode_summaries` 改走新 helper `_episode_vector`：**缓存缺失时惰性 embed
  并缓存**；
- **取舍**：不选"启动时全量预热"（历史摘要多时每次启动白付 embed 成本）——
  向量是**派生索引**，md 才是真相（`episode_store.py` 早已这么定位），
  惰性只给"这次真被检索到"的付。

## 四、验证（测试变化）

- 新增 `tests/test_memory_tool.py`：缓存空 + 磁盘有历史摘要 → 检索惰性补算、
  不 KeyError、且文档向量只 embed 一次；
- 全套 57 测试全绿（此后扩到 63/65 未回归）。

## 方法论沉淀

**看 error 事件的 `why`，先看 id/字段的前缀是不是当前 run——是别的 run 就是跨
run 状态泄漏。** 判断标准：一个缓存（进程内）和一个存储（磁盘持久）喂同一个
查询，生命周期不一致必炸；修法是让"派生数据"（向量/索引）跟随"真相"（存储）惰性重建。
