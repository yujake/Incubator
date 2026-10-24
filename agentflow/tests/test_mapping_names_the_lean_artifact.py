# -*- coding: utf-8 -*-
"""论文对应表里的 Lean 两格（业主 2026-10-22 追加）。

业主原话：「有 Lean 产出时，还要写明 Lean 程序的位置与它验的是哪条定理/哪条证明」。
两格的字段：`lean_file`（验它的那份源码在哪：项目根相对路径 `code/formal/000004.lean`
（L 的落点）或论文包内相对路径 `formal/000004.lean`，两个根都解析 —— 2026-10-25 第 4 条）
与 `lean_target`（那份源码里哪个声明的名字）。

## 这一组守什么（八条，逐条对应业主给的口径）

1. 开关关、盘上也没有 Lean 产物 => `state=pass`，两格允许为空，读数里读得出
   「未开 Lean」（空不许被当成"验过了"）；
2. 开关开、盘上有 `.lean`，两条定理行都给了两格且名字真的在那份源码里 => `pass`；
3. 开关开、有 `.lean`，某条定理行缺 `lean_target` => `fail` +
   `mapping_lean_missing`，且这一档是 blocker；
4. `lean_file` 两个根里都找不到（不存在 / 绝对路径 / 指到两个根之外 / 不是 `.lean`）
   => `mapping_lean_file_missing`；
5. `lean_target` 在那一份源码里找不到（用 `foo` 对 `fooBar` 做词边界反例）
   => `mapping_lean_target_missing`；
6. 开关开、盘上一个 Lean 产物都没有 => 读数里看得见 `lean_on_but_no_artifact`
   （warning 档：不动门，但也不许静默）；
7. 同一个 `lean_target` 被两行共用 => `mapping_lean_target_ambiguous`
   （允许两行共用一个 `lean_file`，但 `lean_target` 必须各自不同）；
8. 反真空：把 `LEAN_KINDS` 清空（内存里 monkeypatch）=> 第 3 条那条红必须消失，
   说明它真的靠那组 kind 而不是靠一段顺手写死的判断。

全部用例都在 `tmp_path` 下自建工作区，零模型调用。
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import papermapping as PM
from agentflow import settings as SET
from agentflow.agent_h import mapping_judge as MJ
from agentflow.store import Store

#: 正文里那三处环境（两条定理 + 一条实验）。
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

#: 论文包内那一份 Lean 源码（夹具：三个全名声明，其中一个 `fooBar` 专门给词边界反例用）。
#:
#: 为什么写成带点的全名而不是 `namespace` 里写短名：判据认的是"这个名字真的出现在文件里"
#: （词边界匹配），而 `namespace FreeGroupFactor` + `theorem isII1` 那种写法里，
#: 字面 `FreeGroupFactor.isII1` 并不出现。两种写法都能表达同一个声明，判据只管字面。
LEAN_SOURCE = (
    "import Mathlib\n"
    "\n"
    "theorem FreeGroupFactor.isII1 : True := trivial\n"
    "\n"
    "theorem FreeGroupFactor.isSimple : True := trivial\n"
    "\n"
    "theorem FreeGroupFactor.fooBar : True := trivial\n"
)

#: 两份 Lean 产物都写在包里的这个相对路径上（业主口径里的 `formal/000004.lean`）。
LEAN_REL = "formal/000004.lean"

#: 表格里那几行指向的真实文件（论文包内，内容非空）。
FILES = ("proofs/thm-main.tex", "proofs/thm-tail.tex", "experiments/scan/run.py",
         "sources/own-notes.txt", "sources/paper-0000.txt")

#: 台账三张表：`stmt:000004` 是自产（带一条第二证明），`stmt:000005` 是从文献摘的。
LEDGER: dict[str, list[dict]] = {
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


def _rows(*, lean: bool = True,
          main_target: str = "FreeGroupFactor.isII1",
          tail_target: str = "FreeGroupFactor.isSimple",
          main_file: str = LEAN_REL, tail_file: str = LEAN_REL) -> list[dict]:
    """三条干净的表行；`lean=True` 时两条定理行各带两格。"""
    rows: list[dict] = [
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
    if lean:
        rows[0]["lean_file"] = main_file
        rows[0]["lean_target"] = main_target
        rows[1]["lean_file"] = tail_file
        rows[1]["lean_target"] = tail_target
    return rows


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _workspace(root: pathlib.Path, *, rows: list[dict],
               tex: str = CLEAN_TEX, lean_source: str | None = LEAN_SOURCE) -> pathlib.Path:
    """造一个工作区：台账三张表 + 正文 + 包内真实文件 +（可选）Lean 产物 + 对应表三份。

    `lean_source=None` 时盘上一个 `.lean` 都没有（测"开关开着却没有产物"那一档）。
    """
    root = pathlib.Path(root)
    store = Store(root)
    store.init()
    for table, table_rows in LEDGER.items():
        path = root / "data" / str(PM.S.TABLES[table]["file"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["rows"] = [dict(row) for row in table_rows]
        _dump(path, doc)
    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / PM.PC.TEX_NAME).write_bytes(tex.encode("utf-8"))
    for rel in FILES:
        target = package / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture\n")
    if lean_source is not None:
        artifact = package / LEAN_REL
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(lean_source.encode("utf-8"))
    PM.write_package(root, [PM.Row(**dict(row)) for row in rows])
    return root


def _kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("problems") or []]


def _warn_kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("warnings") or []]


def _details(reading: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in reading.get("problems") or [])


def _lean(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    """显式钉这一条用例要跑在哪一档（套件默认钉成"开着"，见 `tests/conftest.py`）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1" if on else "0")


# ---------------------------------------------------------------- 1 开关关


def test_lean_off_leaves_both_cells_empty_and_the_reading_says_so(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关、也没有 Lean 产物 => pass，两格空，读数里读得出「未开 Lean」。"""
    _lean(monkeypatch, False)
    root = _workspace(tmp_path, rows=_rows(lean=False))
    got = PM.mapping_reading(root)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]
    assert got["lean_state"] == "off", got["lean"]
    assert got["lean"]["enabled"] is False
    assert "未开 Lean" in got["reason"], got["reason"]
    assert "未开 Lean" in got["lean"]["reason"], got["lean"]
    assert got["warnings"] == [], "开关关着时不该冒出'没有产物'那一条警告"
    # 两格在 json 里真的是空的（不许被渲染或解析顺手填上）
    json_path, md_path = PM.mapping_paths(root)
    rows, problems = PM.parse_rows(json.loads(json_path.read_text(encoding="utf-8")))
    assert problems == [], problems
    assert [(r.lean_file, r.lean_target) for r in rows[:2]] == [("", ""), ("", "")]
    # 人读的那一份恒中文；正文附录按论文语言出文（D-45）—— 这份夹具的正文是英文，
    # 所以附录里印的是英文占位。两处读到的都是"这一格不是空白"，只是语言不同。
    assert PM.LEAN_OFF_CELL in md_path.read_text(encoding="utf-8")
    appendix = PM.appendix_path(root).read_text(encoding="utf-8")
    assert PM.paper_language(root) == PM.PAPER_LANGUAGE_EN
    assert "(Lean off)" in appendix
    assert not re.search(r"[\u4e00-\u9fff]", appendix), \
        "英文论文的附录里混进了中文（D-45）"


# ---------------------------------------------------------------- 2 干净就过


def test_lean_on_with_a_real_declaration_passes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开、包里有 `.lean`、两条定理行都给了两格且名字真的在源码里 => pass。"""
    _lean(monkeypatch, True)
    root = _workspace(tmp_path, rows=_rows())
    got = PM.mapping_reading(root)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]
    assert got["lean_state"] == "on", got["lean"]
    assert got["lean"]["artifacts"] == [LEAN_REL], got["lean"]
    assert got["lean"]["target_kinds"] == ["theorem", "lemma", "proposition", "corollary"]
    assert got["warnings"] == [], got["warnings"]
    # 两格是逐字写进 json 的（写侧只走 `Row.to_dict` 那一个口）
    json_path, _md = PM.mapping_paths(root)
    rows, _problems = PM.parse_rows(json.loads(json_path.read_text(encoding="utf-8")))
    assert (rows[0].lean_file, rows[0].lean_target) == (LEAN_REL, "FreeGroupFactor.isII1")
    # 列也在：人读与附录里都读得到那个声明名
    assert "FreeGroupFactor.isII1" in PM.mapping_paths(root)[1].read_text(encoding="utf-8")
    assert "FreeGroupFactor.isII1" in PM.appendix_path(root).read_text(encoding="utf-8")
    assert MJ.level_of("mapping_lean_missing") == MJ.LEVEL_BLOCKER


# ---------------------------------------------------------------- 3 必填而缺


def test_a_theorem_row_without_lean_target_is_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开、有产物、某条定理行缺 `lean_target` => fail + `mapping_lean_missing`。"""
    _lean(monkeypatch, True)
    rows = _rows()
    rows[0].pop("lean_target")
    root = _workspace(tmp_path, rows=rows)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert _kinds(got) == ["mapping_lean_missing"], _details(got)
    assert "lean_target" in got["problems"][0]["detail"], got["problems"][0]["detail"]
    assert got["problems"][0]["label"] == "thm:main", got["problems"][0]
    # 拦门那一档：客观分档给 blocker，折出来的发现也是 blocker
    levels = [f["level"] for f in MJ.findings_of(got)
              if f["kind"] == "mapping_lean_missing"]
    assert levels == [MJ.LEVEL_BLOCKER], levels
    assert MJ.level_of("mapping_lean_missing") == MJ.LEVEL_BLOCKER


def test_a_row_that_fills_only_one_cell_is_also_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只填一格（填了 `lean_target` 而不说它在哪份源码里）同样是 `mapping_lean_missing`。"""
    _lean(monkeypatch, True)
    rows = _rows()
    rows[1].pop("lean_file")
    root = _workspace(tmp_path, rows=rows)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_lean_missing" in _kinds(got), _details(got)


# ---------------------------------------------------------------- 4 源码位置


def test_a_lean_file_outside_the_package_is_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`lean_file` 不存在 / 绝对路径 / 指到包外 / 不是 `.lean` 都红。"""
    _lean(monkeypatch, True)
    cases = {
        "不存在": {"lean_file": "formal/not-there.lean"},
        "绝对路径": {"lean_file": str(pathlib.Path(tmp_path) / "formal" / "000004.lean")},
        "包外": {"lean_file": "../000004.lean"},
        "不是 lean": {"lean_file": "formal/000004.txt"},
    }
    for i, (name, patch) in enumerate(cases.items()):
        rows = _rows()
        rows[0].update(patch)
        root = _workspace(tmp_path / f"case-{i}", rows=rows)
        got = PM.mapping_reading(root)
        assert got["state"] == "fail", (name, got["reason"])
        assert "mapping_lean_file_missing" in _kinds(got), (name, _details(got))
        assert MJ.level_of("mapping_lean_file_missing") == MJ.LEVEL_BLOCKER


# ---------------------------------------------------------------- 5 声明名


def test_a_lean_target_must_appear_in_that_file_by_word_boundary(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`foo` 不许命中源码里的 `fooBar`；换成真名字就干净（反例与正控成对）。"""
    _lean(monkeypatch, True)
    broken = _workspace(tmp_path / "broken", rows=_rows(main_target="FreeGroupFactor.foo"))
    got = PM.mapping_reading(broken)
    assert got["state"] == "fail", got["reason"]
    assert _kinds(got) == ["mapping_lean_target_missing"], _details(got)
    assert "FreeGroupFactor.foo" in got["problems"][0]["detail"], got["problems"][0]["detail"]
    assert "词边界" in got["problems"][0]["detail"], got["problems"][0]["detail"]
    assert MJ.level_of("mapping_lean_target_missing") == MJ.LEVEL_BLOCKER

    # 正控：同一个位置换成源码里真有的声明名 => 干净
    ok = _workspace(tmp_path / "ok", rows=_rows(main_target="FreeGroupFactor.fooBar"))
    assert PM.mapping_reading(ok)["problems"] == [], _details(PM.mapping_reading(ok))
    # 前缀也不算命中：`FreeGroupFactor.isII` 不许命中 `FreeGroupFactor.isII1`
    prefix = _workspace(tmp_path / "prefix",
                        rows=_rows(main_target="FreeGroupFactor.isII"))
    assert "mapping_lean_target_missing" in _kinds(PM.mapping_reading(prefix))


# ---------------------------------------------------------------- 6 没有产物


def test_lean_on_without_any_artifact_is_visible_and_not_silent(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开而盘上一个 Lean 产物都没有 => `lean_on_but_no_artifact` 必须看得见。

    这一档定成 warning（不动门）：它说的不是"表与正文对不上"（表本身可以完全干净），
    而是"这一趟的形式化一个文件都没落" —— 那件事由收工门的 `load_bearing` 与形式化门在管。
    但读数必须自己说出来：`lean_state`、`warnings`、`reason` 三处都要有，
    否则两格空白会被读成"验过了"。
    """
    _lean(monkeypatch, True)
    root = _workspace(tmp_path, rows=_rows(lean=False), lean_source=None)
    got = PM.mapping_reading(root)
    assert got["lean"]["enabled"] is True
    assert got["lean"]["artifacts"] == [], got["lean"]
    assert got["lean_state"] == "on_no_artifact", got["lean"]
    assert _warn_kinds(got) == ["lean_on_but_no_artifact"], got["warnings"]
    assert "lean_on_but_no_artifact" in got["reason"], got["reason"]
    assert "Lean 产物都没有" in got["reason"], got["reason"]
    # 这一档不改 state（表与正文本身没问题），但它绝不是"什么都没发生"
    assert got["state"] == "pass", got["reason"]
    assert got["problems"] == [], _details(got)
    # 分档：warning（看得见、但不动门的强度）
    assert MJ.level_of("lean_on_but_no_artifact") == MJ.LEVEL_WARNING
    warns = MJ.warnings_of(got)
    assert [w["kind"] for w in warns] == ["lean_on_but_no_artifact"], warns
    assert [w["level"] for w in warns] == [MJ.LEVEL_WARNING], warns
    assert MJ.findings_of(got) == [], "警告档不进拦门清单"


def test_an_artifact_outside_the_package_still_counts_as_lean_output(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`out/formal/` 下也有产物：那也算"有 Lean 产出"，两格因此必填。

    它今天也能直接填进 `lean_file`（项目根相对路径 `out/formal/000004.lean` —— 2026-10-25
    第 4 条把项目根加进解析面），而这条用例钉的是另一件事："产出在包外也不算没有产出"
    这个读数，不许静默放过。
    """
    _lean(monkeypatch, True)
    root = _workspace(tmp_path, rows=_rows(lean=False), lean_source=None)
    artifact = pathlib.Path(root) / "out" / "formal" / "000004.lean"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(LEAN_SOURCE.encode("utf-8"))
    got = PM.mapping_reading(root)
    assert got["lean_state"] == "on", got["lean"]
    assert "out/formal/000004.lean" in got["lean"]["artifacts"], got["lean"]
    assert got["warnings"] == [], got["warnings"]
    assert set(_kinds(got)) == {"mapping_lean_missing"}, _details(got)


# ---------------------------------------------------------------- 7 同一个目标


def test_the_same_lean_target_twice_is_ambiguous(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同一个 `lean_target` 被两行共用 => `mapping_lean_target_ambiguous`。

    允许两行共用一个 `lean_file`（一条命题多条证明时可以那样写），但那时两行的
    `lean_target` 必须各自不同 —— 否则"验的是第几号证明"这件事就说不清了。
    """
    _lean(monkeypatch, True)
    rows = _rows()
    rows[1]["lean_target"] = rows[0]["lean_target"]
    root = _workspace(tmp_path, rows=rows)
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert _kinds(got) == ["mapping_lean_target_ambiguous"], _details(got)
    assert "FreeGroupFactor.isII1" in got["problems"][0]["detail"], got["problems"][0]["detail"]
    assert "thm:main" in got["problems"][0]["detail"], got["problems"][0]["detail"]
    assert MJ.level_of("mapping_lean_target_ambiguous") == MJ.LEVEL_BLOCKER

    # 正控：同一个 `lean_file`、两个不同的 `lean_target` => 干净
    ok = _workspace(tmp_path / "ok", rows=_rows())
    assert PM.mapping_reading(ok)["problems"] == []


# ---------------------------------------------------------------- 8 反真空


def test_emptying_the_lean_kind_group_kills_that_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `LEAN_KINDS` 清空 => 第 3 条那条红必须消失。

    这一条是反真空：如果清空那组 kind 之后它还是红的，说明那条红并不靠这组 kind
    （而是靠一段顺手写死的判断），于是"词表一改就跟着变"这句话不成立，
    而后者正是本项目要求"判据与词表只有一处真身"的理由。
    """
    _lean(monkeypatch, True)
    rows = _rows()
    rows[0].pop("lean_target")
    root = _workspace(tmp_path, rows=rows)

    assert "mapping_lean_missing" in _kinds(PM.mapping_reading(root)), "改前得先是红的"

    monkeypatch.setattr(PM, "LEAN_KINDS", ())
    got = PM.mapping_reading(root)
    assert "mapping_lean_missing" not in _kinds(got), _details(got)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]

    # 还原那组 kind（monkeypatch 的回滚走 undo；这里手动回滚以证"红是真的靠它"）
    monkeypatch.undo()
    _lean(monkeypatch, True)
    assert "mapping_lean_missing" in _kinds(PM.mapping_reading(root)), _details(got)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
