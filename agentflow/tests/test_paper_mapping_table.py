# -*- coding: utf-8 -*-
"""论文对应表（业主 2026-10-22）的判据：表与正文必须双向对上，且不许静默通过。

业主原话：「G 产出论文时需附上对应表，说明每条定理、引理、命题、例子、实验对应产出物的
真实文件和序号是什么，H 依据此核查，G 也依据此写作」。

## 这一组守什么

1. 干净就过（防误伤）：2 条定理 + 1 条实验、表齐、`ledger_id` 与 `proof_no` 都能解析、
   `file` 都在论文包里、正文附录与 json 逐字一致 => `pass`；
2. 三态：没有正文也没有表 => `unknown`（不适用，不是 pass）；有正文而没有表
   => `fail` + `mapping_package_missing`（没产出，不是没查成）；
3. 正文有孤儿环境 => `fail`，点名到行；
4. 表有孤儿行 => `fail`，点名 label；
5. `ledger_id` 解析不到 => `fail`（含 `stmt:000004#pabc` 这种坏尾巴，不许折成 `#p1`）；
6. `file` 不存在 => `fail`，且与"文件存在但空"分得开；
7. 多证明：`#p1` / `#p2` 各占一行、互不顶替；
8. `proof_no` 必须能被 `verifications.proof_list` 解析到，且与 `#pN` 尾巴一致；
9. `citation_loc` 三态（外部文献必填 / 自产可空但要理由 / file 不在包里要红）；
10. 两个落点都在论文包里：`MAPPING.md` 缺了或与 json 漂了都不算通过；
11. 正文必须把表印出来：没有那一节 => `mapping_not_in_paper`；印出来但与 json 不一致
    => `mapping_paper_mismatch`；
12. 分档：客观 kind 全 `blocker`、主观 kind 全 `info`，两个元组非空且不相交，
    且 `papermapping.ALL_PROBLEM_KINDS` 里每个 kind 都被覆盖、都真的产得出来；
13. 收工门那一格三态齐全，且 `status` 仍然只有 `DEFAULT_CHECKS` 那八格（语义不动）。

全部用例都在 `tmp_path` 下自建工作区，一个模型调用都不发。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import closing as CL
from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.agent_h import mapping_judge as MJ
from agentflow.store import Store

#: 正文里那三处环境（`thm:main` 在第 4 行，`thm:tail` 在第 7 行，`exp:scan` 在第 10 行）。
#: `write_appendix` 会在 `\end{document}` 之前插一行 `\input{mapping-appendix}`。
CLEAN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Main results}\n"
    "\\begin{theorem}\\label{thm:main}\n"
    "第一条定理。\n"
    "\\end{theorem}\n"
    "\\begin{theorem}\\label{thm:tail}\n"
    "第二条定理。\n"
    "\\end{theorem}\n"
    "\\begin{experiment}\\label{exp:scan}\n"
    "一条实验。\n"
    "\\end{experiment}\n"
    "\\end{document}\n"
)

#: 干净的那三行（2 条定理 + 1 条实验；`file` 是论文包内的相对路径）。
CLEAN_ROWS: list[dict] = [
    {
        "kind": "theorem", "label": "thm:main", "env_no": 1,
        "ledger_id": "stmt:000004#p1", "proof_no": 1,
        "file": "proofs/thm-main.tex",
        "citation_loc": {"file": "sources/own-notes.txt", "line_range": [1, 20]},
    },
    {
        "kind": "theorem", "label": "thm:tail", "env_no": 2,
        "ledger_id": "stmt:000005", "proof_no": 1,
        "file": "proofs/thm-tail.tex",
        "citation_loc": {"file": "sources/paper-0000.txt", "page_range": [12, 13]},
        "page_or_section": "5",
    },
    {
        "kind": "experiment", "label": "exp:scan", "env_no": 1,
        "ledger_id": "exp:000007", "proof_no": 1,
        "file": "experiments/scan/run.py",
    },
]

#: 台账三张表：`stmt:000004` 是自产（带一条第二证明），`stmt:000005` 是从文献摘的。
CLEAN_LEDGER: dict[str, list[dict]] = {
    "statements": [
        {"stmt_id": "000004", "origin": "own_result", "proof_text": "第一条的证明",
         "statement_text": "第一条定理",
         "proofs": [{"proof_no": 2, "proof_text": "第一条的第二条证明"}]},
        {"stmt_id": "000005", "origin": "external_lit", "source_lit_id": "0000",
         "proof_text": "第二条的证明", "statement_text": "第二条定理"},
    ],
    "experiments": [{"experiment_id": "000007"}],
    "relations": [{"relation_id": "000002"}],
}

#: 表里那几行指向的真实文件（论文包内，内容非空）。
FILES = ("proofs/thm-main.tex", "proofs/thm-tail.tex", "experiments/scan/run.py",
         "sources/own-notes.txt", "sources/paper-0000.txt")


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _workspace(root: pathlib.Path, *, rows: list[dict] | None = None,
               tex: str = CLEAN_TEX, md: bool = True,
               ledger: dict[str, list[dict]] | None = None) -> pathlib.Path:
    """造一个工作区：台账三张表 + 正文 + 包内那些真实文件 + 对应表三份。

    `rows=None` 时**不写**论文包里的 `MAPPING.json`（测"没交表"）。台账文件先按
    `Store.init()` 的信封写一遍再换 rows：收工门那一格要在同一个工作区里跑，版本号必须是真的。
    """
    root = pathlib.Path(root)
    store = Store(root)
    store.init()
    files = CLEAN_LEDGER if ledger is None else ledger
    for table, table_rows in files.items():
        path = root / "data" / str(S.TABLES[table]["file"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["rows"] = [dict(row) for row in table_rows]
        _dump(path, doc)
    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / PC.TEX_NAME).write_bytes(tex.encode("utf-8"))
    for rel in FILES:
        target = package / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture\n")
    if rows is not None:
        PM.write_package(root, [PM.Row(**dict(row)) for row in rows])
        if not md:
            (package / PM.MAPPING_MD_NAME).unlink()
    return root


def _kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("problems") or []]


def _details(reading: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in reading.get("problems") or [])


class _Break:
    """改一处就重算一次读数（每条判据只改一处，改前那一条必须绿）。"""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.json_path, self.md_path = PM.mapping_paths(root)

    def rows(self) -> list[dict]:
        return list(json.loads(self.json_path.read_text(encoding="utf-8"))["rows"])

    def write_rows(self, rows: list[dict]) -> None:
        PM.write_package(self.root, [PM.Row(**dict(r)) for r in rows])

    def reading(self) -> dict:
        return PM.mapping_reading(self.root)


# ---------------------------------------------------------------- 1 干净就过


def test_clean_mapping_passes(tmp_path: pathlib.Path) -> None:
    """正控（防误伤）：2 条定理 + 1 条实验、表齐、附录印出来了 => pass。"""
    root = _workspace(tmp_path, rows=CLEAN_ROWS)
    got = PM.mapping_reading(root)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]
    assert (got["rows"], got["envs"], got["md_state"], got["appendix_state"]) == \
        (3, 3, "present", "present")
    assert got["empty_files"] == []
    assert got["reason"]
    # 三份都在论文包里（不在工作区别处）
    package = PM.package_dir(root)
    assert (package / PM.MAPPING_JSON_NAME).is_file()
    assert (package / PM.MAPPING_MD_NAME).is_file()
    assert (package / PM.APPENDIX_FILE_NAME).is_file()
    assert PM.APPENDIX_INPUT in (package / PC.TEX_NAME).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 2 三态


def test_no_paper_and_no_table_is_unknown_not_pass(tmp_path: pathlib.Path) -> None:
    """没有正文也没有表 => unknown（不适用），不是 pass、不是 fail，理由非空。"""
    root = _workspace(tmp_path, rows=None)
    (PM.package_dir(root) / PC.TEX_NAME).unlink()
    got = PM.mapping_reading(root)
    assert got["state"] == "unknown", got
    assert got["checked"] is False
    assert got["reason"].strip(), "没查成必须说出为什么（不许留空）"
    assert _kinds(got) == [], got["problems"]


def test_a_paper_without_a_table_in_the_package_is_red(tmp_path: pathlib.Path) -> None:
    """有正文、论文包里没有表 => 红（没产出，不是没查成）。"""
    root = _workspace(tmp_path, rows=None)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    assert _kinds(got) == ["mapping_package_missing"], got["problems"]
    assert "没产出" in got["problems"][0]["detail"]
    assert MJ.level_of("mapping_package_missing") == MJ.LEVEL_BLOCKER


def test_a_table_written_outside_the_package_is_also_red(tmp_path: pathlib.Path) -> None:
    """表写在包外（工作区根）=> 包外那一份不算数，两条都要红。"""
    root = _workspace(tmp_path, rows=None)
    _dump(root / PM.MAPPING_JSON_NAME, {"rows": CLEAN_ROWS})
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    assert "mapping_package_missing" in _kinds(got), _details(got)
    assert "mapping_missing" in _kinds(got), _details(got)
    assert "包之外" in " ".join(p["detail"] for p in got["problems"] if p["kind"] == "mapping_missing")


# ---------------------------------------------------------------- 3 正文孤儿环境


def test_an_environment_without_a_row_is_red_and_names_the_line(tmp_path: pathlib.Path) -> None:
    """正文里多一个环境、表里没有 => fail，点名到行号。"""
    tex = CLEAN_TEX.replace(
        "\\begin{experiment}",
        "\\begin{corollary}\\label{cor:extra}\n多出来的一条推论。\n\\end{corollary}\n"
        "\\begin{experiment}")
    root = _workspace(tmp_path, rows=CLEAN_ROWS, tex=tex)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    assert "mapping_orphan" in _kinds(got), _details(got)
    line = tex.split("\n").index("\\begin{corollary}\\label{cor:extra}") + 1
    mine = [p for p in got["problems"]
            if p["kind"] == "mapping_orphan" and "cor:extra" in p["detail"]]
    assert mine, _details(got)
    assert f"第 {line} 行" in mine[0]["detail"], mine[0]["detail"]
    assert mine[0]["where"].endswith(f":{line}"), mine[0]
    assert MJ.level_of("mapping_orphan") == MJ.LEVEL_BLOCKER


# ---------------------------------------------------------------- 4 表孤儿行


def test_a_row_without_an_environment_is_red_and_names_the_label(tmp_path: pathlib.Path) -> None:
    """表里多一行、正文里没有对应环境 => fail，点名 label。"""
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[1] = dict(rows[1], label="thm:ghost")
    root = _workspace(tmp_path, rows=rows)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    mine = [p for p in got["problems"]
            if p["kind"] == "mapping_orphan" and p["label"] == "thm:ghost"]
    assert mine, _details(got)
    assert "thm:ghost" in mine[0]["detail"], mine[0]["detail"]


# ---------------------------------------------------------------- 5 台账解析不到


def test_an_unresolvable_ledger_id_is_red(tmp_path: pathlib.Path) -> None:
    """`ledger_id` 在台账里找不到 => fail，并说出是哪一个。"""
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = dict(rows[0], ledger_id="stmt:000999", proof_no=1)
    root = _workspace(tmp_path, rows=rows)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    mine = [p for p in got["problems"] if p["kind"] == "mapping_unresolvable"]
    assert mine, _details(got)
    assert "000999" in mine[0]["detail"], mine[0]["detail"]


def test_a_bad_proof_tail_is_red_and_is_not_folded_into_p1(tmp_path: pathlib.Path) -> None:
    """坏尾巴（`#pabc`）必须红：折成 `#p1` 就会把"第 2 条"读成"第 1 条"。"""
    ledger = {"statements": CLEAN_LEDGER["statements"], "experiments": CLEAN_LEDGER["experiments"],
              "relations": CLEAN_LEDGER["relations"]}
    resolved = PM.resolve_ledger_id("stmt:000004#pabc", ledger)
    assert resolved["ok"] is False, resolved
    assert "#pabc" in resolved["reason"], resolved["reason"]
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = dict(rows[0], ledger_id="stmt:000004#pabc")
    root = _workspace(tmp_path, rows=rows)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    mine = [p for p in got["problems"] if p["kind"] == "mapping_unresolvable"]
    assert mine, _details(got)
    assert "#pabc" in mine[0]["detail"], mine[0]["detail"]
    # 干净的尾巴照旧解析（防误伤：坏尾巴红不许连累好尾巴）
    assert PM.resolve_ledger_id("stmt:000004#p2", ledger)["proof_no"] == 2


# ---------------------------------------------------------------- 6 文件那一栏


def test_a_missing_file_is_red_and_differs_from_an_empty_one(tmp_path: pathlib.Path) -> None:
    """`file` 不存在 => fail；"在、但空"不是 missing（三态不许折平）。"""
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = dict(rows[0], file="proofs/not-there.tex")
    broken = _workspace(tmp_path / "broken", rows=rows)
    got = PM.mapping_reading(broken)
    assert got["state"] == "fail", got
    mine = [p for p in got["problems"] if p["kind"] == "mapping_file_missing"]
    assert mine, _details(got)
    assert "proofs/not-there.tex" in mine[0]["detail"], mine[0]["detail"]

    rows2 = [dict(r) for r in CLEAN_ROWS]
    rows2[0] = dict(rows2[0], file="proofs/empty.tex")
    clean = _workspace(tmp_path / "empty", rows=rows2)
    (PM.package_dir(clean) / "proofs" / "empty.tex").write_bytes(b"")
    got2 = PM.mapping_reading(clean)
    assert got2["state"] == "pass", _details(got2)
    assert got2["empty_files"] == ["proofs/empty.tex"], got2


def test_a_path_outside_the_package_is_red(tmp_path: pathlib.Path) -> None:
    """绝对路径 / 指到包外的相对路径都过不了"换一台机器也能复核"这一关。"""
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = dict(rows[0], file="../outside.tex")
    root = _workspace(tmp_path, rows=rows)
    (root / "outside.tex").write_bytes(b"outside\n")
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    assert "包之外" in _details(got), _details(got)

    absolute = str((PM.package_dir(root) / "proofs" / "thm-main.tex").resolve())
    brk = _Break(root)
    rows2 = [dict(r) for r in CLEAN_ROWS]
    rows2[0] = dict(rows2[0], file=absolute)
    brk.write_rows(rows2)
    got2 = brk.reading()
    assert got2["state"] == "fail", got2
    assert "绝对路径" in _details(got2), _details(got2)


# ---------------------------------------------------------------- 7 多证明


def test_multi_proof_rows_do_not_stand_in_for_each_other(tmp_path: pathlib.Path) -> None:
    """`#p1` / `#p2` 各占一行：两条都解析到各自的证明号，互相顶替要红。"""
    rows = [dict(r) for r in CLEAN_ROWS]
    rows.append({
        "kind": "theorem", "label": "thm:main", "env_no": 1,
        "ledger_id": "stmt:000004#p2", "proof_no": 2,
        "file": "proofs/thm-main-p2.tex",
        "citation_loc": {"file": "sources/own-notes.txt", "line_range": [1, 20]},
    })
    root = _workspace(tmp_path, rows=rows)
    (PM.package_dir(root) / "proofs" / "thm-main-p2.tex").write_bytes(b"second proof\n")
    got = PM.mapping_reading(root)
    assert got["state"] == "pass", _details(got)
    ledger = PM.read_ledger(root)
    assert PM.resolve_ledger_id("stmt:000004#p1", ledger)["proof_no"] == 1
    assert PM.resolve_ledger_id("stmt:000004#p2", ledger)["proof_no"] == 2
    assert PM.proof_nos_of(ledger["statements"][0]) == [1, 2]

    # 负控：第二行也写成 `#p1` => 两行指同一条证明，必须红（不许互相顶替）
    clash = [dict(r) for r in rows]
    clash[-1] = dict(clash[-1], ledger_id="stmt:000004#p1", proof_no=1)
    brk = _Break(root)
    brk.write_rows(clash)
    got2 = brk.reading()
    assert got2["state"] == "fail", got2
    assert "mapping_orphan" in _kinds(got2), _details(got2)


def test_proof_no_must_be_resolvable_in_the_ledger(tmp_path: pathlib.Path) -> None:
    """`proof_no` 必须出现在该命题的 `proofs` 清单里，且与 `ledger_id` 的尾巴一致。"""
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = dict(rows[0], ledger_id="stmt:000004#p1", proof_no=3)
    root = _workspace(tmp_path, rows=rows)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    assert "mapping_unresolvable" in _kinds(got), _details(got)

    mismatch = [dict(r) for r in CLEAN_ROWS]
    mismatch[0] = dict(mismatch[0], ledger_id="stmt:000004#p2", proof_no=1)
    brk = _Break(root)
    brk.write_rows(mismatch)
    got2 = brk.reading()
    assert got2["state"] == "fail", got2
    assert "mapping_unresolvable" in _kinds(got2), _details(got2)


# ---------------------------------------------------------------- 8 citation_loc


def test_citation_loc_three_states(tmp_path: pathlib.Path) -> None:
    """外部文献必填；自产可空但要理由；给了 loc 而 file 不在包里要红。"""
    root = _workspace(tmp_path, rows=CLEAN_ROWS)
    brk = _Break(root)

    # (a) 外部文献那一行把 citation_loc 删掉 => 红
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[1] = {k: v for k, v in rows[1].items() if k != "citation_loc"}
    brk.write_rows(rows)
    got = brk.reading()
    assert got["state"] == "fail", got
    assert "mapping_citation_loc_missing" in _kinds(got), _details(got)

    # (b) 自产那一行不给 loc、但给了理由 => 不算问题
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = {k: v for k, v in rows[0].items() if k != "citation_loc"}
    rows[0]["citation_loc_reason"] = "我们自己构造的，无可引的原文位置"
    brk.write_rows(rows)
    got = brk.reading()
    assert got["state"] == "pass", _details(got)

    # (c) 自产那一行既没有 loc 也没有理由 => 红
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = {k: v for k, v in rows[0].items() if k != "citation_loc"}
    brk.write_rows(rows)
    got = brk.reading()
    assert got["state"] == "fail", got
    assert "mapping_citation_loc_missing" in _kinds(got), _details(got)

    # (d) loc 的 file 不在包里 => 红（这一档与"文件空"分开）
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[1] = dict(rows[1], citation_loc={"file": "sources/not-there.txt",
                                          "page_range": [1, 2]})
    brk.write_rows(rows)
    got = brk.reading()
    assert got["state"] == "fail", got
    assert "mapping_citation_file_missing" in _kinds(got), _details(got)

    # (e) 区间起点 > 终点 / 不是正整数 / 一种都没给 => 红
    for bad in ({"file": "sources/paper-0000.txt", "page_range": [13, 12]},
                {"file": "sources/paper-0000.txt", "line_range": [0, 3]},
                {"file": "sources/paper-0000.txt"}):
        rows = [dict(r) for r in CLEAN_ROWS]
        rows[1] = dict(rows[1], citation_loc=bad)
        brk.write_rows(rows)
        got = brk.reading()
        assert got["state"] == "fail", (bad, got)
        assert "mapping_citation_loc_missing" in _kinds(got), (bad, _details(got))

    # (f) 外网 URL 不算本地位置
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[1] = dict(rows[1], citation_loc={"file": "https://example.org/x.pdf",
                                          "page_range": [1, 2]})
    brk.write_rows(rows)
    got = brk.reading()
    assert got["state"] == "fail", got
    assert "mapping_citation_file_missing" in _kinds(got), _details(got)


# ---------------------------------------------------------------- 9 两个落点


def test_the_human_readable_copy_is_not_a_silent_pass(tmp_path: pathlib.Path) -> None:
    """`MAPPING.md` 缺了、或被手改成与 json 不一致 => 都不算通过。"""
    root = _workspace(tmp_path, rows=CLEAN_ROWS, md=False)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    assert _kinds(got) == ["md_missing"], got["problems"]
    assert got["md_state"] == "missing"
    assert MJ.level_of("md_missing") == MJ.LEVEL_BLOCKER, "少交一份不许静默通过"

    md = PM.mapping_paths(root)[1]
    PM.sync_markdown(root)
    assert PM.mapping_reading(root)["state"] == "pass"
    md.write_bytes(md.read_bytes() + "手写的一行\n".encode("utf-8"))
    got2 = PM.mapping_reading(root)
    assert got2["state"] == "fail", got2
    assert _kinds(got2) == ["md_drifted"], got2["problems"]


def test_one_writer_generates_the_json_and_the_markdown(tmp_path: pathlib.Path) -> None:
    """两份由同一段代码生成：md 逐字等于 `render_markdown(rows)`，重生成幂等。"""
    root = _workspace(tmp_path, rows=CLEAN_ROWS)
    json_path, md_path = PM.mapping_paths(root)
    rows, problems = PM.parse_rows(json.loads(json_path.read_text(encoding="utf-8")))
    assert problems == []
    assert md_path.read_text(encoding="utf-8") == PM.render_markdown(rows)
    before = md_path.read_bytes()
    PM.sync_markdown(root)
    assert md_path.read_bytes() == before, "重生成不是幂等的"
    text = md_path.read_text(encoding="utf-8")
    assert "proof_no" in text and "citation_loc" in text and "包内" in text


# ---------------------------------------------------------------- 10 正文附录


def test_the_table_must_be_printed_in_the_paper(tmp_path: pathlib.Path) -> None:
    """json 在、正文里没有那一节 => `mapping_not_in_paper`（表没印进正文）。"""
    root = _workspace(tmp_path, rows=CLEAN_ROWS)
    tex = PM.package_dir(root) / PC.TEX_NAME
    text = tex.read_text(encoding="utf-8")
    assert PM.APPENDIX_INPUT in text, "夹具前提：write_package 已经插进 \\input"
    tex.write_bytes(text.replace(PM.APPENDIX_INPUT, "").encode("utf-8"))
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    assert _kinds(got) == ["mapping_not_in_paper"], got["problems"]
    assert got["appendix_state"] == "missing"
    assert MJ.level_of("mapping_not_in_paper") == MJ.LEVEL_BLOCKER


def test_a_printed_appendix_that_drifts_from_the_json_is_red(tmp_path: pathlib.Path) -> None:
    """印出来的附录与 json 渲染的不一致 => `mapping_paper_mismatch`（行数 / label 都要点出来）。"""
    root = _workspace(tmp_path, rows=CLEAN_ROWS)
    frag = PM.appendix_path(root)
    text = frag.read_text(encoding="utf-8")
    assert PM.APPENDIX_BEGIN in text, "夹具前提：附录块带界标"
    # (a) 少印一行
    lines = text.split("\n")
    dropped = [ln for ln in lines if "thm:tail" not in ln]
    frag.write_bytes("\n".join(dropped).encode("utf-8"))
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got
    assert _kinds(got) == ["mapping_paper_mismatch"], got["problems"]
    assert "thm:tail" in got["problems"][0]["detail"], got["problems"][0]["detail"]
    # (b) 行数对上、label 只在附录里
    frag.write_bytes(text.replace("thm:tail", "thm:elsewhere").encode("utf-8"))
    got2 = PM.mapping_reading(root)
    assert got2["state"] == "fail", got2
    assert "thm:elsewhere" in got2["problems"][0]["detail"], got2["problems"][0]["detail"]
    # (c) 重渲染一次就干净（唯一合法的修法）
    PM.write_appendix(root)
    assert PM.mapping_reading(root)["state"] == "pass"


def test_the_appendix_can_also_be_inlined_in_the_tex(tmp_path: pathlib.Path) -> None:
    """`\\input` 与内联两种形态都认（判据认的是那一对界标与逐字内容）。"""
    root = _workspace(tmp_path, rows=CLEAN_ROWS)
    package = PM.package_dir(root)
    tex = package / PC.TEX_NAME
    frag = PM.appendix_path(root)
    block = frag.read_text(encoding="utf-8").rstrip("\n")
    text = tex.read_text(encoding="utf-8").replace(PM.APPENDIX_INPUT, block)
    tex.write_bytes(text.encode("utf-8"))
    frag.unlink()
    got = PM.mapping_reading(root)
    assert got["state"] == "pass", _details(got)
    assert got["appendix_state"] == "present"


# ---------------------------------------------------------------- 11 分档


def test_objective_kinds_block_and_subjective_ones_only_name() -> None:
    """客观全 blocker；主观全 info；两档非空、不相交、覆盖所有问题类别。"""
    assert MJ.MAPPING_OBJECTIVE_KINDS == (
        "mapping_missing", "mapping_orphan", "mapping_unresolvable", "mapping_file_missing",
    ), "业主点名的四类就是这四个（顺序即词表）"
    assert MJ.MAPPING_OBJECTIVE_KINDS == PM.MAPPING_KINDS, "词表只许有一个真身"
    for group in (MJ.MAPPING_OBJECTIVE_KINDS, MJ.CITATION_OBJECTIVE_KINDS,
                  MJ.MD_OBJECTIVE_KINDS, MJ.PAPER_OBJECTIVE_KINDS):
        assert group, "客观那几组都不许是空的"
        assert all(MJ.level_of(k) == MJ.LEVEL_BLOCKER for k in group)
    assert MJ.SUBJECTIVE_KINDS, "主观那一档不许是空的（否则'只点名'这条口径没有对象）"
    assert all(MJ.level_of(k) == MJ.LEVEL_INFO for k in MJ.SUBJECTIVE_KINDS)
    assert set(MJ.BLOCKING_KINDS) & set(MJ.SUBJECTIVE_KINDS) == set(), "两档不许有交集"
    uncovered = [k for k in PM.ALL_PROBLEM_KINDS
                 if k not in set(MJ.BLOCKING_KINDS) | set(MJ.SUBJECTIVE_KINDS)]
    assert uncovered == [], uncovered
    assert set(PM.ALL_PROBLEM_KINDS) == set(MJ.BLOCKING_KINDS), (
        "产出侧会报的 kind 与拦门那一档必须一一对应（多一个'永远不报'的 kind 也不行）")


def test_findings_are_readable_and_never_none() -> None:
    """`findings_of` 的产物逐条可读；零条时返回空表而不是 None（"没有"与"没查"分得开）。"""
    got = MJ.findings_of({"problems": []})
    assert got == [] and got is not None
    assert MJ.findings_of(None) == []
    reading = {"problems": [
        PM._problem("mapping_orphan", "正文第 4 行的 theorem 在表里没有对应行",
                    label="thm:main", where="main.tex:4"),
        PM._problem("md_missing", "人读那一份不在包里"),
    ]}
    findings = MJ.findings_of(reading)
    assert [f["kind"] for f in findings] == ["mapping_orphan", "md_missing"]
    assert [f["level"] for f in findings] == [MJ.LEVEL_BLOCKER, MJ.LEVEL_BLOCKER]
    assert findings[0]["target"] == "thm:main"
    assert "第 4 行" in findings[0]["message"]
    assert MJ.problem_counts(findings) == {"mapping_orphan": 1, "md_missing": 1}


# ---------------------------------------------------------------- 12 收工门那一格


def _closing(root: pathlib.Path) -> CL.ClosingReport:
    return CL.check_closing(Store(root), project_dir=".")


def test_the_closing_reading_has_all_three_states(tmp_path: pathlib.Path) -> None:
    """`readings["mapping"]` 三态齐全，且 `status` 仍然只有 `DEFAULT_CHECKS` 那八格。"""
    ok_root = _workspace(tmp_path / "ok", rows=CLEAN_ROWS)
    rep = _closing(ok_root)
    assert rep.readings["mapping"]["state"] == "pass", rep.readings["mapping"]
    assert rep.readings["mapping"]["findings"] == 0
    assert set(rep.status) == set(CL.DEFAULT_CHECKS), "八格之外不许长出新的一格"
    assert [f for f in rep.findings if f.check == "mapping"] == []

    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = dict(rows[0], file="proofs/not-there.tex")
    bad_root = _workspace(tmp_path / "bad", rows=rows)
    rep2 = _closing(bad_root)
    assert rep2.readings["mapping"]["state"] == "fail", rep2.readings["mapping"]
    blockers = [f for f in rep2.findings if f.check == "mapping"]
    assert blockers and all(f.level == "blocker" for f in blockers), blockers
    assert blockers[0].code == "mapping_file_missing", blockers[0].code
    assert rep2.machine_pass is False
    assert set(rep2.status) == set(CL.DEFAULT_CHECKS)

    none_root = _workspace(tmp_path / "none", rows=None)
    (PM.package_dir(none_root) / PC.TEX_NAME).unlink()
    rep3 = _closing(none_root)
    assert rep3.readings["mapping"]["state"] == "unknown", rep3.readings["mapping"]
    assert rep3.readings["mapping"]["reason"].strip()
    assert [f for f in rep3.findings if f.check == "mapping"] == []
    assert set(rep3.status) == set(CL.DEFAULT_CHECKS)


def test_the_closing_reading_without_a_project_root_is_unknown() -> None:
    """没给项目根 => 这一格 unknown（不是 pass）：没查成不许当通过。"""
    rep = CL.ClosingReport()
    CL._check_mapping(rep, "", object())
    assert rep.readings["mapping"]["state"] == "unknown"
    assert rep.readings["mapping"]["reason"].strip()
    assert [f.code for f in rep.findings] == ["mapping_missing"]


# ---------------------------------------------------------------- 13 反真空


def test_every_problem_kind_is_reachable() -> None:
    """每一类问题都真的产得出来（词表里挂着一个永远不报的 kind 与"没接上"同效）。"""
    assert len(set(PM.ALL_PROBLEM_KINDS)) == len(PM.ALL_PROBLEM_KINDS)
    assert set(PM.ALL_PROBLEM_KINDS) == (
        set(PM.MAPPING_KINDS) | set(PM.CITATION_KINDS) | set(PM.MD_KINDS)
        | set(PM.PAPER_KINDS)
    )


def test_every_problem_kind_is_produced_by_some_broken_workspace(tmp_path: pathlib.Path) -> None:
    """逐个造一次坏，把 10 个 kind 全产出来（每一类都有产出路径）。"""
    seen: set[str] = set()

    # 包里没表 + 包外有一份
    no_table = _workspace(tmp_path / "a", rows=None)
    _dump(no_table / PM.MAPPING_JSON_NAME, {"rows": CLEAN_ROWS})
    seen |= set(_kinds(PM.mapping_reading(no_table)))

    # 孤儿环境 + 孤儿行 + 解不开的代号码 + 缺文件 + 引文两档
    rows = [dict(r) for r in CLEAN_ROWS]
    rows[0] = dict(rows[0], file="proofs/not-there.tex",
                   ledger_id="stmt:000999", proof_no=1,
                   citation_loc={"file": "sources/not-there.txt", "page_range": [1, 2]})
    rows[1] = {k: v for k, v in rows[1].items() if k != "citation_loc"}
    rows.append(dict(rows[2], label="thm:ghost", ledger_id="exp:000007", proof_no=1))
    broken = _workspace(tmp_path / "b", rows=rows, md=False)
    seen |= set(_kinds(PM.mapping_reading(broken)))

    # 正文没印出来
    not_in_paper = _workspace(tmp_path / "c", rows=CLEAN_ROWS)
    tex = PM.package_dir(not_in_paper) / PC.TEX_NAME
    tex.write_bytes(tex.read_text(encoding="utf-8").replace(PM.APPENDIX_INPUT, "").encode("utf-8"))
    seen |= set(_kinds(PM.mapping_reading(not_in_paper)))

    # 印出来但与 json 不一致
    drift = _workspace(tmp_path / "d", rows=CLEAN_ROWS)
    frag = PM.appendix_path(drift)
    frag.write_bytes(frag.read_bytes().replace(b"thm:tail", b"thm:other"))
    seen |= set(_kinds(PM.mapping_reading(drift)))

    # md 漂了
    md_drift = _workspace(tmp_path / "e", rows=CLEAN_ROWS)
    md = PM.mapping_paths(md_drift)[1]
    md.write_bytes(md.read_bytes() + b"x\n")
    seen |= set(_kinds(PM.mapping_reading(md_drift)))

    missing = sorted(set(PM.ALL_PROBLEM_KINDS) - seen)
    assert not missing, f"这些 kind 一次都没被产出来过：{missing}"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
