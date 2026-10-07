"""测评代码的仓库根路径。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROM = REPO_ROOT / "assets" / "rom"
