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
from typing import Any, Iterable

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
