# -*- coding: utf-8 -*-
"""三条已知缝隙：同一张表两个答案 / 空通道的自称 / 空通道的凭据（先红后绿）。

业主 2026-11-04：「未修项倒是修啊」。三条缝的共同形态是「同一条判据长出两个答案」：

| # | 现场 | 改前的两个答案 |
|---|---|---|
| 一 | `kind="example"`、台账那条命题的证明栏是程序（`proof_channel == numeric`） | 收工门读数按通道要 `numeric_evidence` / `exhaustion_note` / 索引四格 ⇒ `complete=0`；`mapping_reading` 被 `is_numeric_row` 的 kind 门挡住 ⇒ `state=pass` |
| 二 | 空通道（证明栏是散文）而 `numeric_evidence` 有值 | `mapping_reading` 按"这一行自己填了数值那两格"跑去判数值证明 ⇒ 报 `mapping_proof_program_missing`；收工门读数按空通道只数 `file` ⇒ 报齐（一边报一边不报） |
| 三 | 空通道却填了合法 `.lean` + 真实声明名 | `_lean_problems` 说「无问题」⇒ 两边都报齐（凭据格说"这条命题百分百为真"，可是这一行没有任何证明通道） |

## 修法（判据侧只有一处）

- `papermapping._numeric_row_reading` 是"这一行算不算数值定理"的唯一读法：通道一律问
  `numericproof.proof_channel`（经 `_credential_slot`），`kind` 不参与；通道判不出来
  （程序还没被 E 签成穷举）时用 `numerictheorem.is_program_proof` 兜底 —— 那条兜底
  只决定"按哪一支判"，不决定凭据格该不该填。
- 空通道而 `numeric_evidence` / `exhaustion_note` 有值 ⇒ `mapping_numeric_evidence_missing`
  （`_lean_problems` 第 6 条）：两边同时报，不再一边报一边不报。
- 空通道而凭据格填了任一格 ⇒ `mapping_lean_file_missing`（`_lean_problems` 第 5 条）：
  「这一行没有证明通道 ⇒ 凭据格不许填，填了就是无依据的声称」。收工门读数只调
  `_lean_problems`，没有第二套。

## 这一组守 a–d（e/f 是静态面与回归面，读数见报告）

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | example + numeric 通道：缺 `numeric_evidence` ⇒ 两边都不齐；补齐 ⇒ 两边都齐 | 改前一个 `complete=0`、一个 `pass` |
| b | 空通道 + `numeric_evidence`/`exhaustion_note` 有值 ⇒ 两边同时报「没有数值证明通道」 | 改前一边 `mapping_proof_program_missing`、一边齐 |
| c | 空通道 + 合法 `.lean` + 真声明名 ⇒ 两边都不齐，点名「凭据格不许填」 | 改前两边都齐、`_lean_problems` 说无问题 |
| d | 把各自的修法摘掉（打桩/过滤）⇒ a/b/c 各回红 | 打桩前它们本来是绿的 —— 证明绿真的靠那几处判据 |

夹具复用 `test_numeric_theorem_writing_spec` 的构造器（同一个仓库里只留一份形状）。
"""
from __future__ import annotations

import pathlib
import re
import sys

PROJECT = pathlib.Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

import test_numeric_theorem_writing_spec as SPEC  # noqa: E402
from agentflow import closing as CL  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import papermapping as PM  # noqa: E402

#: 空通道那一行的正文证明（散文：不是程序，台账里也没有 E 签的穷举）。
PROSE = "对 n 作归纳：基例 n = 0 两端同为 0；归纳步提出公因式 (n + 1)^2 即得。"
#: 形式化那一份 Lean 源码（项目根相对：L 的真实落点 `code/formal/`）。
LEAN_REL = "code/formal/000004.lean"
LEAN_DECL = "free_group_factor_is_ii1"
LEAN_SRC = ("namespace FreeGroupFactor\n\n"
            "theorem free_group_factor_is_ii1 : True := trivial\n\n"
            "end FreeGroupFactor\n")


def _example_tex() -> str:
    """把正文那一条环境换成 `example`（label 不变）—— 现场是"例子环境里的数值定理"。"""
    return (SPEC.CLEAN_TEX
            .replace("\\begin{theorem}\\label{thm:r34}",
                     "\\begin{example}\\label{ex:r34}")
            .replace("\\end{theorem}", "\\end{example}"))


def _package_file(root: pathlib.Path, rel: str, body: bytes = b"proof\n") -> None:
    path = PM.package_dir(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _reading(root: pathlib.Path) -> tuple[dict, dict]:
    """同一现场的两份读数：`mapping_reading` 与收工门那一格（`paper_mapping_cell_reading`）。"""
    return PM.mapping_reading(root), CL.paper_mapping_cell_reading(root, workspace_root=root)


def _kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("problems") or ()]


def _details(reading: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in reading.get("problems") or ())


def _incomplete(got: dict) -> dict:
    assert got["incomplete"], f"收工门读数没有点名任何一行：{got}"
    return got["incomplete"][0]


def _numeric_row_missing_evidence() -> dict:
    """缝隙一的现场：numeric 通道、只缺 `numeric_evidence` 那一格。"""
    return SPEC._row(kind="example", label="ex:r34", numeric_evidence="")


def _empty_channel_with_numeric_claim(**over: object) -> dict:
    """缝隙二的现场：空通道，行自称有数值证据；`over` 用来换哪一格在自称。"""
    row = SPEC._row(file="proofs/thm.tex", numeric_evidence="exp:000000",
                    exhaustion_note="", lean_file="", lean_target="",
                    evidence_kind="", evidence_path="", evidence_sha256="",
                    v_signature=None)
    row.update(over)
    return row


def _empty_channel_with_credentials(**over: object) -> dict:
    """缝隙三的现场：空通道，凭据两格填了合法 `.lean` + 源码里真有的声明名。"""
    row = SPEC._row(file="proofs/thm.tex", lean_file=LEAN_REL, lean_target=LEAN_DECL,
                    numeric_evidence="", exhaustion_note="",
                    evidence_kind="", evidence_path="", evidence_sha256="",
                    v_signature=None)
    row.update(over)
    return row


def _empty_channel_ws(root: pathlib.Path, row: dict) -> pathlib.Path:
    """空通道的工作区：台账里那条命题的证明栏是散文，包里有一份 `proofs/thm.tex`。"""
    root = SPEC._workspace(root, rows=[row], statement=PROSE)
    _package_file(root, "proofs/thm.tex")
    return root


# ============================================================ a 缝隙一：kind 门

def test_a_an_example_row_with_a_numeric_channel_gets_one_answer(
        tmp_path: pathlib.Path) -> None:
    """a：`kind="example"` + numeric 通道 ⇒ 两份读数同一个结论（改前一个齐、一个 pass）。"""
    root = SPEC._workspace(tmp_path / "ws", rows=[_numeric_row_missing_evidence()],
                           tex=_example_tex())
    # 证明栏那份程序在论文包里也放一份：改前 kind 门让它走"包内文件"那一支，
    # 不放这一份，红色会被 `mapping_file_missing` 遮住，看不见"两个答案"。
    _package_file(root, SPEC.PROGRAM, b"print('exhaustive search')\n")

    paper, gate = _reading(root)
    one = _incomplete(gate)
    assert one["channel"] == NP.PROOF_CHANNEL_NUMERIC, gate
    assert "numeric_evidence" in one["missing"], gate
    assert gate["complete"] == 0, gate
    # 另一半（改前是 `pass`）：判据侧也必须按通道把这一行当数值定理判。
    assert paper["state"] == "fail", paper["reason"]
    assert "mapping_numeric_evidence_missing" in _kinds(paper), _details(paper)

    # 负控：把那一格补上 ⇒ 两边同时齐（不是"见 example 就拒"）。
    ok = SPEC._workspace(tmp_path / "ok", rows=[SPEC._row(kind="example",
                                                         label="ex:r34")],
                         tex=_example_tex())
    _package_file(ok, SPEC.PROGRAM, b"print('exhaustive search')\n")
    paper2, gate2 = _reading(ok)
    assert gate2["complete"] == 1 and gate2["incomplete"] == [], gate2
    assert paper2["state"] == "pass", _details(paper2)


# ============================================================ b 缝隙二：空通道的自称

def test_b_an_empty_channel_row_that_claims_numeric_evidence_is_reported_by_both(
        tmp_path: pathlib.Path) -> None:
    """b：空通道 + `numeric_evidence` 有值 ⇒ 两边同时报「没有数值证明通道」（改前一边报）。"""
    root = _empty_channel_ws(tmp_path / "ws", _empty_channel_with_numeric_claim())

    paper, gate = _reading(root)
    assert paper["state"] == "fail", paper["reason"]
    assert "mapping_numeric_evidence_missing" in _kinds(paper), _details(paper)
    detail = _details(paper)
    assert "自称有数值证据" in detail and "没有数值证明通道" in detail, detail
    one = _incomplete(gate)
    assert one["channel"] == "", gate
    assert gate["complete"] == 0, gate
    # 收工门读数的原话必须是同一句（它只转发 `_lean_problems`，不另写一套）。
    assert one.get("problems"), gate
    assert any("自称有数值证据" in text and "没有数值证明通道" in text
               for text in one["problems"]), one

    # 负控：把那一格清空 ⇒ 空通道 + 两格空 + 无数值自称 ⇒ 两边同时齐。
    clean = _empty_channel_ws(tmp_path / "clean", SPEC._row(
        file="proofs/thm.tex", numeric_evidence="", exhaustion_note="",
        lean_file="", lean_target=""))
    paper2, gate2 = _reading(clean)
    assert gate2["complete"] == 1, gate2
    assert paper2["state"] == "pass", _details(paper2)

    # 反方向：`exhaustion_note`（E 的两块读数）也算"自称有数值证据"——
    # 旧 `is_numeric_row` 认这两格，修后不许只剩一格在管。
    note = _empty_channel_ws(tmp_path / "note", _empty_channel_with_numeric_claim(
        numeric_evidence="", exhaustion_note=SPEC.NOTE))
    paper3, gate3 = _reading(note)
    assert "mapping_numeric_evidence_missing" in _kinds(paper3), _details(paper3)
    assert gate3["complete"] == 0, gate3


# ============================================================ c 缝隙三：空通道的凭据

def test_c_an_empty_channel_row_may_not_fill_the_credential_cells(
        tmp_path: pathlib.Path) -> None:
    """c：空通道 + 合法 `.lean` + 真声明名 ⇒ 两边都不齐（改前两边都齐）。"""
    root = _empty_channel_ws(tmp_path / "ws", _empty_channel_with_credentials())
    lean = root / LEAN_REL
    lean.parent.mkdir(parents=True, exist_ok=True)
    lean.write_text(LEAN_SRC, encoding="utf-8", newline="\n")

    paper, gate = _reading(root)
    assert paper["state"] == "fail", paper["reason"]
    assert _kinds(paper) == ["mapping_lean_file_missing"], _details(paper)
    detail = _details(paper)
    for needle in ("没有证明通道", "凭据格不许填，填了就是无依据的声称", "类别与通道不一致"):
        assert needle in detail, (needle, detail)
    one = _incomplete(gate)
    assert one["channel"] == "", gate
    assert gate["complete"] == 0, gate
    assert one["missing"] == ["通道为空却填了 lean_file", "通道为空却填了 lean_target"], one
    assert any("凭据格不许填，填了就是无依据的声称" in text
               for text in one.get("problems") or ()), one

    # 只填一格也要被点名到"填了的那一格"（不许把 lean_target 的多填读成 lean_file 的缺）。
    only_target = _empty_channel_ws(tmp_path / "target",
                                    _empty_channel_with_credentials(lean_file=""))
    paper2, gate2 = _reading(only_target)
    assert "mapping_lean_file_missing" in _kinds(paper2), _details(paper2)
    assert _incomplete(gate2)["missing"] == ["通道为空却填了 lean_target"], gate2

    # 负控：两格都空 ⇒ 两边同时齐（"不适用"不是"缺"）。
    blank = _empty_channel_ws(tmp_path / "blank", SPEC._row(
        file="proofs/thm.tex", lean_file="", lean_target="",
        numeric_evidence="", exhaustion_note=""))
    paper3, gate3 = _reading(blank)
    assert gate3["complete"] == 1 and gate3["incomplete"] == [], gate3
    assert paper3["state"] == "pass", _details(paper3)


# ============================================================ d 反真空：摘掉修法各回红

def test_d1_putting_the_kind_gate_back_reopens_gap_one(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-a：把 `is_numeric_row` 换回改前的 kind 门 ⇒ 同一现场又变成"一个齐、一个 pass"。"""
    root = SPEC._workspace(tmp_path / "ws", rows=[_numeric_row_missing_evidence()],
                           tex=_example_tex())
    _package_file(root, SPEC.PROGRAM, b"print('exhaustive search')\n")
    before, _gate = _reading(root)
    assert before["state"] == "fail", _details(before)

    def _old_kind_gate(row, ledger, experiments=None):
        if row.kind not in PM.LEAN_TARGETED_KINDS:
            return False
        return PM._numeric_row_reading(row, ledger, experiments)["numeric"]

    monkeypatch.setattr(PM, "is_numeric_row", _old_kind_gate)
    after, gate = _reading(root)
    assert after["state"] == "pass", _details(after)
    assert gate["complete"] == 0, gate
    assert after["state"] != "fail" and gate["complete"] == 0


def test_d2_dropping_the_claim_check_reopens_gap_two(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-b：把 `_lean_problems` 摘空（那份自称判据只在它里面）⇒ 同一现场又报齐。"""
    root = _empty_channel_ws(tmp_path / "ws", _empty_channel_with_numeric_claim())
    assert _reading(root)[1]["complete"] == 0

    monkeypatch.setattr(PM, "_lean_problems", lambda *args, **kwargs: [])
    paper, gate = _reading(root)
    assert gate["incomplete"] == [] and gate["complete"] == 1, gate
    assert paper["state"] == "pass", _details(paper)


def test_d3_dropping_the_credential_refusal_reopens_gap_three(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-c：把空通道的凭据拒绝那一条滤掉 ⇒ 同一现场又两边都齐。"""
    root = _empty_channel_ws(tmp_path / "ws", _empty_channel_with_credentials())
    lean = root / LEAN_REL
    lean.parent.mkdir(parents=True, exist_ok=True)
    lean.write_text(LEAN_SRC, encoding="utf-8", newline="\n")
    assert _reading(root)[1]["complete"] == 0

    real = PM._lean_problems

    def _without_credential_refusal(*args, **kwargs):
        return [one for one in real(*args, **kwargs)
                if "凭据格不许填" not in str(one.get("detail") or "")]

    monkeypatch.setattr(PM, "_lean_problems", _without_credential_refusal)
    paper, gate = _reading(root)
    assert gate["incomplete"] == [] and gate["complete"] == 1, gate
    assert paper["state"] == "pass", _details(paper)


# ============================================================ e 判据只有一处（静态面）

def test_e_proof_channel_is_defined_once_and_kind_no_longer_votes() -> None:
    """e：`def proof_channel` 只有 `numericproof` 一处；`is_numeric_row` 里没有 kind 门。"""
    package = SRC / "agentflow"
    defs = sorted(
        str(path.relative_to(package)).replace("\\", "/")
        for path in package.rglob("*.py")
        if re.search(r"^\s*def proof_channel\(", path.read_text(encoding="utf-8"), re.M))
    assert defs == ["numericproof.py"], defs

    text = (package / "papermapping.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^def is_numeric_row\(", text, re.M)) == 1
    body = text.split("def is_numeric_row(", 1)[1].split("\ndef ", 1)[0]
    # 只核「代码」：docstring 里逐字引用改前那两条口径（说明"为什么删"），不算第二套判法。
    code = body.split('"""')[-1] if '"""' in body else body
    assert "_numeric_row_reading" in code, code
    for stale in ("LEAN_TARGETED_KINDS", "row.numeric_evidence", "row.exhaustion_note",
                  "ledger_row"):
        assert stale not in code, f"`is_numeric_row` 的代码里还留着改前那一套：{stale}"
    # 唯一读法里也只接线那两处判据，不自己判通道（同样只看代码）。
    reading = text.split("def _numeric_row_reading(", 1)[1].split("\ndef ", 1)[0]
    reading_code = reading.split('"""')[-1] if '"""' in reading else reading
    assert "NP.PROOF_CHANNEL_NUMERIC" in reading_code, reading_code
    assert "is_program_proof" in reading_code, reading_code
    assert "proof_column_script" not in reading_code, (
        "`_numeric_row_reading` 自己拿 proof_column_script 判通道 ⇒ 第二套判法")


# ============================================================ f 既有回归（读数在报告里）

REGRESSION_FILES: tuple[str, ...] = (
    "test_numeric_theorem_writing_spec.py",
    "test_d38_mapping_is_not_silently_missing.py",
    "test_d38_step2_paper_mapping_is_machine_judged.py",
    "test_lean_file_is_taught_by_channel.py",
    "test_closing_mapping_reads_by_channel.py",
    "test_g_mapping_rows_declare_the_papermapping_cells.py",
)


def test_f_the_named_regression_files_are_still_on_disk() -> None:
    """f：那五组既有回归还在盘上（它们的绿由 pytest 那一趟读数给，不在这里伪造）。"""
    missing = [name for name in REGRESSION_FILES
               if not (PROJECT / "tests" / name).is_file()]
    assert not missing, missing


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
