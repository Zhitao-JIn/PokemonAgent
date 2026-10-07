"""常规脚本的独立期望汇总；分组保留原始用例与依据。"""

from .regular_batch_1 import CASES_1
from .regular_batch_2 import CASES_2
from .regular_batch_3 import CASES_3

CASES = CASES_1 + CASES_2 + CASES_3
CASES_BY_ID = {case.case_id: case for case in CASES}
