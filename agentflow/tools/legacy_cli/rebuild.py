# -*- coding: utf-8 -*-
"""`agentflow rebuild` 的实现真身（移植期工具，从 `cli.py` 原样搬来）。

它是"数据出事时的逃生门"：`events.jsonl` 是唯一的事实来源，其余表都是快照；
重建就是从事件流重放一遍。为什么它算移植期工具：正常使用不该需要它，
而留在 CLI 里会让"随手 rebuild 一下"变成一种看起来无害的操作（它会覆盖快照）。

`main(args)` 的入参就是 argparse 出来的那个 namespace（读 `root` 与 `no_backup`），
与搬走前 `cli.cmd_rebuild` 读的是同样的两格 —— 这是"逐字节不变"的前提。
"""
from __future__ import annotations


def main(args) -> int:
    """重放 `events.jsonl` 重建全部快照（退出码：0 建成 / 1 没有事件流）。"""
    from agentflow.cli import make_store

    st = make_store(args.root)
    if not st.events_path.exists():
        print("[rebuild] 没有 events.jsonl，无法重建")
        return 1
    out = st.rebuild(backup=not args.no_backup)
    print(f"[rebuild] 已从事件日志重建：应用 {out['applied']} 条，跳过 {out['skipped']} 条")
    # ---- R-06 的可见面（`46-01 §2.2(b)` STEP-3 逐字："明细没有人看得见就等于没做"）
    #
    # `skipped` 那个整数一直有，但没有人知道跳过了什么：重建完照样打印
    # "已重建：应用 N 条"，而"N 条为什么没进去"一个字都不说 —— 读的人据此
    # 以为重建是完整的（`verify` 的 `rebuild` 相关读数也只看得到那个整数）。
    # 所以这里把 `store.rebuild` 新增的两键（`skipped_by_reason` / `skipped_details`）
    # 打出来。三态纪律：非空才打印 —— 干净的重建不许多出噪音，
    # 否则"有跳过"这件事会在满屏输出里贬值。
    by_reason = dict(out.get("skipped_by_reason") or {})
    if by_reason:
        detail = "、".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
        print(f"[rebuild] 跳过的分类计数：{detail}")
        for row in list(out.get("skipped_details") or [])[:5]:
            print(f"[rebuild]   跳过明细：{row}")
        if len(list(out.get("skipped_details") or [])) > 5:
            print(f"[rebuild]   （另有 {len(list(out.get('skipped_details') or [])) - 5} 条明细未打印）")
    print(f"[rebuild] counters = {out['counters']}")
    return 0
