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


# ====================================================================== ② 写集的定位
def _manifest_reason_for(path_tail: str) -> str:
    """从 `.noai-paths` 取某一条路径的理由串（清单里的理由是权威口径，不另抄一份）。"""
    manifest = (REPO / ".noai-paths").read_text(encoding="utf-8")
    for line in manifest.splitlines():
        if line.strip().startswith(path_tail):
            return line
    raise AssertionError(f".noai-paths 里找不到 {path_tail}")


def test_write_sets_are_documented_as_a_concurrency_axis_not_permission() -> None:
    """写集是并发轴（谁能同时写同一张表），不是权限轴；「L 绕不过 V 签」的真拦点是另两条。"""
    from agentflow import capabilities as C
    from agentflow import secretary as SEC
    from agentflow import store as ST
    from scripts import noai_gate as G

    specs = _text(ROLE_SPECS)
    assert "并发轴，不是权限轴" in specs
    assert "通用设计，不必精确到单个角色" in specs
    assert "direct_write_refusal" in specs and "not_statement_writer" in specs
    # 旧归因那句话必须已经不在权威正文里
    assert "刻意**不含** `statements` ⇒ \"L 绕过 V 的签给命题升档\"在结构上不可能" not in specs

    # 两处清单逐条一致（FC-27 的机器判据），且 L 那条理由说的是真拦点
    assert G.check_manifest_consistency(
        manifest_path=REPO / ".noai-paths", agents_md=REPO / "AGENTS.md") == []
    agents_reason = ""
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    for line in agents.splitlines():
        if line.strip().startswith("src/agentflow/specs/l.py"):
            agents_reason = line
            break
    assert agents_reason, "AGENTS.md 清单里找不到 specs/l.py 那一条"
    assert agents_reason == _manifest_reason_for("src/agentflow/specs/l.py")
    assert "direct_write_refusal" in agents_reason and "not_statement_writer" in agents_reason
    assert "刻意不含 statements" not in agents_reason

    # 代码面：那两条真拦点真的在
    assert SEC.STATEMENT_WRITER_ROLES == ("B",)
    for table in ("statements", "dependencies"):
        assert ST.direct_write_refusal(table)
    assert C.WRITE_SETS["L"] == frozenset({"experiments"})


# ====================================================================== ③ L 的工具面 vs 协作面
def test_l_tool_face_is_wider_than_its_collab_face() -> None:
    """L 名下可有通用工具（retire_child / void_items），但协作面只有 B -> L -> C；broadcast 已退场。"""
    from agentflow import capabilities as C
    from agentflow.tools import conductor_tools as CT
    from agentflow.tools import formal_tools as FT

    assert C.ALLOWED_EDGES["L"] == frozenset({"C"}), C.ALLOWED_EDGES["L"]
    inbound = {role for role, tos in C.ALLOWED_EDGES.items() if "L" in tos}
    assert inbound == {"B"}, inbound

    names = [func.__name__ for func, _deps in CT._TOOL_FUNCTIONS]
    assert "conductor_retire_child" in names and "conductor_void_items" in names
    assert "conductor_broadcast" not in names, "broadcast 已于 2026-11-16 全面退场"
    assert not hasattr(CT, "conductor_broadcast")
    assert "L" in CT._PARENT_ROLES
    assert FT._ROLES_L == ("L",)

    specs = _text(ROLE_SPECS)
    section = specs.split("### L.4", 1)[1].split("### L.5", 1)[0]
    assert "工具面比协作面宽" in section
    assert "协作面只有 `B → L → C`" in section
    assert "conductor.retire_child" in section and "conductor.void_items" in section
    assert "conductor.broadcast` /" not in section, "L 的工具清单里还挂着已退场的 broadcast"
