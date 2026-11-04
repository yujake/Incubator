# -*- coding: utf-8 -*-
"""夹具：按号落一份 V 可读的证明手稿（2026-11-04 业主裁定 甲之后的迁移用）。

在册命题送审必须带 `proof_manuscript`；旧夹具只给 `proof_text` 的调用会被
`proof_text_needs_a_manuscript` 受控拒绝。这一格让迁移只需"补一份稿 + 传路径"，
断言一个字不用改。

`## 依赖` 的四列表头不能省：空表（表头在、0 行）是合法声明；缺整节是
`dependency_section_missing`（V 读稿口同一把尺）。

为什么单独一个模块而不是塞进 `tests/conftest.py`：2026-11-04 的并行开发里
conftest 正被别的 lane 改着；夹具只读 `store.root`、不碰任何全局状态，独立成文件
不会与那一边的写冲突。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from agentflow import depsection as _DS


def write_proof_manuscript(root: Any, statement_id: str, proof_text: str, *,
                           statement_full: str = "", proof_no: int = 1,
                           deps_rows: Iterable[Any] = ()) -> str:
    """写 `reports/f-proof-<号>[-p<N>].md`，返回工作区相对路径。"""
    no = int(proof_no or 1)
    rel = (f"reports/f-proof-{statement_id}.md" if no <= 1
           else f"reports/f-proof-{statement_id}-p{no}.md")
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ("# 证明手稿（夹具）\n\n"
            f"- 命题号：stmt:{statement_id}\n"
            f"- 证明号：{no}\n\n"
            f"## 命题\n\n{statement_full or '（夹具命题）'}\n\n"
            f"## 证明\n\n{proof_text}\n\n"
            + _DS.render_dependency_section(list(deps_rows)))
    path.write_text(text, encoding="utf-8")
    return rel


def carry_proof_manuscript(root: Any, payload: Mapping[str, Any], *,
                           statement_id: str = "000000",
                           proof_no: int = 1) -> dict[str, Any]:
    """把"只给正文"的一笔补成"先写稿再登记"的那一笔（夹具）。

    补三样（都是生产上 B 那一笔本来就带着的）：
    - `proof_manuscript`：`reports/f-proof-<号>.md` 的路径（三节齐，`## 证明` 与
      被审正文逐字一致）—— 秘书这一层不读它，但它是"正文由稿承载"的那个载体；
    - 一份"还没在册"时 V 审出来的手稿签（`record_pending_sign` 的真写口，
      `object_path` 就是我们刚写的那份稿）；
    - 五元位（`evidencebits.bits_of` 现算，不手写形状）—— B 的 `register_statement`
      每一笔都带 `bits`，秘书据此把"签有没有"交给 B 的 `_unsigned_proof_gate` 判；
      直接调秘书的夹具因此也要带它，否则新正文会被"没有在册行"那一档拦下。

    没有 `proof_text` 的一笔原样返回：概念行 / 只落猜想的那一笔本来就不写正文。
    """
    out = dict(payload)
    text = str(out.get("proof_text") or "").strip()
    if not text:
        return out
    full = str(out.get("statement_full") or "")
    kind = str(out.get("kind") or "theorem")
    rel = write_proof_manuscript(root, statement_id, text,
                                 statement_full=full, proof_no=proof_no)
    from agentflow import evidencebits as _EB
    from agentflow import verifications as _VR

    _VR.record_pending_sign(
        str(root), proof_text=text,
        verdict={"verdict": "成立", "findings": []},
        object_path=rel)
    out["proof_manuscript"] = rel
    if not out.get("bits"):
        out["bits"] = _EB.bits_of(
            origin=str(out.get("origin") or "own_result"),
            source_lit_id=str(out.get("source_lit_id") or ""),
            quote_verified=out.get("quote_verified"),
            proof=True, proof_process=text, kind=kind)
    return out
