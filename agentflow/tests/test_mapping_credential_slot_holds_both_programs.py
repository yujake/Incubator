# -*- coding: utf-8 -*-
"""对应表那一格 = 「这条命题有机器核验过的凭据」：Lean 程序与数值证明程序共用一格。

业主 2026-11-04 的原话（逐字）：

> 「lean 和数值证明程序同用一格不会打架，这一格的功能就是说这个命题是百分百真的」

于是 `MAPPING.json` 行上的 `lean_file`（字段名不改：表头、解析、两份渲染产物照旧）不再
只收 Lean 源码：它收的是这一条命题的机器核验凭据，类别必须与这条命题的证明通道一致
（判据本体是 `numericproof.formal_slot`，本模块只接线，不另写一套口径）：

- 通道 `numeric`（证明栏第 ① 段是程序、且台账里有 E 签的那条穷举）⇒ 必填，且必须是
  证明栏第 ① 段那份程序（`norm_rel` 比）——一份 `.py`；
- 通道 `formal`（形式化）⇒ 仍必填 `.lean`（另带 `lean_target`）；
- 通道空（没有 `proof_text`、也没有穷举）⇒ 这一格允许为空：它说的是"不适用"，不是"没填"。

## 六条判据（a–f，逐条对应验收单）

a 数值通道 + 填证明栏那份 `.py` ⇒ 通过（改前红：那条 `.py` 不以 `.lean` 结尾，
  `mapping_lean_file_missing`）；
b 数值通道 + 填 `.lean` ⇒ 受控拒，且拒信说得出「类别与通道不一致」；
c Lean 通道 + 填 `.lean`（声明名真的在源码里）⇒ 通过（回归：这一档的现有判据不动）；
d Lean 通道 + 填 `.py` ⇒ 受控拒，同样说「类别与通道不一致」；
e 通道空（没有 `proof_text`、盘上却有 `.lean` 产物）⇒ 两格允许为空，不是错误
  （改前红：旧判据"盘上有 Lean 产物 ⇒ 定理行必须给两格"会把这一行判成
  `mapping_lean_missing` —— 那正是「某一格不适用也被当成没填」的形态）；
f 反真空：把 numeric 分支摘掉（把 `formal_slot` 打桩成"永不返回 numeric"）⇒ a 必须回到红，
  证明 a 的绿真的靠那个分支，而不是靠一段顺手写死的放行。

全部用例都在 `tmp_path` 下自建工作区，零模型调用、零网络。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import numericproof as NP
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.store import Store

# 数值定理那一套夹具（证明栏三段、E 签的穷举、两块读数、索引四格）只写了一份：
# 这里直接复用 `test_numeric_theorem_writing_spec` 的构建器，避免第二份口径。
import test_numeric_theorem_writing_spec as TN

#: 数值定理的证明栏第 ① 段那份程序（相对仓库根）。
PROGRAM = TN.PROGRAM

#: 形式化那一档的源码落点（相对项目根；`LEAN_ARTIFACT_DIRS` 里的 `code/formal`）。
LEAN_REL = "code/formal/000004.lean"

#: 那份 `.lean` 里字面出现的声明名（`lean_target` 要写它）。
LEAN_DECL = "FreeGroupFactor.isII1"

#: 声明写成带点的全名：判据认的是"这个名字真的出现在文件里"（词边界匹配）。
LEAN_SOURCE = "theorem " + LEAN_DECL + " : True := trivial\n"

#: 形式化通道那条命题（凭证是 `LEAN_REL` 那份源码）。
FORMAL_SID = S.format_id(11)
#: 形式化通道台账里那条形式化实验（`method="formal"` + `evidence_kind="proof"`）。
FORMAL_EID = S.format_id(20)
#: 空通道那条命题（没有证明栏、台账里也没有穷举/形式化实验）。
EMPTY_SID = S.format_id(12)

#: "一条定理 + 它的一段自然语言证明"的最小正文。
def _tex(label: str) -> str:
    return (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Main results}\n"
        "\\begin{theorem}\\label{" + label + "}\n"
        "一条定理。\n"
        "\\end{theorem}\n"
        "\\end{document}\n"
    )


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _workspace(root: pathlib.Path, *, statements: list[dict], experiments: list[dict],
               rows: list[dict], tex: str, lean: str | None = None) -> pathlib.Path:
    """造一个工作区：台账（statements / experiments）+ 正文 + 包内证明文件 + 可选 `.lean`。"""
    root = pathlib.Path(root)
    store = Store(root)
    store.init()
    for table, table_rows in (("statements", statements), ("experiments", experiments)):
        path = root / "data" / str(S.TABLES[table]["file"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["rows"] = [dict(row) for row in table_rows]
        _dump(path, doc)
    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / PM.PC.TEX_NAME).write_bytes(tex.encode("utf-8"))
    for rel in ("proofs/thm.tex",):
        target = package / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture\n")
    if lean:
        target = root / lean
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(LEAN_SOURCE.encode("utf-8"))
    PM.write_package(root, [PM.Row(**dict(r)) for r in rows])
    return root


def _row(ledger_id: str, label: str = "thm:main", **over) -> dict:
    """一行定理（`file` 是包内那份证明；凭据格由 `over` 决定填不填）。"""
    row = {
        "kind": "theorem", "label": label, "env_no": 1,
        "ledger_id": ledger_id, "proof_no": 1,
        "file": "proofs/thm.tex",
        "citation_loc_reason": "我方自产命题（判据夹具），没有外部引文",
    }
    row.update(over)
    return row


def _formal_ws(root: pathlib.Path, *, lean_file: str, lean_target: str = LEAN_DECL,
               lean_artifact: bool = True) -> pathlib.Path:
    """形式化通道的工作区：台账里有一条 `method="formal"` 的 proof 行，盘上有那份 `.lean`。"""
    statement = {
        "stmt_id": FORMAL_SID, "origin": "own_result", "kind": "theorem",
        "statement_text": "一条定理", "proof_text": "检查器验过（形式化）。",
    }
    experiment = {
        "experiment_id": FORMAL_EID, "method": NP.FORMAL_METHOD,
        "evidence_kind": "proof", "code_path": LEAN_REL,
        # 绑到这条命题（2026-11-05 起 formal 通道按命题号绑，谓词是
        # `evidencebits.formal_row_bound_to`；不绑的行不是这一条的凭据）。
        "claim_key": f"stmt:{FORMAL_SID}",
    }
    return _workspace(
        root, statements=[statement], experiments=[experiment],
        rows=[_row(f"stmt:{FORMAL_SID}", lean_file=lean_file, lean_target=lean_target)],
        tex=_tex("thm:main"), lean=LEAN_REL if lean_artifact else None)


def _empty_channel_ws(root: pathlib.Path) -> pathlib.Path:
    """空通道的工作区：没有 `proof_text`、没有穷举、没有形式化实验，盘上却有一份 `.lean`。

    盘上那份 `.lean` 是这一条的关键：旧判据"有 Lean 产物 ⇒ 定理行必须给两格"会因此把
    这一行判红，而空通道的意思恰恰是"这一格不适用"。
    """
    statement = {
        "stmt_id": EMPTY_SID, "origin": "own_result", "kind": "theorem",
        "statement_text": "一条定理", "proof_text": "",
    }
    return _workspace(
        root, statements=[statement], experiments=[],
        rows=[_row(f"stmt:{EMPTY_SID}")], tex=_tex("thm:main"), lean=LEAN_REL)


def _kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("problems") or []]


def _details(reading: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in reading.get("problems") or [])


# ---------------------------------------------------------------- a 数值通道 + .py

def test_a_a_numeric_channel_accepts_the_proof_columns_program(
        tmp_path: pathlib.Path) -> None:
    """a：数值通道 + 填证明栏第 ① 段那份 `.py` ⇒ 通过。

    改前红：旧判据只认 `.lean` 结尾，于是这份 `.py` 必然落 `mapping_lean_file_missing`
    —— 数值定理的凭据在对应表里根本没有合法落点。
    """
    root = TN._workspace(tmp_path / "ws", rows=[TN._row(lean_file=PROGRAM)])
    got = PM.mapping_reading(root)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]


# ---------------------------------------------------------------- b 数值通道 + .lean

def test_b_a_numeric_channel_refuses_a_lean_program(tmp_path: pathlib.Path) -> None:
    """b：数值通道 + 填 `.lean` ⇒ 受控拒，拒信说得出「类别与通道不一致」。"""
    root = TN._workspace(tmp_path / "ws",
                         rows=[TN._row(lean_file="code/formal/000004.lean")])
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_lean_file_missing" in _kinds(got), _details(got)
    detail = _details(got)
    assert "类别与通道不一致" in detail, detail
    assert "数值" in detail, detail


# ---------------------------------------------------------------- c Lean 通道 + .lean

def test_c_a_formal_channel_accepts_a_lean_program(tmp_path: pathlib.Path) -> None:
    """c：Lean 通道 + `.lean`（声明名真的在源码里）⇒ 通过（回归，这一档的判据不动）。

    负控也在这一条里：同一份工作区把两格留空 ⇒ `mapping_lean_missing`
    —— 形式化通道仍然是必填（"通道非空 ⇒ 要求"这一半没有被放宽）。
    """
    root = _formal_ws(tmp_path / "ws", lean_file=LEAN_REL)
    got = PM.mapping_reading(root)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]

    empty = _formal_ws(tmp_path / "empty", lean_file="", lean_target="")
    got2 = PM.mapping_reading(empty)
    assert got2["state"] == "fail", got2["reason"]
    assert "mapping_lean_missing" in _kinds(got2), _details(got2)


# ---------------------------------------------------------------- d Lean 通道 + .py

def test_d_a_formal_channel_refuses_a_numeric_program(tmp_path: pathlib.Path) -> None:
    """d：Lean 通道 + 填数值程序（`.py`）⇒ 受控拒，同样说「类别与通道不一致」。"""
    root = _formal_ws(tmp_path / "ws", lean_file=PROGRAM)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_lean_file_missing" in _kinds(got), _details(got)
    detail = _details(got)
    assert "类别与通道不一致" in detail, detail
    assert ".lean" in detail, detail


# ---------------------------------------------------------------- e 通道空

def test_e_an_empty_channel_leaves_the_cell_empty_without_an_error(
        tmp_path: pathlib.Path) -> None:
    """e：通道空 ⇒ 允许为空（不适用，不是错误）。

    盘上故意放着一份 `.lean`：旧判据会因此要求每条定理行都给两格（改前是红的），
    而"这一条命题没有机器核验通道"与"表漏填了一格"是两件事。
    """
    root = _empty_channel_ws(tmp_path / "ws")
    # 前提：盘上真的有 Lean 产物（否则这一条测的就不是"不适用"而是"没有产物"）。
    assert PM.lean_artifacts(root) == [LEAN_REL], PM.lean_artifacts(root)
    got = PM.mapping_reading(root)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]


# ---------------------------------------------------------------- f 反真空

def test_f_dropping_the_numeric_branch_turns_a_back_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f：把 numeric 分支摘掉 ⇒ a 必须回到红（a 的绿靠的是通道判据，不是顺手放行）。

    打桩只动"通道认不认得出 numeric"这一件：其余读数（签名、证明栏、索引四格）照旧。
    """
    root = TN._workspace(tmp_path / "ws", rows=[TN._row(lean_file=PROGRAM)])
    assert PM.mapping_reading(root)["problems"] == [], _details(PM.mapping_reading(root))

    real = NP.formal_slot

    def _without_numeric(statement, experiments=(), filled=""):
        got = real(statement, experiments, filled)
        if str(got.get("channel") or "") == NP.PROOF_CHANNEL_NUMERIC:
            return {"channel": "", "kind": "", "path": "", "problems": [],
                    "why": "反真空打桩：numeric 分支被摘掉"}
        return got

    monkeypatch.setattr(NP, "formal_slot", _without_numeric)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_lean_file_missing" in _kinds(got), _details(got)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
