# -*- coding: utf-8 -*-
"""`agentflow repair` 的实现真身（移植期工具，从 `cli.py` 原样搬来）。

它唯一的用途是重算派生列 `related_concepts`，而并表之后那一列已随老表退役
（读侧由 `relations` 现算）—— 于是这条命令今天基本只会走进"受控退出 + 指路"那一支。
留着它是为了不打断已经在脚本里调它的东西；下一版连同本目录一起删。

`main(args)` 的入参就是 argparse 出来的那个 namespace（读 `root` 与 `related`）。
"""
from __future__ import annotations

import sys


def main(args) -> int:
    """按 verify 的派生规则修复 related_concepts（唯一允许的"自动修复"，因为它完全可派生）。

    `--related` 原先是一个被忽略的开关：函数体从不读 `args.related`，
    于是"不带参数跑一次"也会照样重写 concepts 表。一个声明了却不起作用的选项
    比没有更危险 —— 调用方以为自己在做只读检查，实际上知识表已经被改了。
    这里 fail-closed：没有显式指名要重算什么，就一行都不写并以退出码 2 说明。
    """
    from agentflow import conceptrows as CR
    from agentflow import dedup as D
    from agentflow import schema as S
    from agentflow.cli import make_store

    if not args.related:
        print(
            "[repair] 需要显式指定重算目标。本命令会写 concepts 表，因此不接受"
            "'不带参数就默认全做'：请用 `repair --related`（重算 related_concepts）。",
            file=sys.stderr,
        )
        return 2

    st = make_store(args.root)
    # 并表落刀之后这一格随老表退役：`related_concepts` 是老表专有的一列，
    # 新标准里"哪些概念相关"由 `relations` 表本身回答（读侧用同一个
    # `derive_related_concepts` 现算）⇒ 没有可重算的落点。这里受控退出 + 指路，
    # 而不是让 `tx("concepts")` 抛一句"未知表"（读的人拿到那句话不知道下一步做什么）。
    if not CR.legacy_present(st).get("present"):
        print(
            "[repair] `--related` 随并表退役（S1r）：`related_concepts` 是老表专有的一列，"
            "新标准里那件事由 `relations` 表管，读侧现算，没有可重算的落点。"
            "处置：要核对图与关系的偏离，用 `agentflow verify`（`related_drift` 那一档）；"
            "要重放老库，用 `agentflow rebuild`（它会折叠并逐条落 `out/migrate-map.jsonl`）。",
            file=sys.stderr,
        )
        return 2
    with st.tx(*CR.tables_for_concept_write("relations"), actor="repair", note="related") as tx:
        rels = tx.rows("relations")
        changed = 0
        for c in CR.view_tx(tx, shape="legacy")["rows"]:
            want = D.derive_related_concepts(c["concept_id"], rels, include_suspect=True)
            if c.get("related_concepts") != want:
                c["related_concepts"] = want
                c["updated_at"] = S.now_iso()
                # 一处调用办两件事（老表那份 + 新标准那份，同号）—— 见 `conceptrows`
                CR.upsert_legacy_shaped(tx, c, actor="repair", note="related_recomputed")
                changed += 1
    print(f"[repair] related_concepts 重算了 {changed} 行")
    return 0
