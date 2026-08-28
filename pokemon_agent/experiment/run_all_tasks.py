"""把每个 knowledge 任务各跑 N 遍，最后打一张成功率表。

# 为什么单独一个入口，而不是让人手敲 19 条命令

`run_experiment` 一次只跑一条任务链，重复靠 `--repeat`。攒一批基线数据要
19 条命令、几个小时，中间任何一条崩掉，人回来看到的是半张表，而且不知道
剩下的是"跑了没成"还是"根本没跑"。这个脚本把"跑哪些、各跑几遍、最后怎么汇总"
固定下来，让一批数据是**一条命令的产物**，而不是一串手工操作的产物。

# 为什么每一次 run 都起一个子进程

`run_experiment` 已经保证了"每一遍是一次独立的 run"（自己的 manifest、
自己的 world）。这里再套一层进程隔离，防的是另一类东西：**SDL/PyBoy 这类
C 扩展崩起来是段错误，不是 Python 异常**——同进程里跑，一条任务把解释器带走，
后面 18 条就都没了。子进程崩掉只丢它自己那一遍，批次照跑。

代价是每次 run 多一次解释器启动（约 1–2 秒）。相对一局里几十次模型调用，
这个开销可以忽略，换来的是"一条任务的意外不会污染整批数据"。

# 汇总从哪里来

不自己记结果，读 `experiment_results/task_stats/*.json`——那是 harness 每局
落盘的那一份，**唯一真相**。这里只按 `run_id` 前缀把本批次的 run 挑出来。
自己再记一份的话，两份对不上时没人知道该信哪个。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import uuid
from datetime import datetime

from pokemon_agent.experiment.tasks import knowledge_recall_tasks


STATS_ROOT = pathlib.Path("experiment_results/task_stats")


def batch_run_ids(chain_id: str, batch_id: str, repeat: int) -> tuple[str, list[str]]:
    """本批次里这条任务会用到的 `--run-id` 前缀和它展开后的那几个 run_id。

    展开规则**抄自 `run_experiment.main`**：`--repeat` 为 1 时 run_id 原样，
    大于 1 时加 `-r{i}` 后缀。两处必须一致，否则汇总会漏掉整条任务的数据。
    调用方保证 repeat >= 1。
    """
    assert repeat >= 1, f"repeat must be >= 1, got {repeat}"

    prefix = f"{batch_id}-{chain_id}"
    if repeat == 1:
        return prefix, [prefix]
    return prefix, [f"{prefix}-r{index}" for index in range(1, repeat + 1)]


def read_outcomes(chain_id: str, run_ids: list[str]) -> list[bool]:
    """从 task_stats 里挑出这几个 run 的成败。

    读不到的 run 不算失败，**直接不计入**——它可能是子进程崩在了落盘之前。
    把"没跑成"混进"跑了没成功"，成功率就不再是成功率了。
    """
    path = STATS_ROOT / f"{chain_id}.json"
    if not path.is_file():
        return []
    stats = json.loads(path.read_text(encoding="utf-8"))
    wanted = set(run_ids)
    return [bool(run["success"]) for run in stats.get("runs", []) if run["run_id"] in wanted]


def main() -> None:
    """跑一批实验：每个任务各 N 遍，最后打表。"""
    parser = argparse.ArgumentParser(description="每个 knowledge 任务各跑 N 遍")
    parser.add_argument("--repeat", type=int, default=10, help="每个任务跑几遍")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument("--batch-id", default="", help="批次标识，进 run_id 前缀")
    parser.add_argument(
        "--only", nargs="*", default=None,
        help="只跑这几条（任务链 id，可省略 knowledge_ 前缀）；不填则全跑",
    )
    args = parser.parse_args()

    # 命令行是外部输入，走 parser.error 而不是 assert（`python -O` 会删掉 assert）。
    if args.repeat < 1:
        parser.error(f"--repeat 至少是 1，收到 {args.repeat}")

    # **只跑单任务，不跑任务链。** `knowledge_recall_tasks` 返回的里面混着
    # 多节点链（shop_purchase_flow 这类），它们和短任务测的不是一件事：
    # 链是"前一条成功了才跑下一条"，失败会在中途截断，
    # 那张表里的"成功率"既不是每条任务的成功率、也不是链的成功率。
    # 基线要的是每条短任务各自独立的成功率，所以在这里就滤掉。
    chains = [chain for chain in knowledge_recall_tasks(args.max_steps)
              if len(chain.tasks) == 1]
    if args.only:
        wanted = {name if name.startswith("knowledge_") else f"knowledge_{name}"
                  for name in args.only}
        unknown = wanted - {chain.chain_id for chain in chains}
        if unknown:
            parser.error(f"未知任务：{sorted(unknown)}")
        chains = [chain for chain in chains if chain.chain_id in wanted]

    batch_id = args.batch_id or f"{datetime.now().strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    print(f"[BATCH] {batch_id}：{len(chains)} 条任务 × {args.repeat} 遍 "
          f"= {len(chains) * args.repeat} 次 run")

    results: list[tuple[str, list[bool], int]] = []
    for index, chain in enumerate(chains, start=1):
        prefix, run_ids = batch_run_ids(chain.chain_id, batch_id, args.repeat)
        print(f"\n[BATCH] {index}/{len(chains)} {chain.chain_id}")
        completed = subprocess.run(
            [sys.executable, "-m", "pokemon_agent.experiment.run_experiment",
             "--task-id", chain.chain_id, "--repeat", str(args.repeat),
             "--max-steps", str(args.max_steps), "--run-id", prefix],
            check=False,
        )
        # **一条任务崩了不终止整批。** 这和 `run_chain` 里"异常不吞"不冲突：
        # 那里护的是一次 run 内部的数据可信度（坏环境不该继续产出数据），
        # 这里管的是批次调度——19 条任务本来就互相独立，
        # 让第 3 条的崩溃吃掉后面 16 条的数据，才是真的损失。
        # 退出码非 0 会记进表里，最后整体也以非 0 退出，不会被当成"全绿"。
        if completed.returncode != 0:
            print(f"[BATCH] {chain.chain_id} 子进程退出码 {completed.returncode}")
        results.append((chain.chain_id, read_outcomes(chain.chain_id, run_ids),
                        completed.returncode))

    print(f"\n[BATCH] {batch_id} 汇总（成功/完成的遍数，计划每条 {args.repeat} 遍）")
    for chain_id, outcomes, returncode in sorted(
        results, key=lambda row: (sum(row[1]) / len(row[1])) if row[1] else -1.0
    ):
        rate = f"{sum(outcomes) / len(outcomes):.0%}" if outcomes else "  -"
        missing = args.repeat - len(outcomes)
        note = f"  ⚠ {missing} 遍没有落盘" if missing else ""
        if returncode != 0:
            note += f"  ⚠ 退出码 {returncode}"
        print(f"  {rate:>4}  {sum(outcomes)}/{len(outcomes)}  {chain_id}{note}")

    # 有任何一条没跑满或子进程异常退出，整批就不是一份干净的基线数据——
    # 用退出码说出来，别让它在 CI 或者滚屏里被当成成功。
    dirty = [row for row in results if row[2] != 0 or len(row[1]) != args.repeat]
    if dirty:
        print(f"[BATCH] {len(dirty)} 条任务的数据不完整")
        sys.exit(1)


if __name__ == "__main__":
    main()
