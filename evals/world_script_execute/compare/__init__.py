"""脚本自报与世界真值的纯比较逻辑。"""

from .checks import check_declaration, judge_declared_checks
from .core import judge_case, probe
from .verdict import ScriptVerdict

__all__ = ["ScriptVerdict", "check_declaration", "judge_declared_checks", "judge_case", "probe"]
