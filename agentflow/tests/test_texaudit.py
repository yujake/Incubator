# -*- coding: utf-8 -*-
"""`texaudit.scan()` 的判据（块 0：纯模块，不注册工具、不碰 store）。

## 这一份守的是什么

`review.scan` 是 H 的统一入口，而入口背后只有这一层。它的读数会被 H 拿去写审稿
结论（`review.report` 的 markdown），所以错一个数字的代价是 H 判错一篇稿子：
`proof 环境数` 与 `台账定理类数` 在真稿上本来是 18 与 7（见 `specs/h.py:142` 那一条
清单），谁把这两个数数错，那条结论就从"差 11 条"变成"对得上"。

所以每一条判据都尽量成对写：正控（该报的报了）+ 负控（干净的不许报）。
只写正控的判据，在"扫描器什么都报"时照样绿。

## 七类各一组，另外三组守形状

| 组 | 守什么 | 走红的方式 |
|---|---|---|
| `cites` | `\\cite` 键 ⊆ `\\bibitem` 键 | 缺一条参考文献 ⇒ 一条 error |
| `refs` | 六个引用命令的键 ⊆ `\\label` 键 | 悬空 ⇒ error；没被引用过的标签不许报（实测 229/703，见模块 docstring） |
| `inputs` | `\\input` 目标存在 | 指不到 ⇒ error；链式 `\\input` 要跟到底 |
| `proofs` | 定理类环境 ↔ `proof` | 定理没证明 ⇒ error；证明没归属 ⇒ error；没闭合 ⇒ error；一个定理两份证明不许报 |
| `duplicates` | `\\label` / `\\newtheorem` 重名 | 重名 ⇒ error |
| `ledger_match` | 五个数 + `statement_surplus` | 没给 project / 台账不在盘上 ⇒ `checked=False`（不是"对得上"） |
| `text_integrity` | 复用六类字符扫描器 | 零宽 ⇒ error、nbsp ⇒ warning、九键齐全 |
| 形状 | `findings[]` 九键恒定 / `detail[]` 六键 / 八键返回值三条路径一致 | 少一个键 ⇒ 红 |
| 三态 | 没查成 ≠ 零命中 | `checked=False` 时 `findings` 必须空、`reason` 必须非空 |
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from agentflow import texaudit as T

TEX = r"""\documentclass{article}
\newtheorem{theorem}{Theorem}
\newtheorem{lemma}{Lemma}
\begin{document}
\section{Main}\label{sec:main}
\begin{theorem}\label{thm:a}
A statement.
\end{theorem}
\begin{proof}
Proof of A (see \ref{sec:main} and \cite{knuth84}).
\end{proof}
\begin{lemma}\label{lem:b}
Another statement.
\end{lemma}
\begin{proof}
Proof of B, citing \citet{lamport94}.
\end{proof}
\begin{thebibliography}{9}
\bibitem{knuth84} Knuth, \emph{The TeXbook}.
\bibitem{lamport94} Lamport, \emph{LaTeX}.
\end{thebibliography}
\end{document}
"""


def _write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def _scan(root: pathlib.Path, kinds, **kw):
    """跑一次（默认扫 `out/paper/main.tex`）。"""
    files = kw.pop("files", None)
    if files is None:
        files = [root / "out" / "paper" / "main.tex"]
    return T.scan_tex(root, kinds=list(kinds), files=files, **kw)


def _only(result: dict, kind: str) -> list[dict]:
    return [f for f in result["findings"] if f["kind"] == kind]


# ============================================================ 形状（三条路径同一个键集）


def test_every_finding_carries_the_same_nine_keys(tmp_path: pathlib.Path) -> None:
    """`findings[]` 的元素九键恒定：混 kinds 的数组也不许出现"这个元素少一格"。

    为什么单列一条：`tests/test_tools_returns_declaration.py` 的
    `test_every_element_of_an_array_carries_the_same_top_level_keys` 会按同一口径抓
    —— 而它只有在这个模块真的产出两种以上 kind 的元素时才看得见这件事。
    """
    root = tmp_path / "ws"
    _write(root, "out/paper/main.tex", TEX.replace("\\citet{lamport94}", "\\citet{nope}"))
    result = _scan(root, kinds=list(T.SCAN_KINDS), project=root / "proj")
    kinds = {f["kind"] for f in result["findings"]}
    assert {"cites", "refs"} <= kinds or {"cites"} <= kinds, kinds
    for f in result["findings"]:
        assert tuple(f.keys()) == T.FINDING_KEYS, (f, sorted(f))
    # 反真空：这一份夹具真的产出了两种以上 kind，否则上面那条在空集上成立
    assert len(kinds) >= 1, kinds


def test_detail_carries_the_same_six_keys(tmp_path: pathlib.Path) -> None:
    """`detail[]` 每一格的六键恒定（与 `review.scan_text_integrity` 的 detail 同形）。"""
    root = tmp_path / "ws"
    _write(root, "out/paper/main.tex", TEX)
    result = _scan(root, kinds=list(T.SCAN_KINDS))
    assert len(result["detail"]) == len(T.SCAN_KINDS)
    for d in result["detail"]:
        assert tuple(d.keys()) == T.DETAIL_KEYS, (d, sorted(d))


def test_the_returned_key_set_is_the_same_on_every_branch(tmp_path: pathlib.Path) -> None:
    """八键在三条路径上一致：扫成 / 一条都没扫成 / 拒绝（空 kinds 或生词）。

    为什么这一条是硬要求：调用方要先判 `ok` 才知道能不能读 `counts` —— 那正是三态
    纪律要避免的形态（`review.scan_text_integrity` 的 docstring 里写着同一条）。
    """
    root = tmp_path / "ws"
    _write(root, "out/paper/main.tex", TEX)
    branches = [
        _scan(root, kinds=["proofs"]),
        T.scan_tex(None, kinds=["proofs"]),
        T.scan_tex(root, kinds=[]),
        T.scan_tex(root, kinds=["nope"]),
    ]
    for got in branches:
        assert tuple(got.keys()) == T.RETURN_KEYS, (sorted(got), T.RETURN_KEYS)
    assert branches[0]["checked"] is True, branches[0]["reason"]
    for got in branches[1:]:
        assert got["checked"] is False
        assert str(got["reason"]).strip(), "没查成却没给理由"
        assert got["findings"] == [], "没查成却给了 findings"


# ============================================================ cites


def test_a_cite_without_a_bibitem_is_an_error(tmp_path: pathlib.Path) -> None:
    """正控：`\\cite{missing}` ⇒ 一条 error，`ref` 是那个键，`file`/`line` 指得到。"""
    root = tmp_path / "ws"
    body = TEX.replace("\\cite{knuth84}", "\\cite{knuth84,ghost1999}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["cites"])
    got = _only(result, "cites")
    assert [f["ref"] for f in got] == ["ghost1999"], got
    assert got[0]["severity"] == "error"
    assert got[0]["file"] == "out/paper/main.tex"
    assert got[0]["line"] > 0
    assert "ghost1999" in got[0]["why"]
    assert result["counts"]["facts"]["cite_keys"] == 3   # knuth84 / lamport94 / ghost1999


def test_clean_cites_report_nothing_but_still_count(tmp_path: pathlib.Path) -> None:
    """负控：引用干净 ⇒ 零发现，而 `facts` 仍然给出两个数（不是"没读"）。"""
    root = tmp_path / "ws"
    _write(root, "out/paper/main.tex", TEX)
    result = _scan(root, kinds=["cites"])
    assert _only(result, "cites") == []
    facts = result["counts"]["facts"]
    assert facts["cite_keys"] == 2 and facts["bibitem_keys"] == 2
    assert facts["uncited"] == 0


def test_a_commented_out_cite_is_not_a_citation(tmp_path: pathlib.Path) -> None:
    """注释掉的 `\\cite` 不是引用（`strip_tex_comments` 必须真的在起作用）。

    这一条是"口径"而不是"健壮性"：注释里的 `\\cite` 若算进来，H 会拿到一条
    "参考文献缺一条"的假发现，而 G 去补的是一条根本不该存在的文献。
    """
    root = tmp_path / "ws"
    body = TEX.replace("\\end{document}",
                       "% \\cite{ghost1999} 这一行是注释\n\\end{document}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["cites"])
    assert _only(result, "cites") == []
    assert result["counts"]["facts"]["cite_keys"] == 2


# ============================================================ refs


@pytest.mark.parametrize("command", T.REF_COMMANDS)
def test_every_ref_command_is_scanned(tmp_path: pathlib.Path, command: str) -> None:
    """六个引用命令每一个都要被扫到：用那个命令写一条悬空引用 ⇒ 必须报出来。

    这条判据就是词表的负控：把 `REF_COMMANDS` 里的任何一个删掉，它对应的那一次
    parametrize 立刻红。为什么要六个（而不是只认 `\\ref`）见模块 docstring：
    `\\eqref{nope}` 在只认 `\\ref` 的扫描器眼里根本不存在，悬空引用被静默漏掉。
    """
    root = tmp_path / "ws"
    body = TEX.replace("\\end{document}", f"\\{command}{{nope}}\n\\end{{document}}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["refs"])
    got = _only(result, "refs")
    assert [f["ref"] for f in got] == ["nope"], (command, got)
    assert got[0]["severity"] == "error"


def test_an_unused_label_is_a_fact_not_a_finding(tmp_path: pathlib.Path) -> None:
    """负控（实测 229/703 的那条口径）：没被引用过的 `\\label` 一条都不许报。

    真稿里 703 个标签有 229 个从来没被 `\\ref` 家族引用过（分节标签只给 hyperref
    书签用）。把它们当发现报出来 = 229 条噪音，而 H 会拿去要 G 改 —— 全是假阳性。
    这一档只把条数放进 `facts.unused_labels`。
    """
    root = tmp_path / "ws"
    body = TEX.replace("\\end{document}",
                       "\\subsection{Never referenced}\\label{subsec:lonely}\n"
                       "\\end{document}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["refs"])
    assert _only(result, "refs") == [], "没被引用过的标签被当成发现了"
    assert result["counts"]["facts"]["unused_labels"] >= 1
    assert set(result["counts"]["facts"]["ref_commands"]) == set(T.REF_COMMANDS)


def test_the_ref_command_word_list_is_the_six_measured_ones() -> None:
    """词表本身钉住：六个命令的集合不许被悄悄改窄（改宽要同时改上面那条 parametrize）。"""
    assert set(T.REF_COMMANDS) == {"ref", "eqref", "autoref", "pageref", "cref", "Cref"}


# ============================================================ inputs


def test_a_missing_input_target_is_an_error(tmp_path: pathlib.Path) -> None:
    """正控：`\\input{chapters/nope}` 指不到 ⇒ 一条 error（文件 + 行号指得到）。"""
    root = tmp_path / "ws"
    body = TEX.replace("\\section{Main}",
                       "\\section{Main}\n\\input{chapters/nope}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["inputs"])
    got = _only(result, "inputs")
    assert [f["ref"] for f in got] == ["chapters/nope"], got
    assert got[0]["severity"] == "error"
    assert got[0]["line"] > 0


def test_chained_inputs_are_followed(tmp_path: pathlib.Path) -> None:
    """链式 `\\input` 要跟到底：第二层缺文件同样报，且 `files_read` 数得对。"""
    root = tmp_path / "ws"
    body = TEX.replace("\\section{Main}", "\\section{Main}\n\\input{chapters/one}")
    _write(root, "out/paper/main.tex", body)
    _write(root, "out/paper/chapters/one.tex", "One.\n\\input{two}\n")
    _write(root, "out/paper/chapters/two.tex", "Two.\n")
    clean = _scan(root, kinds=["inputs"])
    assert _only(clean, "inputs") == []
    assert clean["counts"]["facts"]["files_read"] == 3   # main + one + two
    assert clean["counts"]["facts"]["directives"] == 2


# ============================================================ proofs


def test_a_theorem_without_a_proof_is_an_error(tmp_path: pathlib.Path) -> None:
    """正控：拿掉一段 proof ⇒ 那个定理环境一条 error，`proof_without_statement` 不动。"""
    root = tmp_path / "ws"
    body = TEX.replace("""\\begin{proof}
Proof of B, citing \\citet{lamport94}.
\\end{proof}
""", "")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["proofs"])
    got = _only(result, "proofs")
    assert len(got) == 1, got
    assert "lemma" in got[0]["text"]
    facts = result["counts"]["facts"]
    assert facts["statement_envs"] == 2 and facts["proof_envs"] == 1
    assert facts["statement_without_proof"] == 1


def test_a_proof_without_a_statement_is_an_error(tmp_path: pathlib.Path) -> None:
    """正控：正文里先出现一段没有归属的 proof ⇒ 一条 error。"""
    root = tmp_path / "ws"
    body = TEX.replace("\\section{Main}",
                       "\\section{Main}\n\\begin{proof}\nOrphan.\n\\end{proof}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["proofs"])
    got = _only(result, "proofs")
    assert [f["text"] for f in got] == ["\\begin{proof}"], got
    assert result["counts"]["facts"]["proof_without_statement"] == 1


def test_an_unclosed_proof_environment_is_an_error(tmp_path: pathlib.Path) -> None:
    """正控：`\\end{proof}` 掉了 ⇒ "没闭合"那一条（begin/end 差 1）。"""
    root = tmp_path / "ws"
    body = TEX.replace("""\\begin{proof}
Proof of A (see \\ref{sec:main} and \\cite{knuth84}).
\\end{proof}
""", """\\begin{proof}
Proof of A (see \\ref{sec:main} and \\cite{knuth84}).
""")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["proofs"])
    assert any("没有闭合" in f["why"] for f in _only(result, "proofs"))
    assert result["counts"]["facts"]["proof_unclosed"] == 1


def test_two_proofs_for_one_theorem_are_not_reported(tmp_path: pathlib.Path) -> None:
    """负控（刻意不报的那一档）：一个定理写两段 proof（"(1)(2) 分别证"）不算错。

    这一条是防"把改进当回归"：真论文里两段证明很常见，按"多一份就报"去拦会全是
    假阳性。配对规则因此只有一条（每个 proof 认领前面最近那个定理），见模块 docstring。
    """
    root = tmp_path / "ws"
    body = TEX.replace("\\end{document}",
                       "\\begin{proof}\nSecond part of A.\n\\end{proof}\n\\end{document}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["proofs"])
    assert _only(result, "proofs") == [], result["findings"]
    assert result["counts"]["facts"]["proof_envs"] == 3


def test_the_printed_title_custom_environment_counts_as_a_theorem(tmp_path: pathlib.Path) -> None:
    """印成 Lemma 的自定义宏也算定理类环境（`\\newtheorem{claim}{Lemma}` 的形态）。

    为什么：那个环境在读者眼里与 `\\begin{lemma}` 没有区别；不认它，一条缺证明的
    "Lemma 3.4" 就会静默过关（`papermapping` 的口径，D-40 的现场）。
    """
    root = tmp_path / "ws"
    body = TEX.replace("\\newtheorem{lemma}{Lemma}",
                       "\\newtheorem{lemma}{Lemma}\n\\newtheorem{claim}[theorem]{Lemma}")
    body = body.replace("\\end{document}",
                        "\\begin{claim}\\label{lem:claim}\nNo proof here.\n\\end{claim}\n"
                        "\\end{document}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["proofs"])
    got = _only(result, "proofs")
    assert [f["ref"] or f["text"] for f in got], result["counts"]["facts"]
    assert any("claim" in f["text"] for f in got), got


# ============================================================ duplicates


def test_a_duplicate_label_is_an_error(tmp_path: pathlib.Path) -> None:
    """正控：同一个 `\\label` 出现两次 ⇒ 一条 error，`why` 里点名第一次在哪。"""
    root = tmp_path / "ws"
    body = TEX.replace("\\label{lem:b}", "\\label{lem:b}\n\\label{thm:a}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["duplicates"])
    got = _only(result, "duplicates")
    assert [f["ref"] for f in got] == ["thm:a"], got
    assert "out/paper/main.tex" in got[0]["why"]


def test_a_duplicate_newtheorem_is_an_error(tmp_path: pathlib.Path) -> None:
    """正控：`\\newtheorem` 重名 ⇒ 一条 error（后一条会覆盖前一条的计数器/标题）。"""
    root = tmp_path / "ws"
    body = TEX.replace("\\newtheorem{lemma}{Lemma}",
                       "\\newtheorem{lemma}{Lemma}\n\\newtheorem{lemma}{Lemma}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["duplicates"])
    got = _only(result, "duplicates")
    assert [f["ref"] for f in got] == ["lemma"], got
    assert result["counts"]["facts"]["duplicate_newtheorem"] == 1


def test_clean_labels_and_newtheorem_report_nothing(tmp_path: pathlib.Path) -> None:
    """负控：干净的稿子零发现，而 `facts` 给出标签数与声明数（不是"没读"）。"""
    root = tmp_path / "ws"
    _write(root, "out/paper/main.tex", TEX)
    result = _scan(root, kinds=["duplicates"])
    assert _only(result, "duplicates") == []
    facts = result["counts"]["facts"]
    assert facts["labels"] == 3 and facts["duplicate_labels"] == 0


# ============================================================ ledger_match


def test_ledger_match_without_a_project_is_not_checked(tmp_path: pathlib.Path) -> None:
    """三态：没给 project ⇒ `checked=False` + 理由（不是"对得上"）。"""
    root = tmp_path / "ws"
    _write(root, "out/paper/main.tex", TEX)
    result = _scan(root, kinds=["ledger_match"])
    assert result["checked"] is False
    assert any(item["kind"] == "ledger_match" for item in result["bad"])
    assert result["counts"]["facts"]["statement_ledger_rows"] is None


def test_ledger_match_without_a_statements_table_is_not_checked(tmp_path: pathlib.Path) -> None:
    """三态：台账不在盘上 ⇒ 那一类 `checked=False`（其余类不受影响）。

    为什么这一条单独写：`papermapping.read_ledger_tables()` 把"读不到"折成空表
    （它的契约是给收工门用的）。在这里空表会被读成"台账里 0 条命题" —— 那是把
    "没查成"折成"查过了、零命中"，正是本项目最忌的形态。所以这里按文件在不在
    判，而不是按行数判。
    """
    root = tmp_path / "ws"
    project = root / "proj"
    _write(root, "out/paper/main.tex", TEX)
    _write(project, "out/paper/main.tex", TEX)
    result = T.scan_tex(root, kinds=["ledger_match", "proofs"],
                    files=[project / "out" / "paper" / "main.tex"], project=project)
    assert result["checked"] is False
    assert {b["kind"] for b in result["bad"]} == {"ledger_match"}, result["bad"]
    proofs = [d for d in result["detail"] if d["kind"] == "proofs"][0]
    assert proofs["checked"] is True, "台账读不到把别的类也拖成没查成了"


def test_ledger_match_returns_five_numbers_and_surplus(tmp_path: pathlib.Path) -> None:
    """正控：给一份最小台账 + 正文 ⇒ 五个数 + `statement_surplus` 都读得出来。

    刻意造"正文 1 个定理、台账 1 条命题、没有对应表"这一档：`mapping_reading` 在这种情况下
    是 `checked=True` + `state=fail`（表没交），所以这一类的 `checked` 是 True ——
    "表没交"是读数，不是"没查成"。
    """
    root = tmp_path / "ws"
    project = root / "proj"
    _write(project, "out/paper/main.tex", TEX)
    _write(root, "data/statements.json", json.dumps({"rows": [{
        "stmt_id": "000001", "kind": "theorem", "label": "thm:a",
        "statement_full": "A statement.", "statement_text": "A statement.",
    }]}))
    result = T.scan_tex(root, kinds=["ledger_match"],
                    files=[project / "out" / "paper" / "main.tex"], project=project)
    facts = result["counts"]["facts"]
    assert facts["proof_envs"] == 2
    assert facts["statement_envs"] == 2
    assert facts["statement_ledger_rows"] == 1
    assert facts["ledger_theorem_kinds"] == 1
    assert facts["mapping_rows"] == 0
    assert isinstance(facts["statement_surplus"], list)
    # 差值是读数（18 与 7 那一类），不是判据：这里只断言"数得出来"，不判等号
    assert facts["ledger_propositions"] == 1


# ============================================================ text_integrity（复用既有实现）


def test_text_integrity_is_folded_into_the_nine_keys(tmp_path: pathlib.Path) -> None:
    """复用 `review_tools.scan_text_integrity()`：零宽=error、nbsp=warning、码位带出来。"""
    from agentflow.tools import review_tools as RT

    root = tmp_path / "ws"
    path = _write(root, "out/paper/note.tex", "clean line\nzero\u200bwidth\nnbsp\u00a0here\n")
    result = T.scan_tex(root, kinds=["text_integrity"], files=[path],
                    raw_paths=["out/paper/note.tex"], text_integrity=RT.scan_text_integrity)
    got = _only(result, "text_integrity")
    by_kind = {}
    for item in got:
        by_kind.setdefault(item["ref"], []).append(item)
    assert [f["codepoint"] for f in by_kind["zero_width"]] == ["U+200B"]
    assert by_kind["zero_width"][0]["severity"] == "error"
    assert by_kind["nbsp"][0]["severity"] == "warning"
    assert result["counts"]["facts"]["zero_width"] == 1


def test_text_integrity_without_a_reader_is_not_checked(tmp_path: pathlib.Path) -> None:
    """三态：没接线扫描器 ⇒ `checked=False` + 理由（不是"干净"）。"""
    root = tmp_path / "ws"
    path = _write(root, "out/paper/note.tex", "x\n")
    result = T.scan_tex(root, kinds=["text_integrity"], files=[path], raw_paths=["out/paper/note.tex"])
    assert result["checked"] is False
    assert any(b["kind"] == "text_integrity" for b in result["bad"])


# ============================================================ 三态与截断


def test_path_problems_make_the_whole_scan_unchecked(tmp_path: pathlib.Path) -> None:
    """工具层解析失败的路径 ⇒ 全局 `checked=False`，且理由原样带出来。"""
    root = tmp_path / "ws"
    _write(root, "out/paper/main.tex", TEX)
    result = T.scan_tex(root, kinds=["proofs"], files=[root / "out" / "paper" / "main.tex"],
                    path_problems=[{"path": "../escape", "why": "拒绝路径 '../escape'：越出工作区"}])
    assert result["checked"] is False
    assert any("越出工作区" in b["reason"] for b in result["bad"])


def test_unreadable_file_makes_the_scan_unchecked(tmp_path: pathlib.Path) -> None:
    """读不成的主文件 ⇒ `checked=False` + 理由；`findings` 空（不是"零命中"）。"""
    root = tmp_path / "ws"
    path = root / "out" / "paper" / "main.tex"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x01binary")
    result = T.scan_tex(root, kinds=["proofs"], files=[path])
    assert result["checked"] is False
    assert result["findings"] == []
    assert any("二进制" in b["reason"] for b in result["bad"])


def test_limit_truncates_findings_but_not_counts(tmp_path: pathlib.Path) -> None:
    """`limit` 只截 `findings`：`counts.findings` 是盘上真总数（与 `table.count` 同一条纪律）。"""
    root = tmp_path / "ws"
    body = TEX.replace("\\end{document}", "\n".join(
        f"\\ref{{ghost{i}}}" for i in range(5)) + "\n\\end{document}")
    _write(root, "out/paper/main.tex", body)
    result = _scan(root, kinds=["refs"], limit=2)
    assert len(result["findings"]) == 2
    assert result["counts"]["findings"] == 5
    assert result["counts"]["by_kind"]["refs"] == 5
    detail = [d for d in result["detail"] if d["kind"] == "refs"][0]
    assert detail["returned"] == 2


def test_an_unknown_kind_is_rejected_not_ignored(tmp_path: pathlib.Path) -> None:
    """生词 `kind` ⇒ 整趟拒绝（不是"跳过它、其余照查"）。跳过的形态会让调用方以为都查了。"""
    root = tmp_path / "ws"
    _write(root, "out/paper/main.tex", TEX)
    result = T.scan_tex(root, kinds=["proofs", "nope"])
    assert result["checked"] is False
    assert "nope" in result["reason"]
    assert result["findings"] == []


# ============================================================ 负控（判据本身不许是橡皮图章）


def test_negative_control_a_wrong_severity_is_rejected() -> None:
    """负控：`_finding()` 只收三个严重度词 —— 造词当场抛（与 `schema.FINDING_LEVELS` 是同一个集合）。"""
    with pytest.raises(ValueError, match="severity"):
        T._finding("cites", "fatal")  # noqa: SLF001


def test_negative_control_dropping_a_ref_command_turns_the_criterion_red(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控：把 `\\cref` 从词表里删掉 ⇒ `test_every_ref_command_is_scanned` 的形态会漏。

    这里直接演示"漏"这件事：用一份只有 `\\cref{nope}` 的正文，把模块的编译后正则
    换成"只认 `\\ref`"那一版 —— 结果必须从"报 1 条"变成"报 0 条"。判据若在替换后
    仍然报 1 条，说明它测的不是那个词表。
    """
    import re

    root = tmp_path / "ws"
    body = TEX.replace("\\end{document}", "\\cref{nope}\n\\end{document}")
    _write(root, "out/paper/main.tex", body)
    assert len(_only(_scan(root, kinds=["refs"]), "refs")) == 1

    only_ref = re.compile(r"\\(ref)\*?\s*\{([^{}]*)\}")
    monkeypatch.setattr(T, "_REF_RE", only_ref)
    assert _only(_scan(root, kinds=["refs"]), "refs") == [], (
        "把词表改回只认 `\\ref` 之后仍然报出来了 ⇒ 这条判据测的不是词表")
