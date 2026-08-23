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
        """获取 trace_data 目录并确保它存在"""
        storage = STORAGE_ROOT
        storage.mkdir(exist_ok=True)
        return storage

    @classmethod
    def _get_index_path(cls) -> Path:
        """获取全局索引路径"""
        return cls._get_storage_root() / "episodes_index.json"

    @classmethod
    def load(cls) -> Dict[str, str]:
        """加载全局索引"""
        index_path = cls._get_index_path()
        if not index_path.exists():
            return {}
        try:
            return json.loads(index_path.read_text())
        except Exception:
            return {}

    @classmethod
    def save(cls, index: Dict[str, str]) -> None:
        """保存索引"""
        index_path = cls._get_index_path()
        index_path.write_text(json.dumps(index, indent=2))

    @classmethod
    def is_unique(cls, episode_id: str, run_id: str) -> bool:
        """验证episode_id是否全局唯一"""
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
        """验证是否包含终止事件"""
        # 檢查是否有EPISODE_END事件
        for event in cls._read_events(episode_id):
            if event.get("type") == "EPISODE_END":
                return True
        return False

    @classmethod
    def _read_events(cls, episode_id: str) -> List[Dict[str, Any]]:
        """安全读取事件"""
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
        """注册新的episode_id"""
        index = cls.load()
        index[episode_id] = run_id
        cls.save(index)

    @classmethod
    def clean_incomplete_episodes(cls, run_id: str) -> None:
        """清理不完整的episode"""
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