# -*- coding: utf-8 -*-
"""判据：`table.update(table="statements")` 只改非正文三格时，走一条真写口。

## 现场（真机 82，2026-11-01 · A-1…A-4）

B 四次用 `table.update` 想改 `kind` / `status` / `quote_reason`，四次都被
`routed_to_backstop.secretary_refused` 拒，理由逐字是"同一条 statement_full 已在册"。
机制：兜底把"盘上那一行 + patch"整份再交给秘书登记，而秘书的查重判据正是
"同一条 statement_full 已在册" ⇒ 非正文 patch 100% 落 duplicate 拒。
这一趟的三格（`kind` / `status` / `quote_reason`）于是没有任何写入口。

## 修法（选乙）

在兜底处认出"这只是改非正文格" ⇒ 转给秘书的新写口
`Secretary.amend_statement_meta`（白名单三格、整行重建后过 `Statement.validate`、
在 `store.tx` 里写、留 `_statement_amend_history` 痕迹）。选乙不选甲（新加一条 B 动作）：
甲会改动作面 / 权限面，乙只改路由与一条受控写口，最小且可回退。

## 这一份钉的七条（改前红）

| 条 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 改 `status` ⇒ 办成、不新建行、盘上那一行真的变了 | 改前落 duplicate 拒 |
| b | 改 `kind` ⇒ 办成（`conjecture` → `lemma`） | 同上 |
| c | 改 `quote_reason` ⇒ 办成 | 同上 |
| d | 白名单外的键（`label`）⇒ 受控拒绝、有码、盘上一个字节没动 | 改前落"重复读数"（码不对） |
| e | 中文 `kind` ⇒ 受控拒绝并列出英文词表 | 改前落"重复读数"（答非所问） |
| f | 带正文（`proof_text`）⇒ 仍走登记路，不走新写口 | 这一条是反真空：放宽不许变成任意改正文 |
| g | 改成功那一笔留下秘书的审计痕迹 `_statement_amend_history` | 改前根本没有这一格 |

边界：全部 tmp 工作区、零真实模型调用（秘书不带缝）；不读写 `projects/`。
"""
from __future__ import annotations

import pytest

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import conductor as COND
from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.store import Store
from agentflow.tools import table_tools
from agentflow.tools.base import ToolRegistry

FULL = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
PROOF = ("证明：对 |G| 作归纳。取阶最大的 p-幂子群 P，用共轭作用数轨道，"
         "得 P 的共轭类大小与 p 互素，故 Sylow p-子群存在。")
OWNER_TASK = S.format_id(0)


def _body() -> dict:
    return {"statement_full": FULL, "statement_text": FULL[:24],
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0),
            "quote_reason": "我方自产命题，没有外部引文要比对"}


def _ws(tmp_path: pathlib.Path) -> tuple[Store, ToolRegistry, str]:
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    b = AgentB(st, extractor=None, extract_text=None, config={})
    got = b.register_statement(**_body(), proof_text=PROOF, evidence_kind="heuristic")
    assert got.get("ok") is True, got
    sid = str(got["stmt_id"])
    reg = ToolRegistry(name="tables")
    reg.bound_role = "A"
    table_tools.register(reg, store=st)
    return st, reg, sid


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id") or "") == sid)


def _update(reg: ToolRegistry, sid: str, patch: dict):
    with COND.calling_as(OWNER_TASK, "B"):
        return reg.call("table.update", table="statements", id=sid, patch=patch)


# ============================================ a/b/c：三格各改一次


def test_status_can_be_amended_in_place(tmp_path):
    """a：改 `status=superseded` ⇒ 办成、不新建、盘上真的变了。"""
    st, reg, sid = _ws(tmp_path)
    res = _update(reg, sid, {"status": "superseded"})
    assert res.ok is True, (res.error, res.meta)
    assert "非正文" in str((res.data or {}).get("what_happened") or ""), res.data
    assert _row(st, sid).get("status") == "superseded", _row(st, sid)
    assert len(st.rows("statements")) == 1


def test_kind_can_be_amended_in_place(tmp_path):
    """b：`conjecture` → `lemma` ⇒ 办成（这是 A-1 想改的那一格）。"""
    st, reg, sid = _ws(tmp_path)
    res = _update(reg, sid, {"kind": "lemma"})
    assert res.ok is True, (res.error, res.meta)
    assert _row(st, sid).get("kind") == "lemma", _row(st, sid)
    assert len(st.rows("statements")) == 1


def test_quote_reason_can_be_amended_in_place(tmp_path):
    """c：改 `quote_reason` ⇒ 办成（这是 A-4 想写的那一格）。"""
    st, reg, sid = _ws(tmp_path)
    res = _update(reg, sid, {"quote_reason": "复核过：V 的签盖住的是旧版正文，所以没升档"})
    assert res.ok is True, (res.error, res.meta)
    assert "旧版正文" in str(_row(st, sid).get("quote_reason") or ""), _row(st, sid)
    assert len(st.rows("statements")) == 1


# ============================================ d/e：白名单与词表


def test_a_key_outside_the_whitelist_is_refused_with_a_code(tmp_path):
    """d：`label` 不在三格里 ⇒ 受控拒绝（有码），盘上一个字节没动。"""
    st, reg, sid = _ws(tmp_path)
    before = _row(st, sid)
    res = _update(reg, sid, {"label": "换个名字"})
    assert res.ok is False, res
    assert str((res.meta or {}).get("kind") or "") == "statement_patch_key_not_allowed", res.meta
    assert "status" in str(res.error or "") and "quote_reason" in str(res.error or ""), res.error
    assert _row(st, sid) == before, "被拒的那一笔改动了盘上的行"


def test_a_chinese_kind_is_refused_with_the_english_vocabulary(tmp_path):
    """e：`kind="引理"` ⇒ 受控拒绝并列出英文词表（不是"重复读数"）。"""
    _st, reg, sid = _ws(tmp_path)
    res = _update(reg, sid, {"kind": "引理"})
    assert res.ok is False, res
    assert str((res.meta or {}).get("kind") or "") == "bad_statement_kind", res.meta
    assert "lemma" in str(res.error or "") and "英文" in str(res.error or ""), res.error


# ============================================ f：带正文仍走登记路


def test_a_body_patch_still_goes_down_the_registration_path(tmp_path):
    """f：带 `proof_text` 的 patch 不走新写口（反真空：放宽不许变成任意改正文）。

    这一条不钉"它撞什么码"（登记路上撞 duplicate / 覆盖 canonical 都可能是正确读数），
    只钉两件事：它不是"非正文就地改"，以及三格没有被顺手改掉。
    """
    st, reg, sid = _ws(tmp_path)
    before = _row(st, sid)
    res = _update(reg, sid, {"proof_text": PROOF + "另补一句。"})
    assert "非正文" not in str((res.data or {}).get("what_happened") or ""), res.data
    after = _row(st, sid)
    assert after.get("status") == before.get("status"), after
    assert after.get("kind") == before.get("kind"), after
    assert after.get("quote_reason") == before.get("quote_reason"), after


# ============================================ g：秘书的审计痕迹


def test_the_amend_leaves_the_secretary_audit_trail(tmp_path):
    """g：改成功那一笔留下 `_statement_amend_history`（谁、何时、从什么改成什么）。"""
    st, reg, sid = _ws(tmp_path)
    res = _update(reg, sid, {"status": "superseded"})
    assert res.ok is True, (res.error, res.meta)
    row = _row(st, sid)
    history = list(row.get("_statement_amend_history") or [])
    assert history, row
    last = dict(history[-1])
    assert "status" in dict(last.get("changes") or {}), last
    assert dict(last["changes"]["status"]).get("to") == "superseded", last
    assert str(last.get("by") or "").startswith("secretary-"), last


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")
