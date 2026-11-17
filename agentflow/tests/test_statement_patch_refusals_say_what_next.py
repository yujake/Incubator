# -*- coding: utf-8 -*-
"""命题的非正文 patch 被拒时，拒信要给一条真的走得通的下一步。

业主 2026-11-02 的硬要求：每条建议都要能回答「照着它做，真的能走通吗」。
这一份对 `Secretary.amend_statement_meta` 的四档受控拒绝逐条做两件事：
① 断言拒信里有 `建议：` 与它点名的真工具/字段；② 真的照那句做一步，断言它到达下一步。

走的是生产路径：`table.update(table="statements", …)` → 兜底路由 → 秘书。
零模型调用；tmp 工作区。
"""
from __future__ import annotations

import pytest

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from conftest import ensure_basis_lit, ensure_basis_stmt

from agentflow import schema as S                 # noqa: E402
from agentflow.agent_b import AgentB               # noqa: E402
from agentflow.conductor import calling_as          # noqa: E402
from agentflow.store import Store                   # noqa: E402
from agentflow.tools import build_registry          # noqa: E402

FULL = "设 G 是 3-正则群；则弦长函数不是常值（patch 判据）。"
TEXT = "弦长函数不是常值（patch 判据）"
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"


def _ws(path: pathlib.Path):
    root = path / "ws"
    st = Store(root)
    st.init()
    reg = build_registry(store=st, workspace_root=root).registry
    b = AgentB(st, extractor=None, extract_text=None, config={})
    got = b.register_statement(statement_full=FULL, statement_text=TEXT,
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
                               origin="own_result", source_lit_id=ensure_basis_lit(st), kind="conjecture",
                               doc_id=S.format_id(0),
                               quote_reason="我方自产命题，没有外部引文要比对",
                               proof_text=P1)
    assert got.get("ok") is True, got
    return root, reg, str(got["stmt_id"])


def _call(reg, tool: str = "table.update", **params):
    with calling_as("t-probe", "B"):
        return reg.call(tool, role="B", **params)


def _advice(res) -> str:
    text = str(getattr(res, "error", "") or "")
    assert "建议：" in text, f"拒信没有「建议：」：{text}"
    tail = text.split("建议：", 1)[1].strip()
    assert tail, f"「建议：」后面是空的：{text}"
    return tail


# ---------------------------------------------------------------- status

def test_bad_status_says_use_the_vocabulary_and_a_valid_status_works(
        tmp_path: pathlib.Path) -> None:
    root, reg, sid = _ws(tmp_path)
    bad = _call(reg, table="statements", id=sid, patch={"status": "不存在的状态"})
    assert bad.ok is False and bad.meta.get("kind") == "bad_statement_status", bad.to_dict()
    assert "词表" in _advice(bad), bad.error

    good = _call(reg, table="statements", id=sid, patch={"status": "disputed"})
    assert good.ok is True, good.to_dict()


# ---------------------------------------------------------------- kind

def test_bad_kind_says_go_through_evidence_and_a_valid_kind_works(
        tmp_path: pathlib.Path) -> None:
    root, reg, sid = _ws(tmp_path)
    bad = _call(reg, table="statements", id=sid, patch={"kind": "定理"})
    assert bad.ok is False and bad.meta.get("kind") == "bad_statement_kind", bad.to_dict()
    advice = _advice(bad)
    assert "register_statement" in advice and "kind_following_grade" in advice, advice

    good = _call(reg, table="statements", id=sid, patch={"kind": "lemma"})
    assert good.ok is True, good.to_dict()


# ---------------------------------------------------------------- quote_reason

def test_empty_quote_reason_says_write_the_reason_and_a_real_one_works(
        tmp_path: pathlib.Path) -> None:
    root, reg, sid = _ws(tmp_path)
    bad = _call(reg, table="statements", id=sid, patch={"quote_reason": ""})
    assert bad.ok is False and bad.meta.get("kind") == "bad_quote_reason", bad.to_dict()
    assert "写清" in _advice(bad), bad.error

    good = _call(reg, table="statements", id=sid,
                 patch={"quote_reason": "还没查：这一条没有可比的全文"})
    assert good.ok is True, good.to_dict()


# ---------------------------------------------------------------- not_found（留给 FC-27 那批）

#: 不在这一份里钉：镜像号由 `tools/table_tools.py:1148` 先拒（`statements 里没有主键 …`），
#: 而那条建议要改的是 table_tools.py（FC-27 auth-audit，按主控口径排到 83 之后）。
#: 秘书那一侧的 `not_found` 是直调内部守卫，模型看不到，按「宁可少一句」不动它。


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")
