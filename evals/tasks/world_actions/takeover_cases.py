"""接管脚本原 75 用例的唯一汇总表。"""

from .takeover_batch_1 import CASES as CASES_1
from .takeover_batch_2 import CASES as CASES_2
from .takeover_batch_3 import CASES as CASES_3
from .takeover_batch_4 import CASES as CASES_4
from .takeover_batch_5 import CASES as CASES_5
from .takeover_contract import Case, ScriptStatus

CASES: list[Case] = CASES_1 + CASES_2 + CASES_3 + CASES_4 + CASES_5

__all__ = ["CASES", "Case", "ScriptStatus"]
