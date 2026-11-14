# -*- coding: utf-8 -*-
"""判据：命题类型 与 证据档位 是两根轴，名字、来源、权威各不同（2026-11-14）。

业主 2026-11-14：「将命题类型和等级两组词进行解耦」。

## 两根轴（这张表是本文件的纲）

| 轴 | 取值 | 谁写 | 权威 | 代码落点 |
|---|---|---|---|---|
| 命题类型 | theorem / lemma / proposition / corollary / conjecture / example / concept / definition | 作者（F/E 的手稿头、B 的调用参数） | 台账 `statements.kind` | `secretary.STATEMENT_META_KINDS`；手稿头标记 `manuscriptkind.PROPOSITION_KIND_MARK` |
| 证据档位 | proof / proof_review / cross_check / heuristic | 机械（五元位现算） | `schema.EVIDENCE_KINDS` | `evidencebits.derive_grade` → `evidencebits.GRADES`（档位是等级的历史反算名） |

改前手稿头那一行叫 `- 证据种类：`、装的却是命题类型 —— 名字借了另一根轴的词。
本文件钉四件事：

- a) 新渲染的稿头是 `- 命题类型：<kind>`，且没有 `- 命题号：`（反向断言）；
- b) 老盘 `- 证据种类：<kind>` 仍读得出（读能力不删）；
- c) 台账 `statements.kind` 与稿上类型不一致 ⇒ 专用读数 `kind_crosscheck`
     带 `outcome=mismatch`（不是静默取其一），方向性受控码照旧
     （升档 `kind_not_upgraded_without_sign` / 降档 `kind_downgrade`）；
- d) 等级那一轴一个字节没动：`derive_grade` 的输入输出与词表逐字不变
     （既有 `tests/test_evidence_bits.py` / `tests/test_two_axes_grade_and_kind.py`
     是完整回归面，这里只钉"没被这次改名碰过"）。

两个反真空：

- a 的反真空：渲染→读回必须走同一对新名字（只渲染不读回，改错了也绿）；
- c 的反真空：把 `proofregistry.kind_crosscheck` 打桩成"恒一致" ⇒
  mismatch 读数消失，正控当场红。

## 不碰的东西

`schema.py` / `store.py` / `specs/*` / `tests/golden/*` 一格未动：`specs/b.py` 的
`proof_manuscript` 说明里仍写着旧名 `- 证据种类：` —— 它被冻结在
`tests/golden/agent_surface_snapshot.json` 与 `tests/fixtures/tool_declaration_baseline.json`
里，改名要重冻快照（人审面，见交付报告）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import evidencebits as EB
from agentflow import manuscriptintake as MI
from agentflow import manuscriptkind as MK
from agentflow import proofregistry as PR
from agentflow import schema as S

#: 本文件所在的 `tests/` 目录（老盘夹具按它找）。
TESTS = pathlib.Path(__file__).resolve().parent

#: 证据档位那一轴的四个取值（一字不改；改它就是改等级口径 ⇒ 停手报人）。
GRADE_AXIS = ("proof", "proof_review", "cross_check", "heuristic")
#: 等级（`derive_grade` 的真输出域；档位只是它的历史反算名）。
GRADE_LEVELS = ("conjecture", "strong_conjecture", "pre_theorem", "theorem")


def _manuscript(kind_line: str = "- 命题类型：conjecture") -> str:
    """三节齐全的最小稿；`kind_line` 换掉稿头那一行（空串 = 不声明）。"""
    head = kind_line + "\n" if kind_line else ""
    return (head + "\n## 命题\n\nP 对所有实数 x 成立。\n\n"
            + "## 证明\n\n逐项验算。\n\n"
            + "## 依赖\n\n| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |\n"
            + "|---|---|---|\n")


def _plan(text: str, *, ledger_kind: str) -> dict:
    """把一份稿的 `kind` 格对到一条台账行上（`plan_cells`，不读盘、不写盘）。"""
    row = {"stmt_id": "000001", "statement_full": "P 对所有实数 x 成立。",
           "kind": ledger_kind}
    got = MI.extract_cells(text, "f-proof", ["kind"])
    return MI.plan_cells(row, got, "refuse", family="f-proof")


# ===================================================== a 新渲染：新名 + 没有命题号

def test_a_new_manuscript_head_uses_the_type_label_and_has_no_statement_number(
        tmp_path: pathlib.Path) -> None:
    """a：新渲染的稿头是 `- 命题类型：lemma`；没有 `- 命题号：`；没有旧名。"""
    got = PR.register_or_rewrite(
        str(tmp_path), family="F", label="夹具", proposition="P 对所有实数 x 成立。",
        proof_text="逐项验算。", manuscript_id="000001", kind="lemma")
    assert got.get("ok") is True, got
    text = (tmp_path / str(got["manuscript_path"])).read_text(encoding="utf-8")
    assert f"{MK.PROPOSITION_KIND_MARK}lemma" in text, text[:400]
    # 反向断言（业主 2026-11-13 的裁定：稿里没有命题号，任何稿里都没有）。
    assert "- 命题号：" not in text, text[:400]
    # 旧名不再写进新稿（读侧仍认，见 b）。
    assert MK.LEGACY_PROPOSITION_KIND_MARK not in text, text[:400]


def test_a_anti_vacuum_render_then_read_back_uses_the_same_pair_of_names() -> None:
    """a 的反真空：渲染出来的那一行，读侧真的读得回（只渲染不读回则改错也绿）。

    顺带钉死"两套词表不相交"：稿头写成档位名（`proof_review`）时，读侧照读那个字节
    （`parse_entry` 不猜），但命题类型的判据（`_declared_manuscript_kind`）拒它
    —— 类型那一格只认 `PROPOSITION_KINDS`。
    """
    from agentflow.agent_b import register_statement as RS

    text = _manuscript(f"{MK.PROPOSITION_KIND_MARK}lemma")
    entry = PR.parse_entry(text)
    assert entry["kind"] == "lemma", entry
    assert entry["kind_label"] == "命题类型", entry
    assert RS._declared_manuscript_kind(text=text) == "lemma"
    # 档位名混进类型格 ⇒ parse_entry 照读字节，但类型判据不认（两根轴不互相顶替）。
    crossed = _manuscript(f"{MK.PROPOSITION_KIND_MARK}proof_review")
    assert PR.parse_entry(crossed)["kind"] == "proof_review"
    assert RS._declared_manuscript_kind(text=crossed) == "", crossed


# ===================================================== b 老盘旧名：读得出

def test_b_legacy_label_is_still_readable_from_both_readers() -> None:
    """b：`- 证据种类：lemma` 仍读得出（两个读侧 + 行号与标签读数都在）。"""
    from agentflow.agent_b import register_statement as RS

    legacy = _manuscript(f"{MK.LEGACY_PROPOSITION_KIND_MARK}lemma")
    entry = PR.parse_entry(legacy)
    assert entry["kind"] == "lemma", entry
    assert entry["kind_label"] == "证据种类（老盘旧名）", entry
    assert RS._declared_manuscript_kind(text=legacy) == "lemma"

    reading = MI.extract_cells(legacy, "f-proof", ["kind"])["kind"]
    assert reading["outcome"] == MI.EXTRACT_PRESENT, reading
    assert reading["value"] == "lemma", reading
    assert reading["label"] == "证据种类（老盘旧名）", reading
    assert reading["source"]["lines"], reading
    assert reading["source"]["section"] == f"head: {MK.PROPOSITION_KIND_MARK}", reading


def test_b_legacy_on_disk_replay_manuscript_is_read_as_written() -> None:
    """b（真盘样本）：`tests/fixtures/98b_replay/` 的老 b-proof 稿仍逐字读得回。

    那一批稿的稿头是 `- 证据种类：proof_review` —— 类型格里装着档位名，正是这次
    要解耦的混名形态；历史字节不改（读能力不删），但读出来的就是它写的那个字节。
    """
    path = TESTS / "fixtures" / "98b_replay" / "notes" / "b-proof-000001.md"
    entry = PR.parse_entry(path.read_text(encoding="utf-8"))
    assert entry["kind"] == "proof_review", entry
    assert entry["kind_label"] == "证据种类（老盘旧名）", entry


def test_b_anti_vacuum_a_head_without_the_line_reads_absent_not_guessed() -> None:
    """b 的反真空：没有那一行 ⇒ absent / 空串（不是"读什么都算旧名读得到"）。"""
    from agentflow.agent_b import register_statement as RS

    text = _manuscript("")
    assert PR.parse_entry(text)["kind"] == ""
    assert RS._declared_manuscript_kind(text=text) == ""
    reading = MI.extract_cells(text, "f-proof", ["kind"])["kind"]
    assert reading["outcome"] == MI.EXTRACT_ABSENT, reading
    assert reading["value"] is None, reading


# ===================================================== c 台账为准 + 不一致的专用读数

def test_c_ledger_is_the_authority_and_mismatch_carries_a_dedicated_reading() -> None:
    """c：两侧不一致 ⇒ `kind_crosscheck=…mismatch`（专用读数），台账值不被稿头改走。"""
    # 台账 theorem > 稿头 conjecture ⇒ 拒降档；读数点名 mismatch。
    down = _plan(_manuscript(f"{MK.PROPOSITION_KIND_MARK}conjecture"),
                 ledger_kind="theorem")
    assert down["refused"] == MI.CODE_KIND_DOWNGRADE, down
    cell = down["cells"]["kind"]
    cross = dict(cell.get("crosscheck") or {})
    assert cross.get("outcome") == "mismatch", cell
    assert cross.get("code") == MK.KIND_CROSSCHECK_MISMATCH, cell
    assert (cross.get("ledger"), cross.get("declared")) == ("theorem", "conjecture"), cell
    assert "以台账为准" in str(cross.get("why") or ""), cross

    # 台账 conjecture < 稿头 lemma ⇒ 签后才升（kept）；读数同样点名 mismatch。
    up = _plan(_manuscript(f"{MK.PROPOSITION_KIND_MARK}lemma"), ledger_kind="conjecture")
    assert up["cells"]["kind"]["outcome"] == MI.PLAN_KEPT, up["cells"]["kind"]
    assert up["cells"]["kind"]["code"] == MI.CODE_KIND_UPGRADE_UNSIGNED
    assert (up["cells"]["kind"].get("crosscheck") or {}).get("outcome") == "mismatch"

    # 一致 ⇒ agree（不是"没有读数"，是"读到了、对上了"）。
    same = _plan(_manuscript(f"{MK.PROPOSITION_KIND_MARK}lemma"), ledger_kind="lemma")
    assert same["cells"]["kind"]["outcome"] == MI.PLAN_UNCHANGED
    assert (same["cells"]["kind"].get("crosscheck") or {}).get("outcome") == "agree"


def test_c_anti_vacuum_stubbing_the_crosscheck_hides_the_mismatch(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """c 的反真空：把交叉核对打桩成"恒一致" ⇒ mismatch 读数消失（正控当场红）。

    这正是"不许静默取其一"的机器形态：读数不是装饰，它由 `kind_crosscheck` 的判定
    产生；判定被换掉，读数就没有了。
    """
    real = MK.kind_crosscheck

    def always_agree(ledger_kind, declared_kind):  # noqa: ANN001 - 打桩签名与真身一致
        got = dict(real(ledger_kind, declared_kind))
        if got.get("outcome") == "mismatch":
            got.update(agree=True, outcome="agree",
                       code=MK.KIND_CROSSCHECK_AGREE, why="打桩：恒一致")
        return got

    baseline = _plan(_manuscript(f"{MK.PROPOSITION_KIND_MARK}conjecture"),
                     ledger_kind="theorem")
    assert (baseline["cells"]["kind"].get("crosscheck") or {}).get("outcome") == "mismatch"

    monkeypatch.setattr(MK, "kind_crosscheck", always_agree)
    stubbed = _plan(_manuscript(f"{MK.PROPOSITION_KIND_MARK}conjecture"),
                    ledger_kind="theorem")
    assert (stubbed["cells"]["kind"].get("crosscheck") or {}).get("outcome") != "mismatch", (
        "把交叉核对打桩成恒一致之后 mismatch 还在 ⇒ 读数不是由它产生的（判据没量到对象）")


# ===================================================== d 等级那一轴：一个字节没动

def test_d_the_grade_axis_is_untouched() -> None:
    """d：档位词表 / 等级词表 / 一个代表格的 `derive_grade` 全部逐字不变。

    完整回归面是既有的 `tests/test_evidence_bits.py` 与
    `tests/test_two_axes_grade_and_kind.py`（32 组五元位逐格对拍）；这里只钉
    "这次改名没有碰它"，并在反向断言里禁止命题类型的词渗进等级模块。
    """
    assert tuple(S.EVIDENCE_KINDS) == GRADE_AXIS, S.EVIDENCE_KINDS
    assert tuple(EB.GRADES) == GRADE_LEVELS, EB.GRADES
    assert tuple(EB.LEGACY_KINDS) == tuple(reversed(GRADE_AXIS)), EB.LEGACY_KINDS
    bits = EB.bits_of(numeric="verified", proof=True, reviewed=False,
                      formal="pending", audited=False)
    assert bits["grade"] == "theorem", bits
    assert EB.derive_grade(bits) == "theorem", bits
    assert EB.kind_from_grade("theorem") == "proof", EB.kind_from_grade("theorem")
    # 解耦护栏：命题类型那根轴的词不许出现在等级模块里（出现即两轴又串了）。
    source = pathlib.Path(EB.__file__).read_text(encoding="utf-8")
    assert "命题类型" not in source, "等级模块里出现了命题类型的词 ⇒ 两轴又串了"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
