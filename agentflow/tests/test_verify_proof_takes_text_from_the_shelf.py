# -*- coding: utf-8 -*-
"""判据：`verify.verify_proof` 的 `proof_text` 口径（2026-11-04 甲之后的新形态）。

## 改前是什么形态

1. 2026-10-26 之前：`required=["statement_id", "proof_text"]`，而实现的 description
   说"不给时从 statements 取" ⇒ 只给命题号被参数门拒成 `param_invalid`；
2. 2026-10-26 收口：三处改成"只给命题号即可，正文从 statements 取"—— 这条口径在
   真机上留下了 `stmt 000000` 的缺口：签是真的（sha 相符），而稿上没有签块、
   `## 依赖` 没人写、也没有按号命名的稿（载体是内联正文）。

## 2026-11-04（业主裁定 甲）之后这一条判什么

- 声明那一侧：`proof_text` 与 `proof_manuscript` 都不在根级 `required` 里
  （条件必填"有 `statement_id` 才要稿"放不进根级 required；两层 required 必须逐字相同）；
- 行为那一侧：在册命题只给命题号、不给稿 ⇒ 受控拒绝
  （`proof_text_needs_a_manuscript`），且台账里不留行 —— 不是 `param_invalid`，
  也不是"从架子上取正文就审"。拒信要指路到"落一份稿再来"；
- 反真空：正文为空的那条命题也只给命题号 ⇒ 同一句受控拒绝（载体缺了，
  正文在不在都不是这一格的主题）；
- 正控（新的合法形态）：`proof_text` 与 `proof_manuscript` 一起给、且与稿里
  `## 证明` 逐字相同 ⇒ 照常审、`proof_sha256` 与稿正文同一份 —— `proof_text`
  从此只是"对 sha 的核对"，不再是签的载体。

零模型钱：模型缝是本地替身（`_ScriptedSeam`），不起任何外部进程。
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace
from typing import Any

from agentflow import depsection as DS
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.store import Store
from agentflow.tools import build_for_role

from conftest import TS, add_literature

#: 盘上那一份证明的正文（判据要能把它与返回里的读数逐字对上）。
PROOF = "1. 由定义直接得到。2. 代入上一行即得。"
PROOF_EMPTY = ""

#: 两条夹具命题：一条带正文，一条正文为空（反真空要用）。
S_WITH_PROOF = "设 G 是有限群；则这条命题有一个可逐行走查的证明。"
S_NO_PROOF = "设 G 是有限群；则这条命题的正文还没写上来。"

#: 替身缝回的那份结论（与 `agent_v` 自检用的那一份同形）。
_VERDICT = '{"verdict": "成立", "findings": []}'


class _ScriptedSeam:
    """最小的模型缝替身：`ask()` 回同一份结论（不碰网络、不花钱）。"""

    def __init__(self, text: str = _VERDICT) -> None:
        self.text = text
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw: Any) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.text, problem="")


def _ws(tmp_path: pathlib.Path) -> Store:
    """一个工作区：一篇在册文献 + 一条带证明正文的命题 + 一条正文为空的命题。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "0000", title="夹具文献")
    with st.tx("statements", "counters", actor="fixture", note="fixture") as tx:
        for full, proof in ((S_WITH_PROOF, PROOF), (S_NO_PROOF, PROOF_EMPTY)):
            row = S.Statement(
                stmt_id=str(tx.alloc_id("stmt")), origin="external_lit",
                kind="theorem", label="夹具", statement_full=full,
                proof_text=proof, source_lit_id="0000",
                page_range=S.PageRange(start=1, end=1), quote_verified=None,
                quote_reason="夹具：这一格不参与本轮判据",
                evidence_kind="heuristic", created_at=TS,
            )
            row.validate()
            tx.upsert("statements", row.to_dict(), note="fixture")
    return st


def _ids(st: Store) -> tuple[str, str]:
    """（有正文那条, 正文空那条）的命题号 —— 按正文取，不按行序猜。"""
    rows = {str(r.get("statement_full") or ""): str(r.get("stmt_id") or "")
            for r in st.rows("statements")}
    return rows[S_WITH_PROOF], rows[S_NO_PROOF]


def _call(st: Store, stmt_id: str, **kw: Any):
    """过一次工具层的参数门再调 `verify.verify_proof`（两层口径一起量）。"""
    from agentflow import agent_v

    reg = build_for_role("V", store=st, workspace_root=str(st.root)).registry
    saved = agent_v.default_llm()
    agent_v.set_default_llm(_ScriptedSeam())
    try:
        return reg.call("verify.verify_proof", role="V", statement_id=stmt_id, **kw)
    finally:
        agent_v.set_default_llm(saved)


def _manuscript(st: Store, sid: str, body: str = PROOF) -> str:
    """落一份按号命名的手稿（空依赖表也是声明）。"""
    rel = f"reports/f-proof-{sid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 证明手稿\n\n- 命题号：stmt:{sid}\n\n"
        f"## 命题\n\n设 G 是有限群；则这条命题有一个可逐行走查的证明。\n\n"
        f"## 证明\n\n{body}\n\n" + DS.render_dependency_section([]),
        encoding="utf-8")
    return rel


def _ledger_names(st: Store, sid: str) -> list[str]:
    p = pathlib.Path(st.root) / "verifications" / f"{sid}.jsonl"
    return [p.name] if p.is_file() else []


def test_the_three_faces_of_proof_text_say_the_same_sentence(tmp_path: pathlib.Path) -> None:
    """只给命题号、不给稿 ⇒ 受控拒绝（不是 `param_invalid`，也不是从架子上取来就审）。

    改前红（2026-10-26 口径）：同一个调用会 `checked=True` 并从 statements 取正文审下去
    —— 那一签没有签块、没有 `## 依赖` 段、也没有按号命名的稿。
    """
    st = _ws(tmp_path)
    with_proof, _no_proof = _ids(st)

    # ---- 声明那一侧：工具层（真身）与能力层的 required 里都不许有这两个键
    from agentflow import capabilities as C

    spec = C.find_action("V", "verify_proof")
    assert spec is not None, "能力表里没有 V.verify_proof"
    required = tuple((spec.params or {}).get("required") or ())
    assert "proof_text" not in required, (
        "能力层的 required 里还有 proof_text ⇒ 两层根级 required 会对不上"
        "（`assert_capabilities()` 第 [9] 条在导入期就会炸）")
    assert "proof_manuscript" not in required, (
        "在册才必填的稿放不进根级 required（未在册那一档合法地不给稿）——"
        "拒绝由实现的 `_manuscript_gate` 做")

    reg = build_for_role("V", store=st, workspace_root=str(st.root)).registry
    tool_spec = reg.get("verify.verify_proof")
    tool_required = tuple((tool_spec.params or {}).get("required") or ())
    assert "proof_text" not in tool_required, (
        "工具层的 required 里还有 proof_text ⇒ 只给命题号仍会被参数门拒成 param_invalid")
    assert "proof_manuscript" not in tool_required, tool_required

    # ---- 行为那一侧：真调一次；受控拒绝 + 不落台账
    res = _call(st, with_proof)
    assert res.ok is True, (res.error, res.meta)
    data = dict(res.data or {})
    assert data.get("checked") is False, data
    assert data.get("reason") == "proof_text_needs_a_manuscript", data
    assert data.get("kind") == "proof_manuscript_required", data
    assert "按号命名的稿" in str(data.get("detail") or ""), data.get("detail")
    assert _ledger_names(st, with_proof) == [], "受控拒绝却落了台账行"


def test_an_empty_shelf_row_still_asks_for_a_manuscript(tmp_path: pathlib.Path) -> None:
    """反真空：正文为空的那条命题也只给命题号 ⇒ 同一句受控拒绝。

    这一格守的是"载体缺了就是缺了"：不会因为 statements 上恰好有/没有正文，
    就把"必须有稿"这条判据换成 `no_proof_text` 或静默放行。
    """
    st = _ws(tmp_path)
    _with_proof, no_proof = _ids(st)
    res = _call(st, no_proof)
    assert res.ok is True, (res.error, res.meta)
    data = dict(res.data or {})
    assert data.get("checked") is False, data
    assert data.get("reason") == "proof_text_needs_a_manuscript", data
    assert _ledger_names(st, no_proof) == [], "受控拒绝却落了台账行"


def test_proof_text_with_a_manuscript_is_only_a_sha_check(tmp_path: pathlib.Path) -> None:
    """正控（新的合法形态）：正文与稿一起给、逐字相同 ⇒ 照常审，sha 与稿同一份。

    改前红：改前 `proof_manuscript` 在册这一档被完全忽略 —— 正文从 statements 取，
    传不传稿对结果没有影响。现在正文以稿为准；`proof_text` 只是对 sha 的核对，
    给的是同一串字才放行。
    """
    st = _ws(tmp_path)
    with_proof, _no_proof = _ids(st)
    rel = _manuscript(st, with_proof, body=PROOF)
    res = _call(st, with_proof, proof_manuscript=rel, proof_text=PROOF)
    assert res.ok is True, (res.error, res.meta)
    data = dict(res.data or {})
    assert data.get("checked") is True, data
    assert data.get("verdict") == "成立", data
    assert data.get("proof_sha256") == VR.text_sha(PROOF), (
        data.get("proof_sha256"), VR.text_sha(PROOF))
    assert data.get("proof_chars") == len(PROOF), data.get("proof_chars")
    assert _ledger_names(st, with_proof), "审过了却没有台账行"
