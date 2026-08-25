"""episode 的全局索引：保证 `episode_id` 唯一，并清掉跑了一半的局。

**id 撞车是静默的坏。** 两次实验用了同一个 id，事件会混进同一条流里，
而离线统计只会看到一局步数异常多的 episode，不会报错。所以注册在跑之前做。

"跑了一半"的判据是**有没有终止事件**（`EPISODE_END`），不是文件大小或时间戳——
`run()` 保证异常路径也补这条事件，所以缺了它就是真的没跑完（进程被杀）。
这类 episode 留在数据里会污染成功率的分母，清掉。
"""

# pokemon_agent/trace/index.py

import json
from pathlib import Path
from typing import Dict, List, Any

# 正确获取项目根目录（通过 __file__ 回溯）
project_root = Path(__file__).parent.parent.parent
STORAGE_ROOT = project_root / "trace_data"


class EpisodeIndex:
    @classmethod
    def _get_storage_root(cls) -> Path:
        """获取 trace_data 目录并确保它存在

        取 trace 数据目录，不存在就建。
        """
        storage = STORAGE_ROOT
        storage.mkdir(exist_ok=True)
        return storage

    @classmethod
    def _get_index_path(cls) -> Path:
        """获取全局索引路径

        取全局索引文件的路径。
        """
        return cls._get_storage_root() / "episodes_index.json"

    @classmethod
    def load(cls) -> Dict[str, str]:
        """加载全局索引

        读回全局索引。
        """
        index_path = cls._get_index_path()
        if not index_path.exists():
            return {}
        try:
            return json.loads(index_path.read_text())
        except Exception:
            return {}

    @classmethod
    def save(cls, index: Dict[str, str]) -> None:
        """保存索引

        把索引写回磁盘。
        """
        index_path = cls._get_index_path()
        index_path.write_text(json.dumps(index, indent=2))

    @classmethod
    def is_unique(cls, episode_id: str, run_id: str) -> bool:
        """验证episode_id是否全局唯一

        看这个 episode_id 有没有被用过。
        """
        index = cls.load()

        # 1. 完全不存在 - 允許
        if episode_id not in index:
            return True

        # 2. 存在但屬於同run_id + 不完整 - 允許覆盖
        if index.get(episode_id) == run_id:
            return not cls._is_episode_complete(episode_id)

        # 3. 存在且屬於其他run_id - 厳格禁止
        return False

    @classmethod
    def _is_episode_complete(cls, episode_id: str) -> bool:
        """验证是否包含终止事件

        看这一局有没有终止事件。
        """
        # 檢查是否有EPISODE_END事件
        for event in cls._read_events(episode_id):
            if event.get("type") == "EPISODE_END":
                return True
        return False

    @classmethod
    def _read_events(cls, episode_id: str) -> List[Dict[str, Any]]:
        """安全读取事件

        读一局的事件，读不了就当空的。
        """
        events = []
        index = cls.load()

        for r_id in set(index.values()):
            episode_path = cls._get_storage_root() / r_id / "episodes" / f"{episode_id}.jsonl"
            if episode_path.exists():
                with episode_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            events.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            pass
        return events

    @classmethod
    def register(cls, episode_id: str, run_id: str) -> None:
        """注册新的episode_id

        把新的 episode_id 记进索引。
        """
        index = cls.load()
        index[episode_id] = run_id
        cls.save(index)

    @classmethod
    def clean_incomplete_episodes(cls, run_id: str) -> None:
        """清理不完整的episode

        删掉没有终止事件的那些局。
        """
        index = cls.load()
        incomplete = {
            ep_id: r_id
            for ep_id, r_id in index.items()
            if r_id == run_id and not cls._is_episode_complete(ep_id)
        }

        for ep_id in incomplete:
            del index[ep_id]
        cls.save(index)

        # 清理磁盘
        for ep_id in incomplete:
            path = cls._get_storage_root() / run_id / "episodes" / f"{ep_id}.jsonl"
            if path.exists():
                try:
                    path.unlink()
                    print(f"🧹 清理不完整episode: {ep_id}")
                except Exception as e:
                    print(f"⚠️ 清理失败: {ep_id} - {e}")