"""Episode memory boundary：单步轨迹记忆与跨 episode 摘要记忆。

只留两个文件，与 `memory/semantic/` 对称：`episode_store.py`（纯存储，
`FileEpisodeMemoryStore`）+ `util.py`（frontmatter 解析等纯函数）。
蒸馏在 `Brain.verify_and_summarize()` 的合并调用里完成（组装函数也在
brain——见 ROADMAP 16），这里只管存。单步记忆是局内的、不跨 episode；
跨局摘要记忆是语义知识之外、按局积累的经验。
"""
