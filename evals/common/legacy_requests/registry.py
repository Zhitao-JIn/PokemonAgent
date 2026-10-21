"""按冻结方法精确选择旧请求，不从缺失字段猜新契约。"""

from .decompose import FromHarnessToBrainToolDecomposeReq
from .judge import FromHarnessToBrainToolJudgeReq
from .plan import FromHarnessToBrainToolPlanOnceReq
from .summarize import FromHarnessToBrainToolSummarizeReq
from .summarize_task import FromHarnessToBrainToolSummarizeTaskReq

REQUESTS = {
    "summarize": FromHarnessToBrainToolSummarizeReq,
    "plan": FromHarnessToBrainToolPlanOnceReq,
    "decompose": FromHarnessToBrainToolDecomposeReq,
    "judge": FromHarnessToBrainToolJudgeReq,
    "summarize_task": FromHarnessToBrainToolSummarizeTaskReq,
}
