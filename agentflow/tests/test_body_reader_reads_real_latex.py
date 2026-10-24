# -*- coding: utf-8 -*-
"""正文读取器必须读得懂合法的 LaTeX（审计缺陷 1–5 的判据）。

这一组守的是 `draft/142-对应表与Lean两格的对抗性审计（17条）.md` 里那四条
"合法输入 ⇒ 静默通过"加一条同族的嵌套缺陷：

1. `\\begin {theorem}`（控制词后带空格）是合法 TeX（控制词后的空格会被吞掉）
   => 必须被读出来；表里缺它要红 `mapping_orphan`；
2. 注释掉的 `\\begin{theorem}` 不是正文环境 => 表里没有它不许红，登记它必须红；
3. `\\iffalse … \\fi` 包住的环境同样不算（TeX 会把整段跳过去）；
4. 注释掉的 `\\input{mapping-appendix}` 不算"附录已印进正文" => `mapping_not_in_paper`，
   而且 `write_appendix` 必须补插一条真的（非注释的）`\\input{mapping-appendix}` ——
   否则附录永久挡在 PDF 外；
5. 定理写在 `\\input{sections/body.tex}` 里 => 必须读出来（0 行表要红、登记两行要
   `pass`），且 `reading["tex_files"]` 要如实列出这次读了哪几个文件；
6. 嵌套（`theorem` 里 `lemma`）内外各一条；`\\input` 成环 / 超深要如实报一档问题，
   不许挂死（深度上限见 `papermapping.MAX_TEX_INPUT_DEPTH`）。

全部用例在 `tmp_path` 下自建工作区，一个模型调用都不发，也不碰 `projects/`。
"""

from __future__ import annotations

import json
import pathlib
import re
import time

from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.store import Store

#: 一条"真的会被排版"的 `\\input{mapping-appendix}`（注释里的不算）。
ACTIVE_INPUT_RE = re.compile(r"\\input\s*\{\s*mapping-appendix(?:\.tex)?\s*\}")

#: 台账里那几条能被解析到的 (ledger_id, proof_no)：每行各占一个槽，
#: 两行不许指同一个 (命题, 证明号)（那也是 `mapping_orphan`，与这里要测的事无关）。
#:
#: 2026-10-24（D-40）起还有第二条：两个不同 label 的定理类环境不许压在同一条命题上
#: （"一条命题对一个环境"，见 `papermapping._statement_surplus_problems`）。所以下面
#: 凡是给两个环境各登记一行的用例，第二行取 slot 2（`stmt:000005`）而不是 slot 1
#: （slot 1 是 `stmt:000004#p2`，与 slot 0 同一条命题）。
LEDGER_SLOTS: tuple[tuple[str, int], ...] = (
    ("stmt:000004#p1", 1),
    ("stmt:000004#p2", 2),
    ("stmt:000005#p1", 1),
    ("stmt:000006#p1", 1),
)

#: `Store.init()` 之后往 statements 里换进去的行（000004 带第二份证明）。
LEDGER_ROWS: list[dict] = [
    {"stmt_id": "000004", "origin": "own_result",
     "proofs": [{"proof_no": 2, "proof_text": "第二条证明"}]},
    {"stmt_id": "000005", "origin": "own_result"},
    {"stmt_id": "000006", "origin": "own_result"},
]


def _dump(path: pathlib.Path, payload) -> None:
    """按仓库口径写一份 json（UTF-8 字节，行尾固定 \\n）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _row(label: str, env_no: int, slot: int = 0, *, kind: str = "theorem") -> dict:
    """表里的一行（`file` 在夹具里真的存在；来源是自产，但照样给 citation_loc）。"""
    ledger_id, proof_no = LEDGER_SLOTS[slot]
    return {
        "kind": kind, "label": label, "env_no": env_no,
        "ledger_id": ledger_id, "proof_no": proof_no,
        "file": f"proofs/slot{slot}.tex",
        "citation_loc": {"file": "sources/notes.txt", "line_range": [1, 20]},
    }


def _workspace(root: pathlib.Path, tex: str, *, rows: list[dict] | None = None,
               extra: tuple[tuple[str, str], ...] = ()) -> pathlib.Path:
    """造一个工作区：台账 + `main.tex` ＋ 包里那些真实文件 ＋ 由 `write_package` 写的表。

    `rows=None` 与 `rows=[]` 都写成 0 行表（都真的落盘：有正文没表是另一档，
    这一组要测的不是它）。`extra` 是包内的额外文件（`sections/body.tex` 之类）。
    """
    root = pathlib.Path(root)
    store = Store(root)
    store.init()
    data = root / "data" / str(S.TABLES["statements"]["file"])
    doc = json.loads(data.read_text(encoding="utf-8"))
    doc["rows"] = [dict(r) for r in LEDGER_ROWS]
    _dump(data, doc)

    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / PC.TEX_NAME).write_bytes(tex.encode("utf-8"))
    for slot in range(len(LEDGER_SLOTS)):
        target = package / f"proofs/slot{slot}.tex"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture\n")
    notes = package / "sources/notes.txt"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_bytes(b"fixture\n")
    for rel, text in extra:
        target = package / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    PM.write_package(root, [PM.Row(**dict(r)) for r in (rows or [])])
    return root


def _kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("problems") or []]


def _details(reading: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in reading.get("problems") or [])


def _active_appendix_inputs(tex: str) -> list[str]:
    """正文里"真的会被排版"的 `\\input{mapping-appendix}`（先剥离注释再找）。"""
    return ACTIVE_INPUT_RE.findall(PM.strip_tex_comments(tex))


def _document(body: str) -> str:
    """一段正文包进最小可编译的 article 里。"""
    return ("\\documentclass{article}\n"
            "\\begin{document}\n"
            + body +
            "\\end{document}\n")


# ---------------------------------------------------------------- 1 空格版 begin


def test_a_begin_spaced_off_its_brace_is_still_a_theorem(tmp_path: pathlib.Path) -> None:
    """`\\begin {theorem}` + `\\end {theorem}`（带空格）必须被读出来，缺登记要红。"""
    tex = _document(
        "\\begin {theorem}\\label{thm:main}\n"
        "第一条定理。\n"
        "\\end {theorem}\n"
        "\\begin {theorem}\\label{thm:spaced}\n"
        "第二条定理（同一行的写法只差一个空格）。\n"
        "\\end {theorem}\n"
    )
    root = _workspace(tmp_path, tex, rows=[_row("thm:main", 1, 0)])
    got = PM.mapping_reading(root)
    assert got["envs"] == 2, got
    assert got["state"] == "fail", ("空格版的环境没被读出来，'表里缺它'就没人报", got)
    assert "mapping_orphan" in _kinds(got), _details(got)
    assert "thm:spaced" in _details(got), _details(got)

    # 登记齐了就该绿（防误伤：读对了才可能逐一对上）
    PM.write_package(root, [PM.Row(**_row("thm:main", 1, 0)),
                            PM.Row(**_row("thm:spaced", 2, 2))])
    got2 = PM.mapping_reading(root)
    assert got2["state"] == "pass", (got2["reason"], _details(got2))
    assert got2["envs"] == 2, got2


# ---------------------------------------------------------------- 2 注释掉的环境


def test_a_commented_out_theorem_is_not_a_body_environment(tmp_path: pathlib.Path) -> None:
    """注释掉的 `\\begin{theorem}` 不是正文环境：不登记不许红，登记了必须红。"""
    tex = _document(
        "\\begin{theorem}\\label{thm:main}\n"
        "真的那一条。\n"
        "\\end{theorem}\n"
        "% \\begin{theorem}\\label{thm:ghost}\n"
        "% 注释掉的这一条不在 PDF 里。\n"
        "% \\end{theorem}\n"
    )
    root = _workspace(tmp_path, tex, rows=[_row("thm:main", 1, 0)])
    got = PM.mapping_reading(root)
    assert got["envs"] == 1, ("注释里的环境被算成正文了", got)
    assert got["state"] == "pass", (got["reason"], _details(got))
    assert _kinds(got) == [], _details(got)

    # 反向：把注释里那一条登记进表 => 表里有、正文没有 => 必须红 `mapping_orphan`
    PM.write_package(root, [PM.Row(**_row("thm:main", 1, 0)),
                            PM.Row(**_row("thm:ghost", 2, 1))])
    got2 = PM.mapping_reading(root)
    assert got2["state"] == "fail", ("表登记了一个 PDF 里不存在的定理，却判 pass", got2)
    assert "mapping_orphan" in _kinds(got2), _details(got2)
    assert "thm:ghost" in _details(got2), _details(got2)


# ---------------------------------------------------------------- 3 \iffalse


def test_a_theorem_inside_iffalse_is_not_a_body_environment(tmp_path: pathlib.Path) -> None:
    """`\\iffalse … \\fi` 包住的环境不参与排版，也不许被算成正文环境。"""
    tex = _document(
        "\\begin{theorem}\\label{thm:main}\n"
        "真的那一条。\n"
        "\\end{theorem}\n"
        "\\iffalse\n"
        "\\begin{theorem}\\label{thm:off}\n"
        "这一段被条件跳过去了。\n"
        "\\end{theorem}\n"
        "\\fi\n"
        "\\begin{lemma}\\label{lem:after}\n"
        "条件块之后的那一条照样要读。\n"
        "\\end{lemma}\n"
    )
    root = _workspace(tmp_path, tex, rows=[_row("thm:main", 1, 0),
                                           _row("lem:after", 1, 2, kind="lemma")])
    got = PM.mapping_reading(root)
    assert got["envs"] == 2, ("\\iffalse 里的环境被算成正文了", got)
    assert got["state"] == "pass", (got["reason"], _details(got))

    # 登记 `\\iffalse` 里那一条 => 正文没有它 => 红
    PM.write_package(root, [PM.Row(**_row("thm:main", 1, 0)),
                            PM.Row(**_row("lem:after", 1, 2, kind="lemma")),
                            PM.Row(**_row("thm:off", 2, 1))])
    got2 = PM.mapping_reading(root)
    assert got2["state"] == "fail", ("\\iffalse 里的环境被当成了正文", got2)
    assert "thm:off" in _details(got2), _details(got2)


# ---------------------------------------------------------------- 4 注释掉的 input


def test_a_commented_out_appendix_input_is_not_printed_and_gets_reinserted(
        tmp_path: pathlib.Path) -> None:
    """注释掉的 `\\input{mapping-appendix}` 判"没印进正文"，写侧必须自愈（补插真的那一行）。"""
    tex = _document(
        "\\begin{theorem}\\label{thm:main}\n"
        "唯一的一条。\n"
        "\\end{theorem}\n"
    )
    root = _workspace(tmp_path, tex, rows=[_row("thm:main", 1, 0)])
    tex_path = PM.package_dir(root) / PC.TEX_NAME
    text = tex_path.read_text(encoding="utf-8")
    assert PM.APPENDIX_INPUT in text, "夹具前提：write_package 已经插进那一行"
    tex_path.write_bytes(text.replace(PM.APPENDIX_INPUT,
                                      "% " + PM.APPENDIX_INPUT).encode("utf-8"))

    got = PM.mapping_reading(root)
    assert got["state"] == "fail", ("注释里的 \\input 被当成了'附录已印进正文'", got)
    assert "mapping_not_in_paper" in _kinds(got), _details(got)
    assert got["appendix_state"] == "missing", got

    # 写侧自愈：必须补插一条真的（非注释的）那一行，而不是因为注释里出现过就跳过
    PM.write_appendix(root)
    after = tex_path.read_text(encoding="utf-8")
    assert _active_appendix_inputs(after), (
        "write_appendix 没有补插非注释的 \\input{mapping-appendix}：注释里那一行骗过了写侧")
    assert PM.mapping_reading(root)["state"] == "pass", PM.mapping_reading(root)["reason"]


# ---------------------------------------------------------------- 5 分节 input


def test_a_theorem_in_an_inputted_section_is_read_and_tex_files_says_so(
        tmp_path: pathlib.Path) -> None:
    """定理写在 `\\input{sections/body.tex}` 里：要读出来，`tex_files` 要如实列。

    0 行表 => 两条都是孤儿环境（红）；登记两行 => pass。
    """
    body = ("\\begin{theorem}\\label{thm:one}\n"
            "分节里的第一条。\n"
            "\\end{theorem}\n"
            "\\begin{theorem}\\label{thm:two}\n"
            "分节里的第二条。\n"
            "\\end{theorem}\n")
    tex = _document("\\input{sections/body.tex}\n")
    root = _workspace(tmp_path, tex, rows=[], extra=(("sections/body.tex", body),))

    got = PM.mapping_reading(root)
    assert got["envs"] == 2, ("\\input 进来的分节没有被读", got)
    assert got["state"] == "fail", ("0 行表却判 pass：正文侧的定理一条都没进对账", got)
    assert "mapping_orphan" in _kinds(got), _details(got)

    # `tex_files`：这次到底读了哪几个文件（按读入顺序，main.tex 恒在第一位）
    assert got["tex_files"][0] == PC.TEX_NAME, got["tex_files"]
    assert "sections/body.tex" in got["tex_files"], got["tex_files"]

    # 登记两行 => pass（表里两行都指得到正文里的环境）
    PM.write_package(root, [PM.Row(**_row("thm:one", 1, 0)),
                            PM.Row(**_row("thm:two", 2, 2))])
    got2 = PM.mapping_reading(root)
    assert got2["state"] == "pass", (got2["reason"], _details(got2))
    assert got2["envs"] == 2, got2
    assert "sections/body.tex" in got2["tex_files"], got2["tex_files"]


# ---------------------------------------------------------------- 6 嵌套 / 成环


def test_nested_environments_are_both_read_and_input_cycles_do_not_hang(
        tmp_path: pathlib.Path) -> None:
    """`theorem` 里的 `lemma` 两条都要读出来；`\\input` 成环 / 超深要报问题且不挂死。"""
    # (a) 嵌套：外层 theorem、内层 lemma，各自的 env_no 都是 1
    nested_tex = _document(
        "\\begin{theorem}\\label{thm:outer}\n"
        "外层。\n"
        "\\begin{lemma}\\label{lem:inner}\n"
        "内层。\n"
        "\\end{lemma}\n"
        "\\end{theorem}\n"
    )
    nested = _workspace(tmp_path / "nested", nested_tex, rows=[])
    got = PM.mapping_reading(nested)
    assert got["state"] == "fail", ("0 行表却判 pass：嵌套里的环境没被读出来", got)
    assert got["envs"] == 2, ("嵌套环境被外层匹配吞掉了", got)
    PM.write_package(nested, [PM.Row(**_row("thm:outer", 1, 0)),
                              PM.Row(**_row("lem:inner", 1, 2, kind="lemma"))])
    got2 = PM.mapping_reading(nested)
    assert got2["state"] == "pass", (got2["reason"], _details(got2))
    assert got2["envs"] == 2, got2

    # (b) 成环：main -> a.tex -> b.tex -> a.tex。报一档问题、不无限展开、不挂死。
    cycle_root = _workspace(tmp_path / "cycle", _document("\\input{a.tex}\n"), rows=[],
                            extra=(("a.tex", "\\input{b.tex}\n"),
                                   ("b.tex", "\\input{a.tex}\n")))
    started = time.monotonic()
    got3 = PM.mapping_reading(cycle_root)
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"成环的 \\input 把读取器挂住了（{elapsed:.1f}s）"
    assert got3["state"] == "fail", ("成环的 \\input 被判成了干净", got3)
    assert "mapping_unresolvable" in _kinds(got3), _details(got3)
    assert any(("环" in str(p.get("detail")) or "上限" in str(p.get("detail")))
               for p in got3["problems"]), _details(got3)

    # (c) 超深：main -> d0 -> d1 -> … -> d10，超过 MAX_TEX_INPUT_DEPTH 要如实报一档
    depth_files: list[tuple[str, str]] = []
    for i in range(10):
        depth_files.append((f"d{i}.tex", f"\\input{{d{i + 1}.tex}}\n"))
    depth_files.append(("d10.tex", "到底了。\n"))
    deep = _workspace(tmp_path / "deep", _document("\\input{d0.tex}\n"), rows=[],
                      extra=tuple(depth_files))
    started = time.monotonic()
    got4 = PM.mapping_reading(deep)
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"超深的 \\input 把读取器挂住了（{elapsed:.1f}s）"
    assert got4["state"] == "fail", ("超过深度上限却判成了干净", got4)
    assert "mapping_unresolvable" in _kinds(got4), _details(got4)
    assert str(PM.MAX_TEX_INPUT_DEPTH) in _details(got4), _details(got4)
