# -*- coding: utf-8 -*-
"""判据：数值实验定理在正文里怎么写、在对应表里怎么登记（业主 2026-10-23，E-1）。

业主原话（逐字）：「请给 G 立规范如何在正文写纯数值实验跑出的定理，且搞好对应表。G 在落
数值实验证出的定理时应该写明程序设计思路以及确实穷举的论证」；「这个可以当数值实验定理的
证明栏」；随后补一条硬口径：「数值实验定理的证明栏三部分：① 程序相对地址 ② 程序设计
③ 穷举论证。作者：② 与 ③ 都由 E 写；G 在正文里必须原样引用 E 的那两块（可压缩措辞，
但不许改写实质、不许把 E 的读数变成『我们认为』），并在正文里标出它们来自 E 的那条读数
（引用编号/路径）。E 没给 ⇒ G 不许把这写成『定理/已证明』，只能写『有数值实验支持』，
并点名缺哪一块」。

## 这一组守七条

1. G 渲染出来的提示词里能逐字读到那三块要求（Lean 开 / 关两档都测）：
   程序设计思路、穷举论证、程序地址（相对仓库）＋运行环境，以及「这三块合起来就是证明栏」
   与「不完全的只能说有数值实验支持、不许写成定理」；
2. 一条数值实验定理的对应表行，证明栏（`file`）必须是相对仓库的程序路径；缺程序路径 =>
   判据红（`mapping_proof_program_missing`）；
3. 缺「程序设计思路」或缺「穷举论证」=> G 落库那一步受控拒绝（`mapping_exhaustion_note_missing`），
   不许静默通过；
4. 负控：不完全的实验（E 没签成穷举 proof）被写成「定理」=> 受控拒绝
   （`mapping_proof_program_unbacked`），只能记成「有数值实验支持」；
5. 反真空：把「三块齐全」判定打桩成恒真 => 第 3 条必红（缺块的行被放行）；
6. 正文里那一段能指回 E 的那两块读数（引用编号或程序路径在其中）；指不回 =>
   判据红（`mapping_numeric_citation_missing`）；
7. 负控：正文把 E 的那两块改写成一段无出处的叙述 => 判据红（要求带出处）。

全部用例都在 `tmp_path` 里自建工作区，一个模型调用都不发。
"""
from __future__ import annotations

import json
import hashlib
import os
import pathlib

import pytest

from agentflow import agent_prompts as AP
from agentflow import exhaustionreport as ER
from agentflow import numerictheorem as NT
from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.settings import ENV_LEAN_ENABLED
from agentflow.store import Store
from agentflow.tools import build_registry

#: 那条穷举证明的程序（相对仓库根 = 工作区根）。
PROGRAM = "code/r34_check.py"
#: E 写的那两块读数的落点（相对仓库根）。
NOTE = "out/experiments/000000/exhaustion.md"
#: E 的那条穷举读数（台账里 `experiments` 的编号，写着就是 `exp:000000`）。
EID = S.format_id(0)
#: 那条命题（`statements` 的编号）。
SID = S.format_id(0)

#: E 的两块读数 + 运行环境 + 署名：直接用 `exhaustionreport` 的合成函数（唯一格式）。
NOTE_TEXT = ER.compose_report(
    experiment_id=EID,
    claim="R(3,4) 的上界：K_9 的任意 2-着色必含红 K_3 或蓝 K_4",
    claim_key="r34-upper",
    script_path=PROGRAM,
    script_sha256="915a24d9f9d1d955",
    design="要解决 R(3,4) 的上界；按字典序逐边回溯、红/蓝两支；根对称性把红邻域折成前缀，"
           "所以每个同构类至少被走到一次，覆盖全域。",
    enumeration="搜索空间 2^36 = 68719476736；只按确定矛盾剪枝（红三角形、蓝 K_4 补全），"
                "所以不漏；n=9 时叶子 0 个；边界 n=8 的第一个见证单独记在 code/r34_orbits.py。",
    search_space={"n": 9, "raw_colourings": 68719476736,
                  "search_space": "2^36 colourings of E(K_9)"},
    environment="python 3.12.4，无随机种子（确定性 DFS），运行时 0.125 s",
    result="supports", evidence_kind="proof")

#: E 写的那条命题的三段式证明栏（① 程序、② 程序设计、③ 穷举论证）。
PROOF_COLUMN = (
    f"程序：{PROGRAM}\n"
    "程序设计：要解决 R(3,4) 的上界；按字典序逐边回溯、红/蓝两支；"
    "根对称性把红邻域折成前缀，覆盖全域。\n"
    "穷举论证：搜索空间 2^36 = 68719476736；只按确定矛盾剪枝所以不漏；n=9 时叶子 0 个。"
)

#: V 签下、E 写 ②③ 的那条穷举实验（`observations.e_signature` 是签名）。
SIGNED_SIGNATURE = {"signed_by": "V", "proof_authors": ["E"], "method": "exhaustive_search",
                    "evidence_kind": "proof", "proof_reason": "exhaustion",
                    "script_path": PROGRAM, "script_sha256": "915a24d9f9d1d955",
                    "proof_text": PROOF_COLUMN,
                    "design": "按字典序逐边回溯，根对称性把红邻域折成前缀",
                    "enumeration": "搜索空间 2^36，只按确定矛盾剪枝，所以不漏"}

#: 正文：一条数值实验定理 + 它的证明（证明里指回 E 的那条读数与那份程序）。
CLEAN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Main results}\n"
    "\\begin{theorem}\\label{thm:r34}\n"
    "R(3,4) = 9.\n"
    "\\end{theorem}\n"
    "\\begin{proof}\n"
    "The upper bound is E's exhaustion of all 2^36 colourings of $K_9$, whose program is\n"
    "\\texttt{code/r34\\_check.py} and whose reading is \\texttt{exp:000000} (Appendix A).\n"
    "\\end{proof}\n"
    "\\end{document}\n"
)

#: 第 7 条那一档：两块改写成无出处的叙述（叙述完整，一个出处都没有）。
UNCITED_TEX = CLEAN_TEX.replace(
    "The upper bound is E's exhaustion of all 2^36 colourings of $K_9$, whose program is\n"
    "\\texttt{code/r34\\_check.py} and whose reading is \\texttt{exp:000000} (Appendix A).",
    "We enumerate all 2^36 colourings of $K_9$ with a lexicographic DFS and a sound\n"
    "symmetry quotient, so the search covers the whole space and no colouring survives.")


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _experiment(*, kind: str = "proof") -> dict:
    """一条 E 的实验行；`kind="cross_check"` 那一档是"不完全的实验"。"""
    sig = dict(SIGNED_SIGNATURE)
    if kind != "proof":
        sig = {"signed_by": "", "proof_authors": ["E"], "method": "exhaustive_search",
               "evidence_kind": kind, "proof_reason": "",
               "script_path": "", "script_sha256": "b20b5063a2e6eaab"}
    return {
        "experiment_id": EID,
        "claim": "R(3,4) 的上界：K_9 的任意 2-着色必含红 K_3 或蓝 K_4",
        "claim_key": "r34-upper",
        "method": "exhaustive_search",
        "evidence_kind": kind,
        "result": "supports",
        "code_path": PROGRAM,
        "code_hash": "915a24d9f9d1d955",
        "search_bound": {"n": 9, "raw_colourings": 68719476736,
                         "exhaustive": True,
                         "search_space": "2^36 colourings of E(K_9)",
                         "design": "按字典序逐边回溯，根对称性把红邻域折成前缀",
                         "enumeration": "搜索空间 2^36，只按确定矛盾剪枝，所以不漏"},
        "observations": {"exhaustive": True,
                         "design": "按字典序逐边回溯，根对称性把红邻域折成前缀",
                         "enumeration": "搜索空间 2^36，只按确定矛盾剪枝，所以不漏",
                         "search_space": "2^36 colourings of E(K_9)",
                         "e_signature": sig},
    }


def _statement(*, proof_text: str = PROOF_COLUMN) -> dict:
    return {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "statement_text": "R(3,4) = 9", "statement_full": "R(3,4) = 9（K_9 上界 + K_8 见证）",
        "proof_text": proof_text, "evidence_kind": "proof",
        "bits": {"numeric": "signed", "formal": {}, "reviewed": "none",
                 "proof": "signed", "audited": "none"},
        "status": "active",
    }


def _row(**over) -> dict:
    """对应表那一行（数值实验定理：证明栏是程序路径，另带 E 读数与两块落点）。

    D-34 起还带索引四格（业主 2026-10-23 夜：D 的报告是目录）：
    `evidence_kind` / `evidence_path` / `evidence_sha256` / `v_signature` —— 四格指的就是
    `NOTE` 那一份读数的字节与 V 签的那一版，所以按 `NOTE_TEXT` 现算 sha256。
    """
    note_sha = hashlib.sha256(NOTE_TEXT.encode("utf-8")).hexdigest()
    row = {
        "kind": "theorem", "label": "thm:r34", "env_no": 1,
        "ledger_id": f"stmt:{SID}", "proof_no": 1,
        "file": PROGRAM,
        "numeric_evidence": f"exp:{EID}",
        "exhaustion_note": NOTE,
        "evidence_kind": "report",
        "evidence_path": NOTE,
        "evidence_sha256": note_sha,
        "v_signature": {"verdict": "成立", "sha256": note_sha},
        "citation_loc_reason": "我方自产命题（E 签的穷举证明），没有外部引文",
    }
    row.update(over)
    return row


def _workspace(root: pathlib.Path, *, rows: list[dict] | None = None,
               tex: str = CLEAN_TEX, note: str | None = NOTE_TEXT,
               experiment: str = "proof", statement: str = PROOF_COLUMN) -> pathlib.Path:
    """造一个工作区：台账 + 论文包 + 那份程序 + E 的两块读数。"""
    root = pathlib.Path(root)
    store = Store(root)
    store.init()
    for table, table_rows in (("statements", [_statement(proof_text=statement)]),
                              ("experiments", [_experiment(kind=experiment)])):
        path = root / "data" / str(S.TABLES[table]["file"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["rows"] = [dict(r) for r in table_rows]
        _dump(path, doc)
    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / PC.TEX_NAME).write_bytes(tex.encode("utf-8"))
    program = root / PROGRAM
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_bytes(b"print('exhaustive search')\n")
    if note is not None:
        target = root / NOTE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(note.encode("utf-8"))
    if rows is not None:
        PM.write_package(root, [PM.Row(**dict(r)) for r in rows])
    return root


def _kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("problems") or []]


def _details(reading: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in reading.get("problems") or [])


# ============================================================ 1. 提示词里读得到三块
#: 提示词里必须逐字出现的那些串（缺一条这一条判据就红）。
PROMPT_MUST_HAVE: tuple[str, ...] = (
    "程序设计思路",
    "穷举论证",
    "程序地址（相对仓库）",
    "这三块合起来就是该定理在论文里的证明栏",
    "有数值实验支持",
    "不许写成「定理」或「已证明」",
    "② 与 ③ 都由 E 写",
    "原样引用",
    "作者：E",
)

#: 渲染用的夹具读数（与 `tests/test_e_has_no_lean_memory_left.py` 同一套形状）。
_TASK = "整理成论文"
_ROOT = "D:/x"
_FACTS = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
          "- 检查器：（判据夹具，与机器无关）")
_FORMAL = ("你这一岗怎么写形式化（由上面那份读数现算）：\n"
           "- （判据夹具：这一次按自足文件写）")


def _render_g(registry, on: bool) -> str:
    """这一档下 G 的渲染提示词（生产形态：四格入参都传）。"""
    os.environ[ENV_LEAN_ENABLED] = "1" if on else "0"
    AP.reset_toolchain_readings()
    return AP.system_prompt("G", registry=registry, task=_TASK, workspace_root=_ROOT,
                            toolchain_facts=_FACTS, toolchain_formal=_FORMAL)


@pytest.fixture()
def two_tiers():
    """Lean 开 / 关两档下 G 的渲染（出夹具时把环境变量与读数缓存放回原值）。"""
    before = os.environ.get(ENV_LEAN_ENABLED)
    try:
        registry = build_registry().registry
        return {"on": _render_g(registry, True), "off": _render_g(registry, False)}
    finally:
        if before is None:
            os.environ.pop(ENV_LEAN_ENABLED, None)
        else:
            os.environ[ENV_LEAN_ENABLED] = before
        AP.reset_toolchain_readings()


def test_1_the_prompt_carries_the_three_blocks_in_both_tiers(two_tiers) -> None:
    """判据 1：G 的渲染提示词里逐字读到那三块（两档都测，缺一条就是红）。"""
    for tier, text in two_tiers.items():
        assert len(text) > 3000, f"[{tier}] G 的渲染只有 {len(text)} 字符 ⇒ 这一条是真空的"
        missing = [m for m in PROMPT_MUST_HAVE if m not in text]
        assert not missing, f"[{tier}] 提示词里读不到 {missing}"
    # 作者与三块的词表只有一份：提示词里的字面串就是 `numerictheorem` 的常量。
    assert NT.BLOCK_DESIGN in two_tiers["on"] and NT.BLOCK_EXHAUSTION in two_tiers["on"]
    assert NT.AUTHOR_MARKER in two_tiers["on"]
    assert NT.BLOCK_DESIGN in PROMPT_MUST_HAVE and NT.BLOCK_EXHAUSTION in PROMPT_MUST_HAVE


# ============================================================ 2. 证明栏是程序路径
def test_2_a_numeric_theorem_row_proves_by_a_program_path(tmp_path: pathlib.Path) -> None:
    """判据 2：干净那一条过；证明栏不是相对仓库的程序路径 => 红。"""
    ok_root = _workspace(tmp_path / "ok", rows=[_row()])
    got = PM.mapping_reading(ok_root)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]

    # 缺程序路径（证明栏写成论文包内的一份 tex）：必须是那一类红，且点名程序。
    root = _workspace(tmp_path / "no-program", rows=[_row(file="proofs/thm.tex")])
    (PM.package_dir(root) / "proofs").mkdir(parents=True, exist_ok=True)
    (PM.package_dir(root) / "proofs" / "thm.tex").write_bytes(b"proof\n")
    got2 = PM.mapping_reading(root)
    assert got2["state"] == "fail", got2["reason"]
    assert "mapping_proof_program_missing" in _kinds(got2), _details(got2)
    assert PROGRAM in _details(got2) or "程序" in _details(got2), _details(got2)

    # 程序路径写了、盘上没有那份程序 => 同样红（三态里"写了"不等于"复核得到"）。
    root3 = _workspace(tmp_path / "gone", rows=[_row(file="code/not_there.py")])
    got3 = PM.mapping_reading(root3)
    assert "mapping_proof_program_missing" in _kinds(got3), _details(got3)


def test_2b_without_the_e_reading_id_the_row_is_red(tmp_path: pathlib.Path) -> None:
    """判据 2（另一半）：证明栏写了程序，但没有 E 的那条读数编号 => 红。"""
    root = _workspace(tmp_path / "ws", rows=[_row(numeric_evidence="")])
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_numeric_evidence_missing" in _kinds(got), _details(got)


# ============================================================ 3. 缺块 => 受控拒绝
@pytest.mark.parametrize("block", [NT.BLOCK_DESIGN, NT.BLOCK_EXHAUSTION])
def test_3_a_missing_block_is_refused_at_the_write_step(tmp_path: pathlib.Path,
                                                       block: str) -> None:
    """判据 3：缺程序设计思路或缺穷举论证 => 落库那一步受控拒绝（不静默通过）。"""
    note = "\n".join(line for line in NOTE_TEXT.split("\n") if block not in line)
    root = pathlib.Path(tmp_path / "ws")
    _workspace(root, note=note)
    store = Store(root)
    registry = build_registry(store=store, workspace_root=root, roles=("G",)).registry
    res = registry.call("doc.write_mapping", role="G", project=".", rows=[_row()])
    assert res.ok is False, f"缺「{block}」却写成功了：{res.data}"
    assert res.meta.get("kind") == "mapping_not_clean", res.meta
    problems = list(res.meta.get("problems") or [])
    assert any(str(p.get("kind")) == "mapping_exhaustion_note_missing" for p in problems), problems
    assert any(block in str(p.get("detail")) for p in problems), problems


def test_3b_a_missing_note_file_is_also_refused(tmp_path: pathlib.Path) -> None:
    """判据 3（另一半）：两块读数的落点根本不在盘上 => 同样受控拒绝。"""
    root = _workspace(tmp_path / "ws", rows=[_row()], note=None)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_exhaustion_note_missing" in _kinds(got), _details(got)


# ============================================================ 4. 负控：不完全的实验
def test_4_an_incomplete_experiment_may_not_be_written_as_a_theorem(
        tmp_path: pathlib.Path) -> None:
    """判据 4（负控）：E 没签成穷举 proof 的实验被写成定理 => 受控拒绝。"""
    root = _workspace(tmp_path / "ws", rows=[_row()], experiment="cross_check")
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_proof_program_unbacked" in _kinds(got), _details(got)
    detail = _details(got)
    assert "有数值实验支持" in detail, detail
    assert "不许写成定理" in detail or "不是定理" in detail, detail


def test_4b_a_theorem_whose_statement_has_no_program_is_left_alone(
        tmp_path: pathlib.Path) -> None:
    """判据 4（反方向，防误伤）：证明栏是自然语言的那一类定理一行都不许被这条拦到。"""
    rows = [_row(file="proofs/thm.tex", numeric_evidence="", exhaustion_note="")]
    root = _workspace(tmp_path / "ws", rows=rows, statement="由定义直接得到。")
    (PM.package_dir(root) / "proofs").mkdir(parents=True, exist_ok=True)
    (PM.package_dir(root) / "proofs" / "thm.tex").write_bytes(b"proof\n")
    got = PM.mapping_reading(root)
    assert not [k for k in _kinds(got) if k.startswith("mapping_proof_program")
                or k == "mapping_numeric_citation_missing"], _details(got)
    assert got["state"] == "pass", _details(got)


# ============================================================ 5. 反真空
def test_5_stubbing_the_block_judgement_true_turns_the_refusal_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 5（反真空）：把「三块齐全」打桩成恒真 => 第 3 条必红。

    两个方向都走真的读数路径：缺块那一份本来红（真判据在管），打桩之后放行
    （那条红消失）—— 没有这一条，第 3 条的绿可能只是"压根没查"。
    """
    note = "\n".join(line for line in NOTE_TEXT.split("\n") if NT.BLOCK_DESIGN not in line)
    root = _workspace(tmp_path / "ws", rows=[_row()], note=note)
    before = PM.mapping_reading(root)
    assert "mapping_exhaustion_note_missing" in _kinds(before), _details(before)

    monkeypatch.setattr(NT, "blocks_missing", lambda text: [])
    after = PM.mapping_reading(root)
    assert "mapping_exhaustion_note_missing" not in _kinds(after), (
        "把三块判定打桩成恒真之后，缺块那一行仍然被拒 ⇒ 第 3 条不是靠这个判定在红"
        f"（它其实是别的东西在拦）：{_details(after)}")


# ============================================================ 6. 正文指回 E 的读数
def test_6_the_paper_segment_must_point_back_to_e(tmp_path: pathlib.Path) -> None:
    """判据 6：正文那一段里指不回 E 的读数 => 红；指得回 => 过。"""
    ok_root = _workspace(tmp_path / "ok", rows=[_row()])
    assert PM.mapping_reading(ok_root)["problems"] == [], _details(PM.mapping_reading(ok_root))

    root = _workspace(tmp_path / "ws", rows=[_row()], tex=UNCITED_TEX)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_numeric_citation_missing" in _kinds(got), _details(got)
    assert "thm:r34" in _details(got), _details(got)


def test_6b_either_the_program_or_the_reading_id_counts_as_the_citation(
        tmp_path: pathlib.Path) -> None:
    """判据 6（口径）：程序路径与 E 的读数编号两种写法都算指得回。"""
    by_program = CLEAN_TEX.replace(" and whose reading is \\texttt{exp:000000} (Appendix A)", "")
    assert "code/r34\\_check.py" in by_program and "exp:000000" not in by_program
    root = _workspace(tmp_path / "prog", rows=[_row()], tex=by_program)
    assert PM.mapping_reading(root)["problems"] == [], _details(PM.mapping_reading(root))

    by_id = CLEAN_TEX.replace("\\texttt{code/r34\\_check.py}", "\\texttt{the accompanying program}")
    root2 = _workspace(tmp_path / "id", rows=[_row()], tex=by_id)
    assert PM.mapping_reading(root2)["problems"] == [], _details(PM.mapping_reading(root2))


# ============================================================ 7. 负控：无出处的叙述
def test_7_the_blocks_may_not_be_rewritten_without_a_source(
        tmp_path: pathlib.Path) -> None:
    """判据 7（负控）：把 E 的两块改写成一段无出处的叙述 => 红（要求带出处）。

    这一段在语义上是"对的"（枚举、剪枝、覆盖全空间都写了），它缺的只有一件事：
    这段东西是谁的读数、在哪。判据只判这一件可判的事（出处）；实质有没有被改写由 H 判。
    """
    root = _workspace(tmp_path / "ws", rows=[_row()], tex=UNCITED_TEX)
    got = PM.mapping_reading(root)
    assert "mapping_numeric_citation_missing" in _kinds(got), _details(got)
    # 反方向：同一段话带上出处就过（判据不是"不许叙述"，而是"叙述要带出处"）。
    cited = UNCITED_TEX.replace(
        "so the search covers the whole space and no colouring survives.",
        "so the search covers the whole space and no colouring survives\n"
        "(E's reading \\texttt{exp:000000}, program \\texttt{code/r34\\_check.py}).")
    ok_root = _workspace(tmp_path / "ok", rows=[_row()], tex=cited)
    assert PM.mapping_reading(ok_root)["problems"] == [], _details(PM.mapping_reading(ok_root))


# ============================================================ 附：作者是 E
def test_8_the_note_must_be_signed_by_e(tmp_path: pathlib.Path) -> None:
    """附：两块读数没有署名（作者不是 E）或者没有 E 的读数编号 => 同样受控拒绝。"""
    for note in (NOTE_TEXT.replace(NT.AUTHOR_MARKER, "作者：G"),
                 NOTE_TEXT.replace("exp:000000", "某次实验")):
        root = _workspace(tmp_path / "ws", rows=[_row()], note=note)
        got = PM.mapping_reading(root)
        assert "mapping_exhaustion_note_missing" in _kinds(got), (note[:40], _details(got))


# ============================================================ 附：词表
def test_9_the_vocabulary_has_exactly_five_kinds() -> None:
    """附：那一组的五个取值逐字（少一个，"缺程序 / 缺块 / 指不回"就有一档没人报）。"""
    assert NT.NUMERIC_KINDS == (
        "mapping_proof_program_missing",
        "mapping_proof_program_unbacked",
        "mapping_numeric_evidence_missing",
        "mapping_exhaustion_note_missing",
        "mapping_numeric_citation_missing",
    )
    assert set(NT.NUMERIC_KINDS) <= set(PM.ALL_PROBLEM_KINDS), (
        "这一组没有全进 `ALL_PROBLEM_KINDS` ⇒ 有一档判出来也不会被当成问题")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
