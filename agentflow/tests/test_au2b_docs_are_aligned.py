# -*- coding: utf-8 -*-
"""AU2b 乙组对齐判据：文档说的与代码做的必须逐条对得上。

## 这一份为什么存在

AU2b 报的那批问题分两类：一类是「权限结构真的不对」（本路不许动权限面），
另一类是「文档把同一件事写错了 / 写成旧口径」。这一份只钉第二类 —— 每一条判据都由
**代码现算**与**文档原文**两头对拍，文档改了而代码没改（或反过来）都会红。

## 三态与反真空

每条判据都先断言「盘上确实读到了这一段」，再比对；读不到不是「通过」。
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
ROLE_SPECS = DOCS / "ROLE-SPECS.md"
DESIGN_ROLES = REPO / "DESIGN-ROLES.md"


def _text(path: pathlib.Path) -> str:
    assert path.is_file(), f"{path} 不在盘上 ⇒ 判据的对象没了"
    got = path.read_text(encoding="utf-8")
    assert len(got) > 1000, f"{path} 只读到 {len(got)} 字节 ⇒ 读错了文件"
    return got


# ====================================================================== ① 秘书的地位
def test_secretary_is_documented_as_a_channel_and_ledger_proxy() -> None:
    """秘书不是角色：不在 ROLES / 无可召唤 / 不在边表；它是判定通道 + 落库代理（框架代写）。"""
    from agentflow import capabilities as C
    from agentflow import schema as S
    from agentflow import secretary as SEC
    from agentflow import store as ST

    # ---- 代码面：四件「不是角色」的证据
    assert tuple(S.ROLES) == ("A", "B", "C", "D", "E", "F", "G", "H", "V", "L"), S.ROLES
    for word in ("秘书", "secretary", "S"):
        assert word not in S.ROLES, f"ROLES 里出现了 {word!r} ⇒ 秘书被当成角色了"
    assert set(C.CAPABILITIES) == set(S.ROLES) | {S.CONDUCTOR_ROLE}, set(C.CAPABILITIES)
    for word in ("秘书", "secretary", "S"):
        assert word not in C.ALLOWED_EDGES
        assert all(word not in tos for tos in C.ALLOWED_EDGES.values())
    assert SEC.STATEMENT_WRITER_ROLES == ("B",), SEC.STATEMENT_WRITER_ROLES
    for table in ("statements", "dependencies"):
        assert ST.direct_write_refusal(table), f"{table} 的通用写口没有被拒 ⇒ 真拦点不在了"
    for name in ("record_statement", "record_nontriviality", "decide_sign_issuance",
                 "land_unregistered_sign"):
        assert callable(getattr(SEC.Secretary, name, None)), f"Secretary 上没有 {name}"

    # ---- 文档面：权威正文必须把这两件事写清（不是一句口号）
    specs = _text(ROLE_SPECS)
    assert "### 0.0 秘书不是角色" in specs
    assert "判定通道 + 落库代理" in specs
    assert "框架代写" in specs
    assert "not_statement_writer" in specs
    design = _text(DESIGN_ROLES)
    assert "秘书不是角色" in design and "判定通道 + 落库代理" in design
