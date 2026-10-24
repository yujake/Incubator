# -*- coding: utf-8 -*-
"""`lit.stage_*` 四个工具 handler 对 `litstage` 受控错的翻译（缺陷 A 的判据）。

## 现场（2026-10-24，HEAD 上可复现）

四个 handler（`_h_lit_stage_add` / `_h_lit_stage_list` / `_h_lit_stage_withdraw` /
`_h_lit_stage_reject`）的 `except` 元组里引用了 `LitStageError`，而这个名字只在
`_stage_fail` 与 `lit.admit` / `lit.admit_all` 的函数作用域里局部 import ——
四个 handler 自己那个作用域里没有它。于是底层一抛错，`except (...)`
本身先抛 `NameError`，工具层的兜底把它折成 `kind="unexpected"`：
模型读到的是一句"名字没定义"，而不是"这一笔为什么被拒"。

## 判据

真抛一次 `LitStageError`（能走真实路径的走真实路径）⇒ 工具层返回的是那条错的
`kind` 与它自己的原话，且 `NameError` 一个字都不许出现。

`lit.stage_list` 这一档把底层函数换成"抛一次真错"：它的工具层参数已经是受控
取值，真实路径上走不到 `litstage` 里那几条错。缺陷在 `except` 元组的绑定上，
与异常从哪条路来无关，所以这一档证明的是同一条判据。
"""

from __future__ import annotations

import pytest

from agentflow import litstage as L
from agentflow.store import Store
from agentflow.tools import build_for_role


@pytest.fixture
def store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


@pytest.fixture
def reg(store: Store):
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def test_the_four_lit_stage_handlers_keep_a_litstage_refusal_verbatim(reg, monkeypatch):
    """底层抛 `LitStageError` ⇒ 返回"被拒 + 原话"，不是被折成 `unexpected`。

    四档各自用真实可达的那条错：
    - `lit.stage_add`：request_id 形态不对（工具层只收非空字符串，形态由 `litstage` 判）；
    - `lit.stage_list`：底层读列表时抛（工具层参数受控，真实路径走不到）；
    - `lit.stage_withdraw` / `lit.stage_reject`：槽位不存在（理由码必须受控，所以用合法码）。

    反真空：把模块级的 `LitStageError` 绑定拿掉（改前形态）⇒ 这四条全部折成
    `kind="unexpected"`，第一条断言就红。改前的实测输出见本批报告；
    这里不再复制一份"删 import"的运行期替身，因为那会证明一个与源码不同形状的假设。
    """
    def _boom(*args, **kwargs):
        raise L.LitStageError("探针原话：待新增列表这次读不成", kind="probe_list_refused")

    monkeypatch.setattr(L, "list_candidates", _boom)

    cases = [
        ("lit.stage_add",
         {"request_id": "not-a-request-id", "entries": [{"title": "t"}]},
         "bad_delegation", "request_id"),
        ("lit.stage_list", {}, "probe_list_refused", "探针原话"),
        ("lit.stage_withdraw",
         {"slot": "000999", "reason_code": "withdrawn_by_reviewer"},
         "unknown_slot", "没有槽位"),
        ("lit.stage_reject",
         {"slot": "000999", "reason_code": "rejected_off_topic"},
         "unknown_slot", "没有槽位"),
    ]
    for name, kwargs, want_kind, want_phrase in cases:
        res = reg.call(name, **kwargs)
        assert res.ok is False, f"{name} 居然成功了：{res.to_dict()}"
        assert res.meta.get("kind") == want_kind, (name, res.meta, res.error)
        assert want_phrase in str(res.error or ""), (name, res.error)
        assert "NameError" not in str(res.error or ""), (name, res.error)
    # 明细也照原样带回来（unknown_slot 的 detail 里有 slot）
    assert reg.call("lit.stage_withdraw", slot="000999",
                    reason_code="withdrawn_by_reviewer").meta.get("slot") == "000999"
