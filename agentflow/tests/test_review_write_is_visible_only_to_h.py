# -*- coding: utf-8 -*-
"""**H 的写入口只对 H 可见**（方案 1 的判据；业主 2026-10-17 裁定）。

## 背景（真机 `projects/t5e`）

口径 A（S2「M 只派活、不点动作」）实现成 `agent_loop._do_summon` **不读** `payload["action"]`
⇒ M 永远派不出 `action=review` ⇒ 而 H 的唯一写入口 **只在** `H.review` 这一次固定流程里
⇒ 于是 `review_findings` 恒 0，H 的发现只能写在回复/交接里。

业主裁定 **方案 1**：写能力长在角色自己身上 —— H/C 的不变量从"全只读"改成"**写面钉死**"。

本文件先钉**三件不许发生的事**（负控），再钉**一件必须发生的事**（正控）。
正控在实现落地之前应当是红的 —— 它就是驱动实现的那条判据。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow.store import Store
from agentflow.tools import build_registry


def _names_for(role: str, tmp_path: pathlib.Path) -> list[str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    reg = build_registry(store=st, workspace_root=ws).registry
    return [str(getattr(s, "name", s)) for s in reg.for_role(role)]


def test_h_can_see_its_own_write_entry(tmp_path: pathlib.Path) -> None:
    """**正控（先红后绿）**：H 的可见面里必须有 `review.review_document`。

    没有它，H 审出来的东西**没有任何落点** —— 它只能把 findings 写进回复或交接
    （真机 t5e 里就是这么发生 4 次的）。
    """
    names = _names_for("H", tmp_path)
    assert "review.review_document" in names, (
        "H 看不见自己的写入口 ⇒ 审校永远落不了台账（本判据在实现落地后应当转绿）")


@pytest.mark.parametrize("role", ["A", "B", "D", "E", "F", "G", "V", "M"])
def test_other_roles_cannot_see_hs_write_entry(role: str, tmp_path: pathlib.Path) -> None:
    """**负控**：别的角色**看不见** H 的写入口（放宽可见面 ≠ 谁都能看见）。"""
    names = _names_for(role, tmp_path)
    assert "review.review_document" not in names, f"{role} 不该看见 H 的写入口"


def test_c_cannot_borrow_hs_write_entry(tmp_path: pathlib.Path) -> None:
    """**负控**：C 也拿不到 H 的写入口（两个只读角色的写面互不借用）。"""
    names = _names_for("C", tmp_path)
    assert "review.review_document" not in names, "C 不该看见 H 的写入口"


def test_hs_visible_write_set_is_pinned(tmp_path: pathlib.Path) -> None:
    """**负控（写面钉死）**：H 能看见的**写工具**只允许是那几件，不许扩张。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    reg = build_registry(store=st, workspace_root=ws).registry
    # 与 `READONLY_CALL_EXCEPTIONS["H"]` 逐条一致（三件，都是 H 自己的落库代理）
    allowed = {"review.review_document", "review.verify_fixes", "review.report"}
    specs = {str(getattr(s, "name", s)): s for s in reg.for_role("H")}
    writes = [n for n, s in specs.items()
              if str(getattr(s, "side_effect", "")) not in ("none", "read")]
    assert set(writes) <= allowed, f"H 的可见写面出现了未登记的件：{sorted(set(writes) - allowed)}"
