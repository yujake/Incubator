# -*- coding: utf-8 -*-
"""判据：`formal` 通道按命题号绑定（沿 `evidencebits.formal_ledger_reading` 的四处绑定点）。

## 真身（手工走查 78c 发现的缺陷）

`numericproof.proof_channel` 的 formal 分支改前只筛 "台账里有没有一条
`method="formal"` + `evidence_kind="proof"` 的 `.lean` 行"，不看这一行绑到哪条命题：

    lean_rows = [r for r in experiments if r.method == "formal" ...]   # 没有绑定判断

于是 L 只给 `stmt:A` 记了一条 formal 实验（`claim_key="stmt:A"`），同一张表里别的散文
证明的命题 `stmt:B` 也被判成 formal 通道；`papermapping._lean_problems` 按"通道非空而
凭据格空"给 B 报 `mapping_lean_missing` —— 而 L 从未碰过 B。`numericproof.formal_slot`
的 formal 分支是同一处口径，还会把 A 的 `code/formal/t.lean` 当成 B 的凭据路径。

绑定的单一来源是 `evidencebits.formal_ledger_reading` 的四处：`params.statement_id` /
`observations.statement_id` / `claim_key` / `verifier_subject_key` 命中「这一条命题号」
（裸号或 `stmt:<号>`）。本文件钉的是"formal 通道复用它，而不是长出第五套判断"。

## 判据（a–e）

| # | 判据 | 它钉的是什么 |
|---|---|---|
| a | 只有绑到 A 的 formal 行 ⇒ `proof_channel(A)=="formal"`、`proof_channel(B)==""`、`formal_slot(B)` 不给 A 的路径 | 绑定真的按命题号 |
| b | `mapping_cells(B)` 的 `channel` 为空、两格是"不适用"，不报 `mapping_lean_missing` | 读侧没有假问题 |
| c | 整表 `doc.write_mapping` 的 problems 里没有 B 的 `mapping_lean_missing` | 写侧（整表）同一个答案 |
| d | 反真空：把绑定谓词打桩成恒 True ⇒ `proof_channel(B)` 立刻变 `"formal"` | 上面几条的红是绑定谓词给的，不是别的偶然 |
| e | A 的行仍读到 `lean_file` / `lean_target`（正控不丢） | 修绑定不许把真凭据也筛掉 |
"""
from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import evidencebits as EB       # noqa: E402
from agentflow import numericproof as NP       # noqa: E402
from agentflow import papermapping as PM       # noqa: E402
from agentflow import schema as S              # noqa: E402
from agentflow.store import Store              # noqa: E402
from agentflow.tools import build_registry     # noqa: E402

#: 两条命题：A 被 L 形式化过，B 没有（它的证明是散文）。
A = S.format_id(0)
B = S.format_id(5)
#: L 落的那份 Lean 源码与它验的声明名（相对项目根）。
LEAN = "code/formal/t.lean"
DECL = "t"
#: 两条命题的证明栏都是散文：通道只能来自台账里那一行 —— 这正是缺陷的现场。
PROSE = "证明：由谱定理逐项展开，三项估计与主项相消。"

#: 正文：两条定理各一个环境（labels 与对应表两行对上）。
TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Main results}\n"
    "\\begin{theorem}\\label{thm:A}\n"
    "第一条命题。\n"
    "\\end{theorem}\n"
    "\\begin{proof}\n"
    "由谱定理逐项展开。\n"
    "\\end{proof}\n"
    "\\begin{theorem}\\label{thm:B}\n"
    "第二条命题。\n"
    "\\end{theorem}\n"
    "\\begin{proof}\n"
    "由谱定理逐项展开。\n"
    "\\end{proof}\n"
    "\\end{document}\n"
)


def _statement(sid: str, label: str) -> dict:
    """台账里一条命题（散文证明；`bits` 与 `schema.Statement` 的形状一致）。"""
    return {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "statement_text": label, "statement_full": label,
        "proof_text": PROSE, "evidence_kind": "proof",
        "bits": {"numeric": "none", "formal": {}, "reviewed": "none",
                 "proof": "none", "audited": "none"},
        "status": "active",
    }


def _formal_row() -> dict:
    """L 记的那一条 formal 实验：只绑到 A（四处绑定点都指 A）。"""
    return {
        "experiment_id": S.format_id(10),
        "claim": f"thm:{A}",
        "claim_key": f"stmt:{A}",
        "method": "formal",
        "evidence_kind": "proof",
        "result": "supports",
        "code_path": LEAN,
        "code_hash": "234c88a4a77bad9e",
        "verifier_output": "'t' does not depend on any axioms",
        "verifier_subject_key": f"stmt:{A}",
        "observations": {"statement_id": A, "checker": "lean 4.7.0",
                         "tri_state": "checked_passed"},
        "params": {"statement_id": A},
    }


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2)
                      + "\n").encode("utf-8"))


def _scene(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个两命题的现场：台账两行、experiments 只有 A 的那条 formal 行、包里两行表。"""
    root = pathlib.Path(tmp_path) / "ws"
    store = Store(root)
    store.init()
    for table, rows in (("statements", [_statement(A, "thm:A"), _statement(B, "thm:B")]),
                        ("experiments", [_formal_row()])):
        path = root / "data" / str(S.TABLES[table]["file"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["rows"] = [dict(r) for r in rows]
        _dump(path, doc)
    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / "main.tex").write_bytes(TEX.encode("utf-8"))
    lean = root / LEAN
    lean.parent.mkdir(parents=True, exist_ok=True)
    lean.write_bytes(b"theorem t : (1:Nat) + 1 = 2 := rfl\n")
    rows = [_row_a(), _row_b()]
    PM.write_package(root, [PM.Row(**row) for row in rows])
    return root


def _row_a() -> dict:
    """A 的对应表行：formal 通道，凭据两格齐（L 落的那份 `.lean` 与它验的声明名）。"""
    return {"kind": "theorem", "label": "thm:A", "env_no": 1,
            "ledger_id": f"stmt:{A}", "proof_no": 1, "file": "main.tex",
            "lean_file": LEAN, "lean_target": DECL}


def _row_b() -> dict:
    """B 的对应表行：散文证明、没有 formal 行 ⇒ 凭据两格必须留空（L 没碰过它）。"""
    return {"kind": "theorem", "label": "thm:B", "env_no": 2,
            "ledger_id": f"stmt:{B}", "proof_no": 1, "file": "main.tex"}


def _lean_problems_of(reading: dict, label: str) -> list[dict]:
    """`mapping_reading` 的 problems 里落在这条 label 上的 `mapping_lean_*` 那几条。"""
    return [one for one in reading.get("problems") or ()
            if str(one.get("label") or "") == label
            and str(one.get("kind") or "").startswith("mapping_lean")]


# ============================================================ a 绑定按命题号

def test_a_only_the_bound_statement_has_a_formal_channel() -> None:
    """a：只有绑到 A 的 formal 行 ⇒ A 是 formal，B 没有通道，且不给 B 挂 A 的路径。"""
    experiments = [_formal_row()]
    a_stmt, b_stmt = _statement(A, "thm:A"), _statement(B, "thm:B")

    # 正控：A 的 formal 通道不许丢
    assert NP.proof_channel(a_stmt, experiments) == NP.PROOF_CHANNEL_FORMAL
    # 缺陷那一半：B 没有 formal 行 ⇒ 没有通道
    assert NP.proof_channel(b_stmt, experiments) == "", (
        "B 的证明栏是散文、台账里又没有绑到 B 的 formal 行，却读出了通道")
    # 空台账的既有读数不许变
    assert NP.proof_channel(b_stmt, []) == ""

    # `formal_slot(B)` 不许把 A 的源码当成 B 的凭据路径
    slot_b = NP.formal_slot(b_stmt, experiments)
    assert slot_b["channel"] == "" and slot_b["path"] == "", slot_b
    assert slot_b["kind"] == "", slot_b


# ============================================================ b 读侧：假问题

def test_b_mapping_cells_of_the_unbound_statement_has_no_fake_lean_gap(
        tmp_path: pathlib.Path) -> None:
    """b：`mapping_cells(B)` 通道为空、两格按"不适用"处理，不报 `mapping_lean_missing`。"""
    root = _scene(tmp_path)
    got = PM.mapping_cells(root, workspace_root=root, statement_id=B)

    assert got["checked"] is True, got
    assert got["channel"] == "", got["channel"]
    assert got["cells"]["lean_file"] == "" and got["cells"]["lean_target"] == "", got["cells"]
    assert "不适用" in got["sources"]["lean_file"], got["sources"]["lean_file"]
    # 两格不许有"缺凭据"那类假问题（空通道本来就不适用）
    lean_cells = [one for one in got["problems"] or ()
                  if str(one.get("cell") or "") in ("lean_file", "lean_target")]
    assert lean_cells == [], lean_cells


# ============================================================ c 写侧：整表

def test_c_the_whole_table_does_not_report_b_lean_missing(tmp_path: pathlib.Path) -> None:
    """c：整表 `doc.write_mapping` 的 problems 里不许出现 B 的 `mapping_lean_missing`。"""
    root = _scene(tmp_path)
    rows = [{name: row[name] for name in
             ("kind", "label", "env_no", "ledger_id", "proof_no", "file",
              "lean_file", "lean_target") if name in row}
            for row in (_row_a(), _row_b())]
    registry = build_registry(store=Store(root), workspace_root=root, roles=("G",)).registry
    res = registry.call("doc.write_mapping", role="G", project=".", rows=rows)
    # 失败时 tool 把逐条 problems 放在 `meta`（`data` 是空的），成功时放 `data` ——
    # 两处都读：这一条判的是"整表有没有报 B 的凭据缺口"，不是"这张表过没过门"。
    data = dict(res.data or {})
    problems = list((res.meta or {}).get("problems") or data.get("problems") or ())

    assert _lean_problems_of({"problems": problems}, "thm:B") == [], (
        f"B 没有 formal 行，整表却给它报了凭据缺口：{_lean_problems_of({'problems': problems}, 'thm:B')}")
    # 反真空的一半：A 那一行本来就有凭据，不许被这条判据顺带清掉
    assert _lean_problems_of({"problems": problems}, "thm:A") == [], problems


# ============================================================ d 反真空

def test_d_stubbing_the_binding_predicate_turns_b_back_to_formal(monkeypatch) -> None:
    """d：把绑定谓词打桩成恒 True ⇒ B 立刻又读成 formal（判据的红由它给）。"""
    # 反真空的前置：不打桩时它是空
    assert NP.proof_channel(_statement(B, "thm:B"), [_formal_row()]) == ""

    monkeypatch.setattr(EB, "formal_row_bound_to", lambda experiment, statement: True)
    assert NP.proof_channel(_statement(B, "thm:B"), [_formal_row()]) == NP.PROOF_CHANNEL_FORMAL, (
        "绑定谓词被换成恒 True，B 却还不是 formal —— 说明 proof_channel 没走这个谓词"
        "（判据 a 的红就不是它给的）")
    # `formal_slot` 也必须走同一个谓词
    assert NP.formal_slot(_statement(B, "thm:B"), [_formal_row()])["path"] == LEAN


# ============================================================ e 正控：真凭据还在

def test_e_the_bound_row_still_reads_its_lean_file_and_target(tmp_path: pathlib.Path) -> None:
    """e：A 的行仍读到 `lean_file` / `lean_target`（修绑定不许把真凭据筛掉）。"""
    a_stmt, experiments = _statement(A, "thm:A"), [_formal_row()]
    slot = NP.formal_slot(a_stmt, experiments, filled=LEAN)
    assert (slot["channel"], slot["kind"], slot["path"]) == (
        NP.PROOF_CHANNEL_FORMAL, NP.FORMAL_SLOT_LEAN, LEAN), slot
    assert slot["problems"] == [], slot["problems"]

    root = _scene(tmp_path)
    got = PM.mapping_cells(root, workspace_root=root, statement_id=A)
    assert got["channel"] == NP.PROOF_CHANNEL_FORMAL, got["channel"]
    assert got["cells"]["lean_file"] == LEAN, got["cells"]
    assert got["cells"]["lean_target"] == DECL, got["cells"]
