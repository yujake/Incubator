# -*- coding: utf-8 -*-
"""判据：`doc.write_mapping` / `doc.mapping_cells` 的声明文案与 `papermapping` 的实际判定逐条对齐。

## 守什么（2026-11-05，`8b48065b` 之后的新口径）

`tools/doc_tools.py` 的七处声明（summary 的两句、`file` / `lean_file` /
`numeric_evidence` / `exhaustion_note` 四格描述、`doc.mapping_cells` 的 `returns`）
曾经把旧口径写死：凭据格要「E 签的穷举」才算、附加义务压在「证明栏是程序的那几行」、
`file` 只有两种落点、`cells` 的空串只有一种含义。实现（`papermapping._lean_problems`
第 7 条 / `is_numeric_theorem_row` / `mapping_cells`）早已按新口径走，于是声明与实测分家：

| # | 声明位置 | 实现事实（`papermapping`） |
|---|---|---|
| D6 | `doc.write_mapping` summary 的凭据/附加义务两句 | 凭据按通道（有程序就填那份 `.py`，不要求 E 已签）；附加义务只压定理类行 |
| D7 | `rows[].lean_file` 描述 | 例子 / 实验的证明栏 ① 段是程序 ⇒ 那份 `.py` 就是凭据 |
| D8 | `rows[].numeric_evidence` 描述 | 只定理类行必填（`is_numeric_theorem_row`） |
| D9 | `rows[].exhaustion_note` 描述 | 同上 |
| D10 | `rows[].file` 描述 | 三档落点：理论 = 包内；数值定理 = 仓库根程序；例子/实验按通道 = 仓库根 |
| D11 | summary 的 `file` 那句 | 同上（三种，不是两种） |
| D12 | `doc.mapping_cells` 的 `returns` | 空串两种含义：通道为空；通道非空但这一档没有这一格 |

## 判据的读法（a–d）

- a：同一条判据既读「声明文本」（工具面注册的字符串）又读「`papermapping` 的实际
  判定」（`mapping_cells` 的 cells / sources / problems，`is_numeric_theorem_row`）——
  七处逐条对齐。事实只有一份：`doc_tools.MAPPING_DECLARATION_FACTS`，声明文案由
  `doc_tools._mapping_declaration_texts()` 从它渲染，本判据从 `papermapping` 现测期望值。
- b（正控）：example / experiment + 证明栏 ① 段是程序 ⇒ 声明说「填那份 `.py` 就齐」，
  实测 `mapping_cells` 也说齐（`ok=True`、`lean_file` 就是那份程序）。
- c：定理类行缺 `numeric_evidence`（或 `exhaustion_note`）⇒ 仍然 fail —— 附加义务
  没被放宽；同一现场换成 example / experiment ⇒ 不要求那几格（档位边界两侧都核）。
- d（反真空）：把事实源改一处再渲染 ⇒ 对应的那一条判据必须红。四个变异分别打在
  凭据签名开关、附加义务档位、`file` 落点、空串含义上。

不许两边各写一份字面量：声明与判据都读 `MAPPING_DECLARATION_FACTS` / 现测行为；
本文件里出现的字符串只用于「读声明」与「比对行为」，不复制一份事实清单。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Mapping

PROJECT = pathlib.Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
for _entry in (SRC, PROJECT / "tests"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

import pytest  # noqa: E402

import test_mapping_three_known_gaps as GAPS  # noqa: E402
import test_numeric_theorem_writing_spec as SPEC  # noqa: E402
from agentflow import papermapping as PM  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402
from agentflow.tools import doc_tools as DT  # noqa: E402


# ============================================================ 读声明（唯一注册面）

def _registered_texts() -> dict[str, str]:
    """工具面注册的那七处声明文本（判据读的就是调用方真正看到的那一份）。"""
    registry = build_registry().registry
    write_mapping = registry.get("doc.write_mapping")
    cells = registry.get("doc.mapping_cells")
    props = write_mapping.params["properties"]["rows"]["items"]["properties"]
    return {
        "summary": write_mapping.summary,
        "file": props["file"]["description"],
        "lean_file": props["lean_file"]["description"],
        "numeric_evidence": props["numeric_evidence"]["description"],
        "exhaustion_note": props["exhaustion_note"]["description"],
        "returns": write_mapping.returns,
        "mapping_cells_returns": cells.returns,
    }


def _rendered_texts(facts: Mapping[str, Any] | None = None) -> dict[str, str]:
    """从事实源渲染同一组声明（判据用它证明「改一处事实 ⇒ 声明与实测分家」）。"""
    return DT._mapping_declaration_texts(facts)


# ============================================================ 读实测（papermapping）

def _cells(root: pathlib.Path) -> dict[str, Any]:
    return PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)


def _table_from_cells(cells: Mapping[str, Any]) -> dict[str, str]:
    """从 `cells` / `sources` 读「空串」落在哪一种含义上（判据不自己定义含义）。"""
    out: dict[str, str] = {}
    for name, value in (cells.get("cells") or {}).items():
        if value != "":
            continue
        source = str((cells.get("sources") or {}).get(name) or "")
        out[name] = ("empty_channel" if "通道为空" in source
                     else "tier_not_present" if "不适用" in source else "?")
    return out


def _landing(cells: Mapping[str, Any]) -> str:
    """`file` 那一格的落点：包内相对 / 仓库根相对（读 `sources` 的原话）。"""
    source = str((cells.get("sources") or {}).get("file") or "")
    if "论文包内" in source:
        return "package"
    if "仓库根" in source:
        return "repo_root"
    return "?"


def _theorem_kinds(ledger: Mapping[str, Any]) -> set[str]:
    """现测「附加义务压在哪几类环境上」：逐类造一行，问 `is_numeric_theorem_row`。"""
    out: set[str] = set()
    for kind in PM.ENV_KINDS:
        parsed, problems = PM.parse_rows({"rows": [SPEC._row(kind=kind)]})
        assert not problems, problems
        if PM.is_numeric_theorem_row(parsed[0], ledger):
            out.add(kind)
    return out


# ============================================================ 现场（复用既有夹具）

def _ws_theorem(root: pathlib.Path) -> pathlib.Path:
    return SPEC._workspace(root, rows=[SPEC._row()], tex=SPEC.CLEAN_TEX)


def _ws_theorem_without(root: pathlib.Path, **over: Any) -> pathlib.Path:
    row = SPEC._row(**over)
    return SPEC._workspace(root, rows=[row], tex=SPEC.CLEAN_TEX)


def _ws_example(root: pathlib.Path, kind: str, experiment: str = "proof") -> pathlib.Path:
    return SPEC._workspace(
        root, rows=[GAPS._example_credential_only(kind)],
        tex=GAPS._example_tex(kind), experiment=experiment)


def _ws_empty_channel(root: pathlib.Path) -> pathlib.Path:
    row = SPEC._row(file="proofs/thm.tex", lean_file="", lean_target="",
                    numeric_evidence="", exhaustion_note="", evidence_kind="",
                    evidence_path="", evidence_sha256="", v_signature=None)
    return SPEC._workspace(root, rows=[row], tex=SPEC.CLEAN_TEX,
                           statement=GAPS.PROSE)


def _ws_empty_channel_with_credentials(root: pathlib.Path) -> pathlib.Path:
    row = SPEC._row(file="proofs/thm.tex", lean_file=GAPS.LEAN_REL,
                    lean_target=GAPS.LEAN_DECL, numeric_evidence="",
                    exhaustion_note="", evidence_kind="", evidence_path="",
                    evidence_sha256="", v_signature=None)
    got = SPEC._workspace(root, rows=[row], tex=SPEC.CLEAN_TEX,
                          statement=GAPS.PROSE)
    lean = got / GAPS.LEAN_REL
    lean.parent.mkdir(parents=True, exist_ok=True)
    lean.write_text(GAPS.LEAN_SRC, encoding="utf-8", newline="\n")
    return got


# ============================================================ a：七处逐条对齐

def _checks(root: pathlib.Path, texts: Mapping[str, str],
            facts: Mapping[str, Any]) -> dict[str, list[str]]:
    """七条判据的逐条读数（空 = 这一处声明与实测对齐）。"""
    out: dict[str, list[str]] = {f"D{i}": [] for i in range(6, 13)}
    summary = texts["summary"]

    # ---- 现场（每处判据读同一批实测现场）
    ws_thm = _ws_theorem(root / "theorem")
    ws_ex_signed = _ws_example(root / "example_signed", "example")
    ws_ex_unsigned = _ws_example(root / "example_unsigned", "example",
                                 experiment="cross_check")
    ws_empty = _ws_empty_channel(root / "empty")
    ws_blank = _ws_empty_channel_with_credentials(root / "blank")
    ws_no_ne = _ws_theorem_without(
        root / "theorem_no_ne",
        **GAPS._example_credential_only("theorem", label="thm:r34"))
    ws_no_note = _ws_theorem_without(root / "theorem_no_note", exhaustion_note="")
    ledger = PM.read_ledger_tables(ws_thm)
    cells_thm = _cells(ws_thm)
    cells_ex_signed = _cells(ws_ex_signed)
    cells_ex_unsigned = _cells(ws_ex_unsigned)
    cells_empty = _cells(ws_empty)
    cells_blank = _cells(ws_blank)
    cells_no_ne = _cells(ws_no_ne)
    cells_no_note = _cells(ws_no_note)

    # ---- D6：summary 的凭据 / 附加义务两句
    if DT._credential_sentence(facts) not in summary:
        out["D6"].append("summary 没有凭据按通道那一句（有程序就填那份 .py）")
    if DT._duty_sentence(facts) not in summary:
        out["D6"].append("summary 没有附加义务按档位那一句（只压定理类行）")

    # ---- D7：`lean_file` 描述 —— 例子/实验的程序凭据不要求 E 签成穷举
    lean_text = texts["lean_file"]
    if str(facts["credential_program_suffix"]) not in lean_text:
        out["D7"].append("lean_file 描述没写那份程序的后缀（.py）")
    if "相对仓库根" not in lean_text:
        out["D7"].append("lean_file 描述没写那份程序相对仓库根")
    if DT._signature_clause(facts) not in lean_text:
        out["D7"].append("lean_file 描述没写「E 签穷举」那半句的当前口径")
    accepted_unsigned = (bool(cells_ex_unsigned.get("ok"))
                         and str(cells_ex_unsigned.get("channel") or "") == ""
                         and (cells_ex_unsigned.get("cells") or {}).get("lean_file")
                         == SPEC.PROGRAM)
    if bool(facts["credential_requires_signature"]) != (not accepted_unsigned):
        out["D7"].append(
            "实测：例子 + 未签穷举的程序，mapping_cells 的凭据格"
            f"{'认' if accepted_unsigned else '不认'}那份 .py —— 事实源却说"
            f" credential_requires_signature={facts['credential_requires_signature']!r}")

    # ---- D8 / D9：两格的描述 + 档位边界
    actual_kinds = _theorem_kinds(ledger)
    if actual_kinds != set(facts["additional_duty_kinds"]):
        out["D8"].append(
            f"实测附加义务压在 {sorted(actual_kinds)} 上，事实源写的是 "
            f"{sorted(facts['additional_duty_kinds'])}")
    for kind in facts["additional_duty_kinds"]:
        if str(kind) not in texts["numeric_evidence"]:
            out["D8"].append(f"numeric_evidence 描述没点名定理类行 {kind!r}")
        if str(kind) not in texts["exhaustion_note"]:
            out["D9"].append(f"exhaustion_note 描述没点名定理类行 {kind!r}")
    if "定理类行" not in texts["numeric_evidence"]:
        out["D8"].append("numeric_evidence 描述没写「只定理类行」")
    if "定理类行" not in texts["exhaustion_note"]:
        out["D9"].append("exhaustion_note 描述没写「只定理类行」")
    if not any(item.get("cell") == "numeric_evidence"
               for item in (cells_no_ne.get("problems") or ())):
        out["D8"].append("实测：定理类行缺 numeric_evidence 却没被判出来（附加义务被放宽了）")
    if any(item.get("cell") == "numeric_evidence"
           for item in (cells_ex_signed.get("problems") or ())):
        out["D8"].append("实测：例子行被要求 numeric_evidence（档位被压到例子/实验上）")
    if not any(item.get("cell") == "exhaustion_note"
               for item in (cells_no_note.get("problems") or ())):
        out["D9"].append("实测：定理类行缺 exhaustion_note 却没被判出来")
    if any(item.get("cell") == "exhaustion_note"
           for item in (cells_ex_signed.get("problems") or ())):
        out["D9"].append("实测：例子行被要求 exhaustion_note")

    # ---- D10 / D11：`file` 三档落点（描述 + summary）
    actual_tiers = {
        "theory": _landing(cells_empty),
        "numeric_theorem": _landing(cells_thm),
        "example_by_channel": _landing(cells_ex_signed),
    }
    expected_tiers = {
        str(code): ("package" if "包内" in str(line) else "repo_root")
        for code, line in facts["file_tiers"]
    }
    if actual_tiers != expected_tiers:
        out["D10"].append(
            f"实测 file 落点 {actual_tiers}，事实源渲染出来的是 {expected_tiers}")
    for _, line in facts["file_tiers"]:
        if str(line) not in texts["file"]:
            out["D10"].append(f"file 描述缺落点 {line!r}")
    if DT._file_tiers_sentence(facts) not in summary:
        out["D11"].append("summary 没写 file 的落点那一句")

    # ---- D12：`cells` 空串的两种含义
    actual_meanings = set()
    for got in (cells_empty, cells_ex_signed):
        actual_meanings.update(_table_from_cells(got).values())
    actual_meanings.discard("?")
    expected_meanings = {
        "empty_channel" if "通道为空" in str(line) else "tier_not_present"
        for _, line in facts["empty_cell_meanings"]
    }
    if actual_meanings != expected_meanings:
        out["D12"].append(
            f"实测空串含义 {sorted(actual_meanings)}，事实源写的是 "
            f"{sorted(expected_meanings)}")
    if DT._empty_cells_sentence(facts) not in texts["mapping_cells_returns"]:
        out["D12"].append("doc.mapping_cells 的 returns 没写空串的两种含义")
    for _, line in facts["empty_cell_meanings"]:
        if str(line) not in texts["mapping_cells_returns"]:
            out["D12"].append(f"doc.mapping_cells 的 returns 缺含义 {line!r}")
    # 空通道的凭据两格必须空：实测拒了才与 empty_channel_requires_blank 同向。
    blank_refused = not bool(cells_blank.get("ok"))
    if bool(facts["empty_channel_requires_blank"]) != blank_refused:
        out["D12"].append(
            "实测：空通道 + 凭据两格非空 "
            f"{'被拒' if blank_refused else '没被拒'}，事实源写的是 "
            f"empty_channel_requires_blank={facts['empty_channel_requires_blank']!r}")
    return out


def test_a_every_declaration_point_is_checked_against_papermapping(
        tmp_path: pathlib.Path) -> None:
    """a：七处声明逐条对齐（既读声明文本，也读 `papermapping` 的实际判定）。"""
    problems = _checks(tmp_path, _registered_texts(), DT.MAPPING_DECLARATION_FACTS)
    bad = {name: items for name, items in problems.items() if items}
    assert not bad, "\n".join(f"[{name}] {one}" for name, items in bad.items()
                              for one in items)


def test_the_registered_text_is_rendered_from_the_one_fact_source() -> None:
    """a 的附带：注册面那七段必须就是事实源渲染出来的那一份（不许两处各写一套）。"""
    registered = _registered_texts()
    rendered = _rendered_texts()
    bad = [name for name in rendered if registered.get(name) != rendered[name]]
    assert not bad, f"这些声明不是从 MAPPING_DECLARATION_FACTS 渲染的：{bad}"


# ============================================================ b：正控（声明说齐、实测也齐）

@pytest.mark.parametrize("kind", ["example", "experiment"])
@pytest.mark.parametrize("experiment", ["proof", "cross_check"])
def test_b_an_example_with_a_program_is_accepted_and_the_declaration_says_so(
        tmp_path: pathlib.Path, kind: str, experiment: str) -> None:
    """b：example / experiment + 证明栏 ① 段是程序 ⇒ 填那份 `.py` 就齐（签没签穷举都算）。

    「签了」与「没签」都测：`proof` 是 E 已签的穷举（`proof_channel == numeric`），
    `cross_check` 是还没签（`proof_channel == ""`）—— 两种现场凭据格都必须是那份 `.py`。
    """
    root = _ws_example(tmp_path / "ws", kind, experiment=experiment)
    cells = _cells(root)
    assert cells["ok"] is True, cells["problems"]
    assert cells["cells"]["lean_file"] == SPEC.PROGRAM, cells["cells"]
    assert cells["cells"]["lean_target"] == "", cells["cells"]
    # 声明那一侧读的是同一份事实：有程序就填那份 `.py`，且不要求 E 已签穷举。
    texts = _registered_texts()
    assert str(DT.MAPPING_DECLARATION_FACTS["credential_program_suffix"]) in \
        texts["lean_file"]
    assert DT._signature_clause() in texts["lean_file"]
    assert DT._credential_sentence() in texts["summary"]


# ============================================================ c：定理类行仍要附加义务

@pytest.mark.parametrize("kind", ["theorem", "lemma", "proposition", "corollary"])
def test_c_a_theorem_class_row_without_numeric_evidence_still_fails(
        tmp_path: pathlib.Path, kind: str) -> None:
    """c：定理类行缺 `numeric_evidence` ⇒ 仍然 fail（附加义务没被放宽）。"""
    row = GAPS._example_credential_only(kind, label="thm:r34")
    root = SPEC._workspace(tmp_path / "ws", rows=[row], tex=SPEC.CLEAN_TEX)
    cells = _cells(root)
    assert cells["ok"] is False, cells
    assert any(item.get("cell") == "numeric_evidence"
               for item in cells["problems"]), cells["problems"]


def test_c_an_example_without_numeric_evidence_is_not_required(
        tmp_path: pathlib.Path) -> None:
    """c 的另一侧：同一现场换成例子 ⇒ 不要求那几格（档位边界不是「一律不要求」）。"""
    root = _ws_example(tmp_path / "ws", "example")
    cells = _cells(root)
    assert cells["ok"] is True, cells["problems"]
    assert not any(item.get("cell") == "numeric_evidence"
                   for item in cells["problems"]), cells["problems"]


# ============================================================ d：反真空（改事实源一处 ⇒ 红）

@pytest.mark.parametrize("key,expected", [
    ("credential_requires_signature", "D7"),
    ("additional_duty_kinds", "D8"),
    ("file_tiers", "D10"),
    ("empty_cell_meanings", "D12"),
])
def test_d_changing_one_fact_turns_the_criterion_red(
        tmp_path: pathlib.Path, key: str, expected: str) -> None:
    """d：把事实源改一处、按它重新渲染 ⇒ 对应那一条判据必须红。

    这不是「跑一遍绿的就收工」：变异打在声明与判据共用的那一份事实上，判据读的
    `papermapping` 实测不动 ⇒ 两边分家必须被看见。
    """
    facts = dict(DT.MAPPING_DECLARATION_FACTS)
    if key == "credential_requires_signature":
        facts[key] = True
    elif key == "additional_duty_kinds":
        facts[key] = tuple(facts[key]) + ("example",)
    elif key == "file_tiers":
        facts[key] = tuple(facts[key])[:-1]
    else:
        facts[key] = tuple(facts[key])[:-1]
    problems = _checks(tmp_path, _rendered_texts(facts), facts)
    assert problems[expected], (
        f"把事实源 {key} 改成 {facts[key]!r} 后，{expected} 仍然全绿 ⇒ "
        "这一条判据没有真的读那一份事实")
