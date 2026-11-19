"""判据：坏 JSONL 行要在页面上说清「哪几行读不出来」，空/缺表不许白屏。

## 业主的两条口径（2026-11-19 对齐第 ⑨ 项 / 鲁棒 a、b）

1. 会话只有一份 `sessions/<sid>.jsonl`；读不出来的行要显示成
   「第 A–B 行读不出来（N 行）」，不许空白、不许整页报错，其余行照常显示。
   行界口径必须与后端同一份实现（`jsonlfile.read_jsonl_state` 只按 `\\n` 切；
   `str.splitlines()` 会把 U+0085 等 Unicode 行界也切断 —— 真机 lp-ball-10 的
   8 条合法行曾被切成 90 段）。
2. 空工作区 / 只有部分表：不 500，显示「还没有这张表」，不是
   「读到了、里面是 0 行」。

## 判据的三半

- 后端：`snapshot()` 的 `sessions[].bad_line_notes` 逐字给出后端那几句
  （连续同因的一整段折成一条「第 A–B 行…（N 行；首条：…）」）；
- 行界：U+0085 那一行算一条事件（`events_seen`），不是三条碎片；
- 页面：Home 的会话概览读 `bad_line_notes`；Evidence / Artifacts 对
  `not_applicable` 说「还没有这张表」。

反真空（三条负控）：

- 把两条连续坏行改成两条不同死因 ⇒ 说明"折段"不是把不同原因也吞进去；
- 页面源码把 `bad_line_notes` 换成 `bad_lines` ⇒ 页面判据必须红（只给条数
  说不出"哪几行"）；
- Evidence 把 `not_applicable` 那一支删掉 ⇒ 页面判据必须红。
"""
from __future__ import annotations

import json
import pathlib
import re

from agentflow import schema as S
from agentflow.webui import readers as RD
from agentflow.webui import state as ST

REPO = pathlib.Path(__file__).resolve().parents[1]
HOME_TSX = REPO / "ui" / "src" / "pages" / "Home.tsx"
EVIDENCE_TSX = REPO / "ui" / "src" / "pages" / "Evidence.tsx"
ARTIFACTS_TSX = REPO / "ui" / "src" / "pages" / "Artifacts.tsx"


def _event(seq: int, *, note: str = "") -> str:
    row = {"seq": seq, "ts": f"2026-11-19T00:00:0{seq}+08:00", "kind": "heartbeat"}
    if note:
        row["note"] = note
    return json.dumps(row, ensure_ascii=False)


def _session(root: pathlib.Path, lines: list[str], sid: str = "2026-11-20") -> None:
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "sessions" / f"{sid}.jsonl").write_text("\n".join(lines) + "\n",
                                                    encoding="utf-8")


def test_bad_lines_are_a_range_not_a_blank(tmp_path: pathlib.Path) -> None:
    """正控：两条连续坏行 ⇒ 一条「第 2–3 行读不出来（2 行；首条：…）」。

    `bad_lines` 数的是「坏行说明」的条数（后端折段之后是 1 条），物理行数写在
    那条说明的括号里 —— 两个数不许互相顶替。
    """
    _session(tmp_path, [_event(1), "{not json", "{still not json", _event(2)])
    snap = ST.snapshot(tmp_path)
    assert len(snap["sessions"]) == 1, snap["sessions"]
    row = snap["sessions"][0]
    assert row["bad_lines"] == 1, row
    assert len(row["bad_line_notes"]) == 1, row["bad_line_notes"]
    note = row["bad_line_notes"][0]
    assert note.startswith("第 2–3 行读不出来（2 行；首条："), note
    # 其余照常读：两条合法事件都在，且问题清单里也带同一句（整页"没查成"那一卡）。
    assert row["events_seen"] == 2, row
    assert any("第 2–3 行读不出来" in p for p in snap["problems"]), snap["problems"]


def test_two_different_causes_are_not_merged(tmp_path: pathlib.Path) -> None:
    """负控：不同死因不合并（"不是对象"不许被吞进 JSON 语法错误里）。"""
    _session(tmp_path, [_event(1), "{not json", "[1, 2, 3]", _event(2)])
    row = ST.snapshot(tmp_path)["sessions"][0]
    assert row["bad_lines"] == 2, row
    assert any("第 2 行读不出来" in n for n in row["bad_line_notes"]), row["bad_line_notes"]
    assert any("第 3 行不是对象" in n for n in row["bad_line_notes"]), row["bad_line_notes"]


def test_u0085_does_not_split_a_valid_line(tmp_path: pathlib.Path) -> None:
    """行界口径：含 U+0085 的合法 JSON 行算一条事件，不是三条碎片。"""
    _session(tmp_path, [_event(1, note="a\u0085b\u0085c"), _event(2)])
    row = ST.snapshot(tmp_path)["sessions"][0]
    assert row["bad_lines"] == 0, row
    assert row["bad_line_notes"] == [], row
    assert row["events_seen"] == 2, row


def test_an_empty_workspace_does_not_500_and_says_there_is_no_table(
        tmp_path: pathlib.Path) -> None:
    """负控（b）：空工作区上每一面都读得出来，表缺是 not_applicable，不是 0 行。"""
    snap = ST.snapshot(tmp_path)
    assert snap["sessions"] == [] and snap["problems"] == [], snap
    ev = RD.evidence_chain(tmp_path)
    trises = {k: v for k, v in ev.items() if k.endswith("_tri")}
    assert trises, ev
    assert set(trises.values()) == {"not_applicable"}, trises
    art = RD.artifacts_face(tmp_path)
    assert art["tri"] == "not_applicable", art["tri"]
    # 负控：同一个空工作区上拿"只落了一张表"的现场再读一次 —— 别的表照旧
    # not_applicable，落过的那一张才是 computed（不许把"有这张表"与"没这张表"读成同一档）。
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "statements.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": []}), encoding="utf-8")
    ev2 = RD.evidence_chain(tmp_path)
    assert ev2["statements_tri"] != "not_applicable", ev2["statements_tri"]
    assert ev2["conjectures_tri"] == "not_applicable", ev2["conjectures_tri"]


#: Home 会话概览必须读的那一格（不是只读条数）。
def _home_problems(source: str) -> list[str]:
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    at = code.find("会话概览")
    if at < 0:
        return ["页面里没有会话概览"]
    region = code[at:at + 5000]
    problems: list[str] = []
    if "bad_line_notes" not in region:
        problems.append("会话概览没有读 bad_line_notes（只给条数说不出哪几行）")
    if "第 A–B 行" not in region and "哪几行" not in region:
        problems.append("会话概览没有把「哪几行读不出来」说给读的人")
    return problems


def _missing_table_problems(source: str, *, page: str) -> list[str]:
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    return [] if "还没有这张表" in code else [f"{page} 没有把 not_applicable 说成「还没有这张表」"]


def test_the_page_shows_the_bad_line_ranges_and_the_missing_table_words() -> None:
    """页面那一半：Home 说清哪几行；Evidence / Artifacts 说「还没有这张表」。"""
    home = HOME_TSX.read_text(encoding="utf-8")
    assert _home_problems(home) == [], _home_problems(home)
    for path, page in ((EVIDENCE_TSX, "Evidence"), (ARTIFACTS_TSX, "Artifacts")):
        text = path.read_text(encoding="utf-8")
        assert _missing_table_problems(text, page=page) == [], _missing_table_problems(
            text, page=page)
    # 负控一：Home 退回只读条数 ⇒ 必须报。
    doctored = home.replace("bad_line_notes", "bad_lines")
    assert any("bad_line_notes" in p for p in _home_problems(doctored)), _home_problems(doctored)
    # 负控二：Evidence 删掉「还没有这张表」⇒ 必须报。
    ev = EVIDENCE_TSX.read_text(encoding="utf-8")
    assert _missing_table_problems(ev.replace("还没有这张表", ""), page="Evidence"), (
        "负控没改到源码")
