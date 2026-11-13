# -*- coding: utf-8 -*-
"""开稿口（2026-11-13 业主裁定）：写命题 → 命题形式过审 → 拿稿号 → 落骨架。

业主口径（逐字）：

> 「统一 B、E、F 注册稿和写稿的流程：写命题 → 命题形式过审 → 拿稿号 → 写稿
> （稿允许慢慢 edit，不必一次成稿）」

## 这个文件钉什么

| 编号 | 判据 | 用例 |
|---|---|---|
| a | 命题形状不合格 ⇒ 受控拒 `proposition_form_refused`、`reports/` 零字节、号源未动（三族各一条） | `test_a_*` |
| b | 形状合格 ⇒ 拿到稿号、骨架在盘上、`## 命题` 逐字 == 命题、此时 `statements` 零行（三族各一条） | `test_b_*` |
| c | 同一份稿可被多次写（至少两次、逐次 sha 变），且不触发「一次成稿」类拒信 | `test_c_*` |
| f1 | 反真空①：把闸打桩成恒放行 ⇒ a 必红 | `test_f1_*` |
| f2 | 反真空②：把号源打桩成不发号 ⇒ b 必红 | `test_f2_*` |
| g | 三族流程同构：同一份判据脚本参数化跑 F/E/B 三遍，三遍全绿 | `test_g_*` |
| h | 角色-族绑定：F 碰不到 b/e 族、E 碰不到 f 族、B 碰不到 e 族 | `test_h_*` |

## 为什么这组用例能代表「三族同构」

三条 `test_a_*` / `test_b_*` 是同一个函数体按 `(role, family)` 参数化：断言逐字相同，
只有族与稿头行不同。任何一族自己的分叉（例如只给 E 留了一条绕过开稿口的路）都会让
那一格参数红。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import depsection as DS
from agentflow import manuscriptfamily as MFAM
from agentflow import manuscriptids as MID
from agentflow import manuscriptopen as MO
from agentflow import proofregistry as PR
from agentflow import secretary as SEC
from agentflow.store import Store

PROP = "设 x 为正实数；则 x + 1/x ≥ 2，等号当且仅当 x = 1。"
NOTE = "按 V u-000005 的唯一缺陷修订第 7 步：把第 7 步改掉，其余八步一字不动，重送 V。"

#: 三族（角色, 族, 稿头行）。E 两族都跑：e-proof 有 `## 证明`，e-num 只有 `## 数值结果`。
TRIPLE = [
    ("F", "f-proof", ("- 计划：plan-000001 · 子目标：s1",)),
    ("E", "e-proof", ("- 实验号：exp:000001",)),
    ("E", "e-num", ("- 实验号：exp:000001",)),
    ("B", "b-proof", ("- 标签：夹具",)),
]


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _judge(**kw):
    return {"checked": True, "well_formed": True, "conditions": "设 x 为正实数",
            "conclusion": "则 x + 1/x ≥ 2，等号当且仅当 x = 1",
            "problems": [], "decision": "夹具：合规", "refused": "",
            "reason": "夹具", "cached": False}


def _judge_bad(**kw):
    return {"checked": True, "well_formed": False, "conditions": "", "conclusion": "",
            "problems": ["结论不是可判真假的数学断言，而是流程要求"],
            "decision": "夹具：不是命题", "refused": SEC.PROPOSITION_FORM_REFUSED,
            "reason": "夹具：形态不合规", "cached": False}


def _section(text: str, name: str) -> str:
    _head, sections = PR.split_sections(text)
    return next((body for got, body in sections if got == name), "")


def _reports(root: pathlib.Path) -> list[str]:
    d = root / MFAM.MANUSCRIPT_DIR
    return sorted(p.name for p in d.glob("*.md")) if d.is_dir() else []


# ---------------------------------------------------------------- a：闸在前
@pytest.mark.parametrize(("role", "family", "header"), TRIPLE)
def test_a_a_bad_proposition_is_refused_before_any_id_or_byte(
        tmp_path: pathlib.Path, role: str, family: str, header: tuple[str, ...]) -> None:
    """形状不合格 ⇒ 受控拒、零字节、号源不动。改前：F 先发号后过闸（号被吃掉）。"""
    st = _ws(tmp_path)
    root = pathlib.Path(st.root)
    before = MID.peek_manuscript_counter(root, family=family)
    got = MO.open_manuscript(root, role=role, family=family, proposition=NOTE,
                             judge=_judge_bad, header_lines=header)
    assert got["ok"] is False, got
    assert got["refused"] == SEC.PROPOSITION_FORM_REFUSED, got
    assert got["problems"], "拒信必须逐条说缺什么"
    assert got["path"] == "" and got["manuscript_id"] == "", got
    assert _reports(root) == [], "闸判不过 ⇒ reports/ 一个字节都不许有"
    assert MID.peek_manuscript_counter(root, family=family) == before, "闸判不过 ⇒ 号源不动"
    assert st.rows("statements") == [], "闸判不过 ⇒ statements 零行"


# ---------------------------------------------------------------- b：骨架
@pytest.mark.parametrize(("role", "family", "header"), TRIPLE)
def test_b_b_a_well_formed_proposition_opens_a_skeleton(
        tmp_path: pathlib.Path, role: str, family: str, header: tuple[str, ...]) -> None:
    """形状合格 ⇒ 稿号 + 骨架在盘上 + `## 命题` 逐字 == 命题；还没有 statements 行。"""
    st = _ws(tmp_path)
    root = pathlib.Path(st.root)
    got = MO.open_manuscript(root, role=role, family=family, proposition=PROP,
                             judge=_judge, header_lines=header, title="夹具定理")
    assert got["ok"] is True, got
    assert got["written"] is True and got["draft"] is True, got
    assert MID.is_manuscript_id(got["manuscript_id"]), got
    assert got["path"] == MFAM.relpath(family, got["manuscript_id"]), got
    target = root / got["path"]
    assert target.is_file(), "骨架必须落在盘上"
    text = target.read_text(encoding="utf-8")
    assert text == got["text"], "回执里的骨架全文必须就是盘上那一份（模型据此免读一次）"
    assert _section(text, "命题").strip() == PROP, "`## 命题` 必须逐字 == 命题"
    assert _section(text, "证明").strip() == "", "骨架的 `## 证明` 是空的"
    assert "## 数值结果" not in text or family == "e-num", text
    if family == "e-num":
        assert DS.SECTION_PROOF not in text, "e-num 没有 `## 证明` 那一节"
    assert st.rows("statements") == [], "开稿不发命题号：statements 此时零行"
    # 重开同一号 ⇒ 一个字节都不写（绝不覆盖已有稿 / 已有 edit）
    again = MO.open_manuscript(root, role=role, family=family, proposition=PROP,
                               judge=_judge, manuscript_id=got["manuscript_id"])
    assert again["ok"] is True and again["written"] is False and again["preserved"] is True
    assert (root / got["path"]).read_text(encoding="utf-8") == text


# ---------------------------------------------------------------- c：慢慢改
@pytest.mark.parametrize(("role", "family", "header"), TRIPLE)
def test_c_c_the_same_manuscript_can_be_written_more_than_once(
        tmp_path: pathlib.Path, role: str, family: str, header: tuple[str, ...]) -> None:
    """同一份稿写两次（逐次 sha 变），第二次仍放行 —— 没有「一次成稿」这道拒信。"""
    st = _ws(tmp_path)
    root = pathlib.Path(st.root)
    got = MO.open_manuscript(root, role=role, family=family, proposition=PROP,
                             judge=_judge, header_lines=header)
    rel = got["path"]
    section = "数值结果" if family == "e-num" else "证明"
    one = MO.write_section(root, role=role, rel=rel, section=section, body="1. 第一步。")
    assert one["ok"] is True and one["written"] is True, one
    two = MO.write_section(root, role=role, rel=rel, section=section,
                           body="1. 第一步。\n2. 第二步（这一版把第二步补上）。")
    assert two["ok"] is True and two["written"] is True, two
    assert one["sha256"] != two["sha256"], "逐次写必须让文件 sha 变"
    text = (root / rel).read_text(encoding="utf-8")
    assert "第二步" in text and _section(text, "命题").strip() == PROP, "命题一个字节都不许动"
    # `## 命题` 不归写内容的口：改它等于绕开形态闸
    bad = MO.write_section(root, role=role, rel=rel, section="命题", body="换一条命题")
    assert bad["ok"] is False and bad["refused"] == MO.SECTION_NOT_WRITABLE, bad


# ---------------------------------------------------------------- f1/f2：反真空
@pytest.mark.parametrize(("role", "family", "header"), TRIPLE)
def test_f1_the_gate_is_what_makes_a_red(tmp_path: pathlib.Path, role: str, family: str,
                                         header: tuple[str, ...]) -> None:
    """把闸打桩成恒放行 ⇒ a 那一条会绿（同一段流程说明 a 的红来自闸）。"""
    st = _ws(tmp_path)
    root = pathlib.Path(st.root)
    got = MO.open_manuscript(root, role=role, family=family, proposition=NOTE,
                             judge=_judge, header_lines=header)
    assert got["ok"] is True and (root / got["path"]).is_file(), (
        "闸恒放行时同一段「修订说明」会照旧开出一份骨架 ⇒ a 的绿只能来自闸")


def test_f2_the_id_source_is_what_makes_b_red(tmp_path: pathlib.Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """把号源打桩成不发号 ⇒ b 那一条必红（没有稿号、没有骨架）。"""
    st = _ws(tmp_path)
    root = pathlib.Path(st.root)

    def _no_id(*_a, **_kw):
        raise MID.ManuscriptIdError("夹具：号源不发号")

    monkeypatch.setattr(MO._MID, "next_manuscript_id", _no_id)
    got = MO.open_manuscript(root, role="F", family="f-proof", proposition=PROP,
                             judge=_judge)
    assert got["ok"] is False and got["refused"] == MO.ID_UNAVAILABLE, got
    assert _reports(root) == [], "没号 ⇒ 不许落一份没有身份的稿"
    # 反真空的反面：不打桩时同一条会绿（b 的绿来自号源这一步）
    monkeypatch.undo()
    ok = MO.open_manuscript(root, role="F", family="f-proof", proposition=PROP,
                            judge=_judge)
    assert ok["ok"] is True and (root / ok["path"]).is_file()


# ---------------------------------------------------------------- g：同构
def test_g_g_the_same_script_passes_for_all_three_families(tmp_path: pathlib.Path) -> None:
    """同一份脚本跑 F / E(proof) / E(num) / B 四遍：四遍读数的键集与判定逐字相同。"""
    root = pathlib.Path(_ws(tmp_path).root)
    readings = []
    for role, family, header in TRIPLE:
        bad = MO.open_manuscript(root, role=role, family=family, proposition=NOTE,
                                 judge=_judge_bad, header_lines=header)
        good = MO.open_manuscript(root, role=role, family=family, proposition=PROP,
                                  judge=_judge, header_lines=header)
        readings.append((family, bad["refused"], good["ok"], good["draft"],
                         bool(good["manuscript_id"])))
    assert [r[1] for r in readings] == [SEC.PROPOSITION_FORM_REFUSED] * len(TRIPLE)
    assert all(r[2] and r[3] and r[4] for r in readings), readings


# ---------------------------------------------------------------- h：角色-族绑定
def test_h_h_a_role_only_touches_its_own_family(tmp_path: pathlib.Path) -> None:
    """别人的稿不可改：F 碰不到 b/e、E 碰不到 f、B 碰不到 e（含 e-num 那一族）。"""
    root = pathlib.Path(_ws(tmp_path).root)
    made = {}
    for role, family, header in TRIPLE:
        got = MO.open_manuscript(root, role=role, family=family, proposition=PROP,
                                 judge=_judge, header_lines=header)
        assert got["ok"], got
        made[family] = got["path"]
    for role, family in (("F", "b-proof"), ("F", "e-num"), ("E", "f-proof"),
                         ("B", "e-proof")):
        got = MO.write_section(root, role=role, rel=made[family], section="证明",
                               body="越权改别人的稿")
        assert got["ok"] is False, got
        assert got["refused"] == MO.FAMILY_NOT_OWNED, got
        verdict = MO.write_allowed(rel=made[family], role=role, root=root)
        assert verdict["allowed"] is False and verdict["owns"] is False, verdict
    # 自家那一份仍然放行（正控：收紧不许把正路一起关掉）
    mine = MO.write_allowed(rel=made["f-proof"], role="F", root=root)
    assert mine["allowed"] is True, mine
