# -*- coding: utf-8 -*-
"""判据 ⑥：`duplicate` 那一档的拒信只许指出这条动作上真有的做法。

## 改前是什么形态（拒信指了一个不存在的参数）

同一条命题再交一次 ⇒ 秘书查重 ⇒ "重复读数，不新建行"，而拒信里写着
「确实要另起一条，请给 force_new」。可是走到那一格的每一条路都没有 `force_new`：

- B 的动作 `register_statement` 的参数表里没有它（`specs/b.py` 的 `ACTIONS`）；
- 被通用写口转交过来的 `table.create` 只有 `table` / `row` 两格。

于是模型照拒信去给 `force_new` ⇒ 撞 `invalid_params`（`additionalProperties=false`）——
"拒信把模型指回正路"这条要求在这里正好反了过来：它把人指进另一堵墙。

## 判据

1. 拒信里不出现 `force_new`，而它指的那两个做法（`proofs` / `statement_full`）
   真的在这条动作的声明面上；
2. 反真空：拒信仍然点名既有那一行的号（`stmt_id`）—— 它不是"删了一句话"，
   而是换成这条路上真能做的事（引用既有那行 / 交第 N 份证明 / 正文写不同）。

零模型钱：整条路径不调模型。
"""
from __future__ import annotations

import pathlib

from agentflow import capabilities as C
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.agent_b import AgentB
from agentflow.store import Store

from conftest import add_literature

#: 一条自产命题（形状照 `tests/test_v_verdict_reaches_f.py` 那一份：`doc_id` 与
#: `quote_reason` 是写库前的硬要求）。
FULL = "探针：若 n>=3 则 n^2+n 是偶数。"
PROOF = "1. n^2+n = n(n+1)。\n2. 相邻整数必有一偶，故积为偶。"

#: 外部文献那条路（秘书直收）用的载荷。
PAYLOAD: dict = {
    "origin": "external_lit", "kind": "theorem", "label": "Theorem 1.5",
    "statement_text": "随机游走的距离有 CLT 型极限",
    "statement_full": "设 G 是有限连通图；则 (d(X_0,X_n)-E d)/sqrt(n) 依分布收敛到正态",
    "proof_text": "Proof. By Theorem 6.5 of the companion book ...",
    "source_lit_id": S.format_id(0), "page_range": {"start": 7, "end": 7},
    "quote_verified": True, "quote_reason": "逐字比对通过（page 7）",
    "evidence_kind": "proof",
}


def _own(**kw) -> dict:
    """`B.register_statement` 的一份自产命题载荷。

    `kind="conjecture"`：自产且没有外部出处的那一笔必须先以猜想起步
    （`must_start_as_conjecture` 是这条路上的另一道预检，与本判据无关 ——
    本判据要的是"同一份正文交第二次"这件事）。
    """
    base = {"statement_full": FULL, "origin": "own_result", "doc_id": "000000",
            "kind": "conjecture",
            "proof_text": PROOF, "quote_verified": False,
            "quote_reason": "自产命题：没有第二份文本可比对"}
    base.update(kw)
    return base


def _props_of_the_action() -> set[str]:
    """`B.register_statement` 动作面声明的全部参数名（"真有的做法"的判据面）。"""
    spec = C.find_action("B", "register_statement")
    assert spec is not None
    return set((spec.params or {}).get("properties") or {})


def test_the_duplicate_refusal_points_at_what_the_action_really_has(
        tmp_path: pathlib.Path) -> None:
    """⑥ 同一条命题交两次 ⇒ 拒信里没有 `force_new`，指的每个参数都真在这条动作上。

    改前红：拒信逐字含"确实要另起一条才走 `force_new`（本动作不暴露它）"。
    """
    st = Store(tmp_path / "ws")
    st.init()
    b = AgentB(st, extractor=None, extract_text=None, config={})

    first = b.register_statement(**_own())
    assert first.get("ok") is True, first
    again = b.register_statement(**_own())
    assert again.get("ok") is False, again
    assert str(again.get("kind")) == "duplicate_statement", again

    text = str(again.get("error") or again.get("reason") or "")
    assert text, again

    props = _props_of_the_action()
    assert "force_new" not in props, (
        "前提变了：`B.register_statement` 现在真有 force_new 这个参数 ⇒ "
        "这条判据要连同规格一起重判（它今天断言的是'拒信不许指一个不存在的参数'）")
    assert "force_new" not in text, (
        "拒信又在指一个这条动作没有的参数了：", text)
    for named in ("proofs", "statement_full"):
        assert named in props, f"{named} 不在动作声明面上 ⇒ 判据的前提要重写"
        assert named in text, f"拒信没有说出这条路上真有的做法 {named}：{text}"

    # 反真空：它仍然点名既有那一行的号（不是"把指路那句删掉"了事）
    assert str(again.get("stmt_id") or ""), again
    assert "stmt_id" in text, text


def test_the_secretary_duplicate_reading_does_not_name_force_new(
        tmp_path: pathlib.Path) -> None:
    """⑥ 秘书那一层的重复读数同样不指 `force_new`（模型读到的就是这两条之一）。

    改前红：`Secretary.record_statement` 的重复读数逐字含"请给 force_new"。
    """
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, S.format_id(0))
    sec = SEC.Secretary("B", root=st.root, store=st)

    first = sec.record_statement(dict(PAYLOAD), role="B")
    assert first.get("created") is True, first
    dup = sec.record_statement(dict(PAYLOAD), role="B")
    assert dup.get("duplicate") is True, dup
    reason = str(dup.get("reason") or "")
    assert reason, dup
    assert "force_new" not in reason, reason
    # 指出的两件真事：既有那行的号 + 差异要写进 statement_full
    assert str(dup.get("stmt_id") or ""), dup
    assert "statement_full" in reason, reason
