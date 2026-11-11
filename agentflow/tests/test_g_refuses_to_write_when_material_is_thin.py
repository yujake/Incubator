# -*- coding: utf-8 -*-
"""乙（2026-11-11，业主：「乙是已有设计，不要重复劳动，只需看通不通」）的连通性判据。

这一条不改实现，只回答一件事：料不足时，已有的那条路会不会真的产出
「受控拒成文 + 让 G 去要料（走 D）」，还是它会照写一篇薄的？

## 已有的那条路（两半，各自只有一个落点）

1. 拒成文（硬闸，代码）：`tools/doc_tools.py::_doc_write_mapping` 的成文门 ——
   先问 `researchbase.research_base(store)`；`state != "ready"` ⇒ 受控拒
   `kind="no_evidence_chain"`、`written=False`（`MAPPING.json` 一个字节都不写）。
   判据本来就有：`tests/test_g_cannot_write_a_paper_on_an_empty_research_base.py`。
2. 向 D 要料（题面 + 拒信）：G 的声明正文里那句逐字——
   「发现证据不足时要回去要：把「缺什么、要什么样的证据」写清交给 D」；
   拒信的 `next_steps` 把 D 那条链点名（「让 D 出研究手稿…你 → D → B」），
   并写明「不许杜撰」。

## 这条判据钉什么（只看通不通）

- 缺料现场（有一条命题但没有 `proof_text`、没有可核引文）⇒ 受控拒 + 一个字节不写；
- 拒信里点得到缺什么（`research_base.missing`）且点得到 D 那条正路
  （`next_steps` 里「让 D 出研究手稿」与「你 → D → B」）；
- 题面真的带着「证据不足 ⇒ 写清缺什么交给 D」那一句（从 `SPEC.brief` 取，不读源码字符串）；
- 料到位之后（同一条命题补上 `proof_text`）⇒ 同一道门不再拒成文（不是永远拒）。

没有一条断言说"框架会替 G 派 D"——它不派；派活是 G 的动作。这一格答的是
"现有的拒信与题面把 G 推到 D 那条路上没有"，与"G 下一拍照不照做"是两件事
（后者要模型调用，见报告里的读数与断点）。
"""
from __future__ import annotations

import pathlib

from agentflow import researchbase as RB
from agentflow.specs import g as GSPEC
from agentflow.store import Store

from test_g_cannot_write_a_paper_on_an_empty_research_base import (
    _registry, _rows, _statement, _store,
)


def _write_mapping(st: Store):
    return _registry(st).call("doc.write_mapping", project="projects/p1",
                              rows=_rows())


def test_g_refuses_to_write_when_material_is_thin(tmp_path: pathlib.Path) -> None:
    st = _store(tmp_path)
    # 料不足：只有一条标题，没有 proof_text、没有可核引文（真机那种「产出不足」）
    _statement(st, "000000")
    base = RB.research_base(st)
    assert base["state"] == "insufficient", base

    res = _write_mapping(st)
    # ① 受控拒成文，而且一个字节都不写
    assert res.ok is False, res.data
    assert res.meta.get("kind") == "no_evidence_chain", res.meta
    assert res.meta.get("written") is False, res.meta
    paper = st.root / "projects" / "p1" / "out" / "paper"
    assert not (paper / "MAPPING.json").exists(), "门拒了却把对应表写出来了"

    # ② 拒信里点得到"缺什么"（不是一句泛泛的"材料不足"）
    missing = " ".join(str(x) for x in (base.get("missing") or []))
    assert missing.strip(), base
    assert "proof_text" in missing or "引文" in missing, base

    # ③ 拒信里点得到 D 那条正路（这一步是"申请补充"的落点）
    steps = " ".join(str(x) for x in (res.meta.get("next_steps") or []))
    assert "让 D 出研究手稿" in steps, steps
    assert "你 → D → B" in steps, steps
    assert "不许杜撰" in steps, steps

    # ④ 题面（G 的声明正文，不是源码字符串）真的教了"缺料就把缺什么交给 D"
    boundary = " ".join(str(x) for x in GSPEC.SPEC.brief.boundary)
    assert "证据不足时要回去要" in boundary, boundary[:200]
    assert "把「缺什么、要什么样的证据」写清" in boundary, boundary[:200]
    assert "交给 D" in boundary, boundary[:200]

    # ⑤ 料到位之后同一道门放行（不是永远拒）：同一条命题补上 proof_text
    _statement(st, "000001", proof="Proof. 由定义直接得到。")
    assert RB.research_base(st)["state"] == "ready"
    after = _write_mapping(st)
    assert after.meta.get("kind") != "no_evidence_chain", after.meta
