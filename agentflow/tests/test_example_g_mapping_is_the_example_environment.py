# -*- coding: utf-8 -*-
"""d / e：G 收进正文时 `kind=example` 用 `Example` 环境（反例：`kind=lemma` 仍 `Lemma`）。

业主原话（逐字，`_canon_F_manuscript_protocol.md` 第六节）：

    「登记里 `kind=example` 的行（玩具例子）：正文用 `Example` 环境，不用 Lemma/Theorem；
      其余按既有映射。」

落点是 `papermapping.ENV_TITLES`（六类环境共用的一张表）与 `environment_titles()`
（逐行把「该印什么」与导言区 `\\newtheorem` 真声明成什么对起来）；`mapping_reading`
的 `environments` 一格就是它的读数。它不是 example 专用的分支：theorem / lemma /
proposition / corollary / experiment 五格都走同一张表、同一个读口。
"""
from __future__ import annotations

import pathlib

import test_numeric_theorem_writing_spec as SPEC
from agentflow import papermapping as PM


def _example_mapping_ws(tmp_path: pathlib.Path, kind: str) -> pathlib.Path:
    """一个能过 `mapping_reading` 的最小论文包：一行 kind、正文里一个对应环境。"""
    row = SPEC._row(kind=kind, label="ex:r34", file="proofs/thm.tex",
                    lean_file="", lean_target="", numeric_evidence="",
                    exhaustion_note="", evidence_kind="", evidence_path="",
                    evidence_sha256="", v_signature=None)
    root = SPEC._workspace(tmp_path / f"ws_{kind}", rows=[row],
                           statement="对 n 作归纳：基例 n=0 两端同为 0；归纳步提出公因式即得。",
                           tex=SPEC.CLEAN_TEX
                           .replace("\\begin{theorem}\\label{thm:r34}",
                                    "\\begin{" + kind + "}\\label{ex:r34}")
                           .replace("\\end{theorem}", "\\end{" + kind + "}"))
    target = PM.package_dir(root) / "proofs" / "thm.tex"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"proof\n")
    return root


def _env_reading(root: pathlib.Path, kind: str) -> dict:
    """`mapping_reading` 里逐行那一格（该印什么抬头 / 导言区真声明成什么）。"""
    reading = PM.mapping_reading(root)
    assert reading["state"] == "pass", reading["problems"]
    rows = list(reading["environments"]["rows"])
    match = [r for r in rows if r["kind"] == kind]
    assert len(match) == 1, rows
    return match[0]


def test_d_an_example_row_maps_to_the_example_environment_and_a_lemma_to_lemma(tmp_path):
    """d：`kind=example` ⇒ `Example`；反例 `kind=lemma` 仍 ⇒ `Lemma`（没把别的档带错）。"""
    example = _env_reading(_example_mapping_ws(tmp_path, "example"), "example")
    assert example["env_title"] == "Example", example
    assert example["ok"] is True, example
    lemma = _env_reading(_example_mapping_ws(tmp_path, "lemma"), "lemma")
    assert lemma["env_title"] == "Lemma", lemma
    assert lemma["ok"] is True, lemma
    # 六类都有一格（这张表不是只为 example 长出来的）
    titles = PM.ENV_TITLES
    assert set(titles) == set(PM.ENV_KINDS), (titles, PM.ENV_KINDS)
    assert titles["example"] == "Example" and titles["lemma"] == "Lemma"
    # 正文里那个环境真的被认成 example（不是被当成 theorem 一族）
    root = _example_mapping_ws(tmp_path, "example")
    tex = (PM.package_dir(root) / "main.tex").read_text(encoding="utf-8")
    assert [(e.kind, e.label) for e in PM.body_envs(tex)] == [("example", "ex:r34")]


def test_e_removing_the_example_mapping_makes_d_red(tmp_path, monkeypatch):
    """e：把 example 的映射摘掉 ⇒ d 的读数当场变红（这条绿真的靠那张表）。"""
    root = _example_mapping_ws(tmp_path, "example")
    assert _env_reading(root, "example")["env_title"] == "Example"
    trimmed = {k: v for k, v in PM.ENV_TITLES.items() if k != "example"}
    monkeypatch.setattr(PM, "ENV_TITLES", trimmed)
    reading = PM.mapping_reading(root)
    rows = [r for r in reading["environments"]["rows"] if r["kind"] == "example"]
    assert len(rows) == 1, rows
    assert rows[0]["env_title"] == "", rows[0]
    assert rows[0]["ok"] is False, rows[0]
    assert "example" in reading["environments"]["unknown"], reading["environments"]
