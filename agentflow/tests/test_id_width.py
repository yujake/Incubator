# -*- coding: utf-8 -*-
"""编号宽度：**发号只发六位**（反真空）+ **旧四位读得进来**（读侧兼容）。

业主 2026-10-14 逐字：「**所有四位编号改成六位**（`0000`→`000000`，防溢出）……
并留一条『六位』的反真空判据 + 旧数据（四位）的读侧兼容处置」。

## 两半必须分开判（这是这一组存在的理由）

把"读得进来"与"发得出去"折成一个判据，就会得到两种坏形态里的一种：

- 只判"旧数据读得进" ⇒ 六位这件事没有任何东西看着（改回四位照样全绿）；
- 只判"新号是六位" ⇒ 历史行会在 `store.rebuild()` 里被判成坏行**静默跳过**
  （那是数据毁灭，不是迁移）。`row_from_dict` + `validate` 走的是同一个 `require_id`。

所以这一组按两半写：

1. 反真空（六位）：**每一个发号点的输出**都必须是六位 —— 逐个真发一次，
   不读任何文档/注释里的宽度；
2. 读侧兼容（四位）：四位的历史号照样通过 `require_id` / `is_valid_process_id`，
   且 `id_width()` 能把两种宽度分开报出来（迁移读数靠它）。
"""

from __future__ import annotations

import pathlib
import re

import pytest
from conftest import TS, add_literature
from agentflow import manuscripts as MS
from agentflow import schema as S
from agentflow import userio as U
from agentflow import verifications as V
from agentflow.store import MAX_ID, Store

# ---------------------------------------------------------------- 一、反真空：六位


def test_the_declared_width_is_six_and_the_ceiling_matches():
    """宽度与上限**同一处对账**（判据本身也钉一遍，免得它随别处一起漂）。"""
    assert S.ID_DIGITS == 6, f"业主裁定的宽度是六位，读到的 {S.ID_DIGITS} 位"
    assert S.ID_PATTERN == r"\d{6}", S.ID_PATTERN
    assert MAX_ID == 10 ** S.ID_DIGITS - 1 == 999999, MAX_ID
    # 反真空：这一格不是"读注释读来的" —— 形态判据真的按六位判
    assert S.is_valid_id("000001") and not S.is_valid_id("0000001")


def test_every_allocator_emits_the_current_width(tmp_path: pathlib.Path):
    """**所有发号点**的输出都必须是六位：逐个真发一次（不是读文档）。

    为什么逐个发而不能只查 `format_id`：改宽度最容易漏的形态是"某个发号点自己
    拼了 `f\"{n:04d}\"`"—— 那种点不看 `format_id`，只查一处函数是抓不到的。
    """
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "000000", title="L")
    # ① 实体表计数器（`store.alloc_id`，经事务取号）
    with st.tx("literature", actor="t", note="alloc") as tx:
        sid = tx.alloc_id("lit")
    # ② 过程记录号（`interactions.next_prefixed_id`：`cli` / `agent_c` / `webui` 都直接调它）
    from agentflow.interactions import next_prefixed_id

    rid = next_prefixed_id(st.rows("search_requests"), "request_id", "r")
    # ③ 手稿号（`manuscripts.next_id`）
    mid = MS.next_id(tmp_path / "ws")
    # ④ 工作项号（`deliver._next_work_id`）
    from agentflow.deliver import _next_work_id

    wid = _next_work_id(tmp_path / "ws", 1)
    # ⑤ 问题号（`userio._next_qid`，从事件流里取号）
    qid = U._next_qid([])

    got = {"store.alloc_id": sid, "next_prefixed_id": rid, "manuscripts.next_id": mid,
           "deliver._next_work_id": wid, "userio._next_qid": qid}
    for what, value in got.items():
        body = value.split("-", 1)[1] if "-" in value else value.lstrip("q")
        assert re.fullmatch(S.ID_PATTERN, body), (
            f"{what} 发出来的号是 {value!r} ⇒ 号身不是 {S.ID_DIGITS} 位。"
            "发号点必须走 `schema.format_id()`（宽度一处定义）")
    # 审校号那一处（`verifications`）单独真发一次
    from agentflow import verifications as V

    vroot = tmp_path / "ws2"
    vroot.mkdir()
    vid = V.next_verification_id(vroot, "000000")
    assert re.fullmatch(rf"v-{S.ID_PATTERN}", vid), vid


def test_no_four_digit_mint_remains_in_the_source():
    """反真空的第二条：源码里不许再有"自己拼四位数"的发号点。

    查的是 `f"{...:04d}"` 这种**写死的宽度**（读侧兼容的 `f"{n:04d}"` 只允许出现在
    明确标注"旧数据"的那一处 —— 目前只有 `manuscripts._mid_forms` 一处）。
    """
    root = pathlib.Path(__import__("agentflow").__file__).parent
    offenders: list[str] = []
    for p in sorted(root.rglob("*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if ":04d" not in line:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):     # 注释里引用旧写法不算发号点
                continue
            # 读侧兼容那一处（旧四位写法）自己带 LEGACY 标记，判据据此放行。
            if "LEGACY" in line:
                continue
            offenders.append(f"{p.relative_to(root)}:{i}: {stripped[:100]}")
    assert not offenders, (
        "这些地方还在自己拼四位数（宽度必须只有 `schema.format_id` 一处）：\n  - "
        + "\n  - ".join(offenders))


# ---------------------------------------------------------------- 二、读侧兼容：旧四位


def test_legacy_four_digit_ids_are_still_accepted_on_the_read_side():
    """旧四位数据**读得进来**：形态判据两种宽度都认，且能分辨是哪一种。"""
    assert S.is_valid_id("0000") and S.is_legacy_id("0000")
    assert S.is_valid_id("000000") and not S.is_legacy_id("000000")
    assert S.require_id("0000") == "0000"
    assert S.id_width("0000") == 4 and S.id_width("000000") == 6 and S.id_width("abc") == 0
    # 过程记录号同理（旧工作区盘上全是 `t-0252` 这种）
    assert S.is_valid_process_id("t-0001") and S.is_valid_process_id("t-000001")
    assert S.require_process_id("t-0001", "task") == "t-0001"


def test_a_legacy_row_in_a_real_store_is_read_not_dropped(tmp_path: pathlib.Path):
    """一条真实的历史行（四位号）必须能读、能重建，不被当成坏行静默跳过。

    这是读侧兼容的**端到端**那一半：`store.rebuild()` 逐行调
    `row_from_dict` + `validate`，任何异常都被 `except: skipped += 1` 吃掉 ——
    所以"只认六位"的后果是历史行凭空消失，且不报错。
    """
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("literature", actor="t", note="legacy") as tx:
        row = {"lit_id": "0007", "title": "旧行", "authors": [], "year": 2001,
               "type": "J", "summary": "s", "path": "", "venue": "", "doi": "", "url": "",
               "abstract": "", "pdf_path": "", "text_path": "", "has_text_layer": True,
               "pages": 3, "sha256": "0" * 64, "created_at": TS, "updated_at": TS}
        tx.upsert("literature", row, note="legacy")
    assert [r["lit_id"] for r in st.rows("literature")] == ["0007"]
    rep = st.rebuild()
    assert [r["lit_id"] for r in st.rows("literature")] == ["0007"], (
        f"四位的历史行在 rebuild 里没了（skipped={getattr(rep, 'skipped', None)}）")
    # 新号仍然只发六位（发号器不看表里有没有旧宽度的号，只发当前宽度）
    with st.tx("literature", actor="t", note="new") as tx:
        nxt = tx.alloc_id("lit")
    assert re.fullmatch(S.ID_PATTERN, nxt), nxt


def test_a_new_write_with_a_legacy_id_is_still_shape_valid_but_the_allocator_is_not(
        tmp_path: pathlib.Path):
    """写侧与发号侧的分工：手写一个四位号**仍然合法**（旧数据要能续写/迁移），
    但**发号器只发六位** —— "新号必须六位"这条判据落在发号点上，不落在形态判据上。

    为什么刻意这样分（业主裁定的两半分法）：形态判据要同时服务"读旧数据"与
    "写新数据"，把它收紧成只认六位就会把历史行判死；而"新写的号是几位"这件事
    在发号器上是可以逐个数出来的（上一条判据就是那么做的）。
    """
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "0000", title="手写的旧宽度号")
    assert [r["lit_id"] for r in st.rows("literature")] == ["0000"]
    with st.tx("literature", actor="t", note="new") as tx:
        nxt = tx.alloc_id("lit")
    assert re.fullmatch(S.ID_PATTERN, nxt), f"发号器发出了 {nxt!r}"
