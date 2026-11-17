# -*- coding: utf-8 -*-
"""AU2b 乙组对齐判据：文档说的与代码做的必须逐条对得上。

## 这一份为什么存在

AU2b 报的那批问题分两类：一类是「权限结构真的不对」（本路不许动权限面），
另一类是「文档把同一件事写错了 / 写成旧口径」。这一份只钉第二类 —— 每一条判据都由
代码现算与文档原文两头对拍，文档改了而代码没改（或反过来）都会红。

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


# ====================================================================== ⑥ 旧文档 8 条
def _edge_table_rows(text: str) -> dict[str, str]:
    """从 ROLE-SPECS §0.5 的边表取「角色 -> 出边那一格原文」。"""
    body = text.split("### 0.5", 1)[1].split("### 0.6", 1)[0]
    rows: dict[str, str] = {}
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        role = re.fullmatch(r"`([A-Z])`(?:（.*）)?", cells[0])
        if role:
            rows[role.group(1)] = cells[1]
    return rows


def _letter_set(cell: str) -> frozenset[str]:
    """出边那一格里第一个「大写字母 + 空格」的代码跨度；没有 ⇒ 空集。

    只看破折号之前那一截：`（无出边）—— 入边 `F` / `E` / `B`…` 里的入边不能当成出边。
    """
    for span in re.findall(r"`([^`]+)`", cell.split("——", 1)[0]):
        if re.fullmatch(r"[A-Z](?: [A-Z])*", span):
            return frozenset(span.split())
    return frozenset()


def test_role_specs_edge_table_matches_capabilities() -> None:
    """§0.5 的出边表逐行等于 ALLOWED_EDGES（F 的 A C D E V 不再写回 A B C E V）。"""
    from agentflow import capabilities as C

    text = _text(ROLE_SPECS)
    rows = _edge_table_rows(text)
    assert set(rows) == {"A", "B", "C", "D", "E", "F", "G", "H", "V", "L", "M"}, set(rows)
    for role, cell in rows.items():
        assert _letter_set(cell) == frozenset(C.ALLOWED_EDGES.get(role) or ()), (role, cell)
    assert "`A C D E V`" in rows["F"]
    assert "`A B C E V`" not in rows["F"]

    # 各 X.9 的入边清单：只钉被 AU2b 点过名的那几处，且用现算的入边集合作反真空
    inbound = {r: {frm for frm, tos in C.ALLOWED_EDGES.items() if r in tos}
               for r in "ABCDEFGHVL"}
    e9 = text.split("### E.9", 1)[1].split("### E.10", 1)[0]
    first = e9.split("**不是", 1)[0]
    assert frozenset(re.findall(r"`([A-Z])`", first)) == frozenset(inbound["E"]), first
    assert "不是 `G`" in e9
    f9 = text.split("### F.9", 1)[1].split("### F.10", 1)[0]
    assert frozenset(re.findall(r"`([A-Z])`", f9.split("入边只有", 1)[1].split("。", 1)[0])) == \
        frozenset(inbound["F"]), f9[:200]


def test_closing_gate_is_documented_as_eight_cells() -> None:
    """收工门现在是 8 格（含 literature_pending）；paper 不在门里 —— 三份文档同一口径。"""
    from agentflow import closing

    checks = tuple(closing.DEFAULT_CHECKS)
    assert len(checks) == 8, checks
    assert "literature_pending" in checks and "paper" not in checks

    specs = _text(ROLE_SPECS)
    row = [ln for ln in specs.splitlines() if ln.startswith("| 81 | `conductor.closing`")]
    assert len(row) == 1, row
    for key in checks:
        assert f"`{key}`" in row[0], key
    assert "`paper` 不在门里" in row[0]

    guide = _text(DOCS / "USER-GUIDE.md")
    assert "八格" not in guide
    assert "literature_pending" in guide
    components = _text(DOCS / "SYSTEM-COMPONENTS.md")
    assert "收工门八格" in components and "DEFAULT_CHECKS 八格" in components


def test_lean_modes_puts_the_formal_obligation_on_l() -> None:
    """LEAN-MODES 的形式化义务归 L（M 派 B 安排），E 那一档是受控拒绝。"""
    text = _text(DOCS / "LEAN-MODES.md")
    assert "E 的形式化义务" not in text
    assert "L 的形式化义务" in text
    assert "formal_not_in_e" in text
    assert "派 B（`M→B`）由 B 逐条安排 L" in text
    assert "verify.check_formal" not in text


def test_role_guide_conjecture_rows_follow_the_one_write_point() -> None:
    """猜想台账的唯一写点是产出侧（E/F/B）；D 只读、没有 register_conjecture。"""
    import sys

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools import write_system_docs as W

    def rows(role: str) -> list[tuple[str, str, str]]:
        return list(W.ARTIFACTS[role])

    def conjecture_rw(role: str) -> list[str]:
        return [rw for path, rw, _detail in rows(role)
                if "conjectures.json" in path]

    assert conjecture_rw("D") == ["只读"]
    assert conjecture_rw("E") == ["写"]
    assert conjecture_rw("F") == ["写"]
    assert conjecture_rw("B") == ["写"]
    joined = "\n".join(detail for role in ("A", "B", "C", "D", "E", "F", "G", "H", "V", "L", "M")
                       for _p, _rw, detail in rows(role))
    assert "register_conjecture（D" not in joined
    guide = _text(DOCS / "ROLE-GUIDE.md")
    assert "register_conjecture（D 的主力动作" not in guide
