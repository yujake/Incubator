# -*- coding: utf-8 -*-
"""判据 ①：`verify.verify_proof` 的 `proof_text` 三处口径必须是同一句话。

## 改前是什么形态（三处互相矛盾，模型照描述做就撞墙）

1. 声明：`tools/verify_tools.py` 的 `required=["statement_id", "proof_text"]`；
2. 描述：同一个 property 的 `description` 写着"不给时从 statements 取"；
3. 实现：`agent_v.AgentV.verify_proof` 在参数为空时真的从 statements 那一行取
   （`verifications.proof_text_of(命中行, proof_no)`）。

于是"只给命题号"这条合法调用被工具层参数门拒成 `param_invalid`
（真机 15 条 `param_invalid` 里 7 条死在这里），而它在实现里本来是通的。

## 这一条判什么

- 声明那一侧：工具 schema 与能力层动作声明的 `required` 里都没有 `proof_text`
  （两层根级 `required` 必须逐字相同，`capabilities.assert_capabilities()` 第 [9] 条
  在导入期就核这件事 —— 这里再把读数摊开一次）；
- 行为那一侧：只给 `statement_id` 真调一次，返回的正文读数（`proof_sha256` /
  `proof_chars`）与盘上那一份逐字对上 —— "没报缺少必填"还不够，必须证明正文真的取到了；
- 反真空：把那一行的 `proof_text` 清空 ⇒ 同一次调用报 `no_proof_text`。
  没有这一条，上面那条"取到了正文"可能只是"某个常量恰好非空"。

零模型钱：模型缝是本地替身（`_ScriptedSeam`），不起任何外部进程。
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace
from typing import Any

from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.store import Store
from agentflow.tools import build_for_role

from conftest import TS, add_literature

#: 盘上那一份证明的正文（判据要能把它与返回里的读数逐字对上）。
PROOF = "1. 由定义直接得到。2. 代入上一行即得。"

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
        for full, proof in ((S_WITH_PROOF, PROOF), (S_NO_PROOF, "")):
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


def _call(st: Store, stmt_id: str):
    """只给命题号调一次 `verify.verify_proof`（改前被参数门拒掉的就是这一次调用）。"""
    from agentflow import agent_v

    reg = build_for_role("V", store=st, workspace_root=str(st.root)).registry
    saved = agent_v.default_llm()
    agent_v.set_default_llm(_ScriptedSeam())
    try:
        return reg.call("verify.verify_proof", role="V", statement_id=stmt_id)
    finally:
        agent_v.set_default_llm(saved)


def test_the_three_faces_of_proof_text_say_the_same_sentence(tmp_path: pathlib.Path) -> None:
    """① 只给命题号 ⇒ 不报缺少必填，正文从 statements 取到（读数与盘上那一份逐字对上）。

    改前红：同一个调用得到 `ok=False / kind=param_error`，拒信逐字是
    `缺少必填参数：proof_text`。
    """
    st = _ws(tmp_path)
    with_proof, _no_proof = _ids(st)

    # ---- 声明那一侧：工具层（真身）与能力层的 required 里都不许有它
    from agentflow import capabilities as C

    spec = C.find_action("V", "verify_proof")
    assert spec is not None, "能力表里没有 V.verify_proof"
    assert "proof_text" not in tuple((spec.params or {}).get("required") or ()), (
        "能力层的 required 里还有 proof_text ⇒ 两层根级 required 会对不上"
        "（`assert_capabilities()` 第 [9] 条在导入期就会炸）")

    reg = build_for_role("V", store=st, workspace_root=str(st.root)).registry
    tool_spec = reg.get("verify.verify_proof")
    assert "proof_text" not in tuple((tool_spec.params or {}).get("required") or ()), (
        "工具层的 required 里还有 proof_text ⇒ 只给命题号仍会被参数门拒成 param_invalid")

    # ---- 行为那一侧：真调一次
    res = _call(st, with_proof)
    assert res.ok is True, (res.error, res.meta)
    data = dict(res.data or {})
    assert data.get("checked") is True, data
    assert data.get("verdict") == "成立", data
    # 正文真的从盘上那一份取到了（不是"没报错"就算过）
    assert data.get("proof_sha256") == VR.proof_sha(PROOF), (
        data.get("proof_sha256"), VR.proof_sha(PROOF))
    assert data.get("proof_chars") == len(PROOF), data.get("proof_chars")


def test_an_empty_shelf_row_still_says_no_proof_text(tmp_path: pathlib.Path) -> None:
    """① 反真空：正文为空的那条命题仍然报 `no_proof_text`。

    上一条证明"从 statements 取到了"；这一条证明那个"取"真的读了那一行 ——
    把正文清空，同一句就变成"没有可审的全文"（不是"取到了空串照样审"）。
    """
    st = _ws(tmp_path)
    _with_proof, no_proof = _ids(st)
    res = _call(st, no_proof)
    assert res.ok is True, (res.error, res.meta)
    data = dict(res.data or {})
    assert data.get("checked") is False, data
    assert data.get("reason") == "no_proof_text", data
