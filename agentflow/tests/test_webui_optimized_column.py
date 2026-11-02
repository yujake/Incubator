# -*- coding: utf-8 -*-
"""命题台账的「是否优化」那一格：后端逐份读数 + 页面「优化」列（三态不折平）。

## 这一份守什么

业主 2026-11-03（goal 第 ⑤ 条）：网页端「命题台账」页要能看到"这一份证明洗过没有"。
盘上那一格已经有唯一读口（`evidencebits.optimized_by_proof` / `optimized_state`），
三态在 `evidencebits.OPTIMIZED_STATES` 里定死了（`true` / `false` / `not_recorded`），
缺的只是**网页端**这一路：读模型没把那一格吐出来，页面上也没有那一列。

于是这份判据钉三件事（与任务 ④ 的 a / b / c 一一对应）：

| # | 钉的是 | 改前红在哪 |
|---|---|---|
| a | 造 `{"1": true, "2": false}` ⇒ 两条分别读成 `true` / `false`，页面上是「已优化」「未优化」 | `_TS_TYPES` 里没有 `optimized_paths`，`evidence_chain` 的行上没有这一格；页面上没有「优化」列 |
| b | 造缺格（`bits.evidence` 里根本没有 `optimized_by_proof`）⇒ 逐份是 `not_recorded`，页面写「未记录」 | 同上；另一种错法是把它折成 `false` ⇒ 页面写「未优化」 |
| c | 反真空：把读口 `evidencebits.optimized_by_proof` 打桩成恒 `true` ⇒ a 那个判据函数必须报 | 改前 a 根本没有读数可打桩（读不到 `optimized_paths`） |

## 为什么逐份的编号取自四张表的并集

`optimized_by_proof` 只回答"记过的那几份各是什么"——缺格的那一份**不在表里**。
只看这张表，判据 b 那一档（这一份还没记）就会从屏幕上消失，而那正是要显示的一档。
所以逐份的编号取自 `reviewed_by_proof` / `reviewed_sha_by_proof` /
`optimized_by_proof` / `formal_by_proof` 四张同形表的并集：任一张认得这一份，
这一份就在命题台账里占一行 —— 「优化」与签过 / 验过的那几格按 `proof_no` 逐份并排，
缺哪一格就写哪一档，不借相邻那一份的光。

## 边界（这一份刻意不测什么）

- 不测 `evidencebits` 的读口语义（那一层已有 `tests/test_two_stage_intake_optimized.py`
  等判据；本批只搬运）。
- 不测 `papermapping` 那张对应表的同名列（另一批已落地）。
- 页面判据读源码字面量、后端判据真读盘上的 `statements` 表：两头都比，
  只改一头是红不了的（判据自己的负控见 `_page_problems` 与 `_two_state_problems`）。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
EVIDENCE_TSX = UI_SRC / "pages" / "Evidence.tsx"

#: 夹具里的时间戳（`schema.Statement.created_at` 只要求是个字符串）。
TS = "2026-11-03T00:00:00+08:00"

#: 页面上的三档词（逐字，与 `papermapping.OPTIMIZED_*` 同词；后端给的是
#: `evidencebits.OPTIMIZED_STATES` 的三个 token，映射只在页面那一处）。
OPTIMIZED_WORDS: tuple[str, ...] = ("已优化", "未优化", "未记录")

#: 逐条签那一张表（与验收表同形：`#p1` 签过、`#p2` 没签）—— 它让"四张表的并集"
#: 这件事在夹具上真的有两个证明号，而不是只有 optimized 那一张自说自话。
_BITS_REVIEWED: dict[str, Any] = {
    "reviewed_by_proof": {"1": True, "2": False},
    "reviewed_sha_by_proof": {"1": "a" * 64},
}


# ====================================================================== 夹具
def _write_json(path: pathlib.Path, doc: object) -> None:
    """按 UTF-8 / LF 写一份 JSON（与仓库里其它夹具的写法同一条口径）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _statement_ws(tmp_path: pathlib.Path, evidence: dict[str, Any] | None,
                  *, bits_missing: bool = False) -> pathlib.Path:
    """造一个只有一行命题的工作区（`bits.evidence` 由调用方决定）。"""
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    row: dict[str, Any] = {
        "stmt_id": "000001", "origin": "own_result", "kind": "theorem",
        "statement_text": "偶数平方仍是偶数", "statement_full": "对任意整数 n，n² 为偶数当且仅当 n 为偶数。",
        "proof_text": "", "created_by": "B", "created_at": TS,
    }
    if not bits_missing:
        row["bits"] = {
            "numeric": "pending", "proof": True, "reviewed": True,
            "formal": {"1": "verified", "2": "pending"}, "audited": False,
            "evidence": dict(evidence or {}),
        }
    _write_json(root / "data" / S.TABLES["statements"]["file"],
                {"schema_version": S.SCHEMA_VERSION, "rows": [row]})
    return root


@pytest.fixture()
def ws_two_states(tmp_path: pathlib.Path) -> pathlib.Path:
    """判据 a：优化态 `{"1": true, "2": false}`（与任务里点名的那一份逐字同形）。"""
    return _statement_ws(tmp_path, {**_BITS_REVIEWED,
                                    "optimized_by_proof": {"1": True, "2": False}})


@pytest.fixture()
def ws_missing_cell(tmp_path: pathlib.Path) -> pathlib.Path:
    """判据 b：缺格 —— `evidence` 里有逐条签的两张表，就是**没有** `optimized_by_proof`。"""
    return _statement_ws(tmp_path, dict(_BITS_REVIEWED))


# ====================================================================== 后端那一半
def _statement(ws: pathlib.Path) -> dict[str, Any]:
    """这一份工作区里唯一的命题行（读模型给的那一行）。"""
    rows = R.evidence_chain(ws)["statements"]
    assert len(rows) == 1, rows
    return rows[0]


def _two_state_problems(rows: list[dict[str, Any]]) -> list[str]:
    """判据 a 的纯函数：两条证明分别读成 `true` / `false`（页面上是两档词）。

    返回问题清单（空 = 这一条成立）—— 抽成纯函数是为了让反真空 c 能拿一份
    "打桩之后的行"直接喂它，而不是再去信一次读盘。
    """
    problems: list[str] = []
    if not rows:
        return ["一条命题行都没有读出来（判据失去对象）"]
    got = rows[0].get("optimized_paths")
    if not isinstance(got, list):
        return [f"命题行上没有 optimized_paths 这一格：{got!r}"]
    want = [{"proof_no": 1, "state": "true"}, {"proof_no": 2, "state": "false"}]
    if got != want:
        problems.append(f"逐份优化态不是 {want}，而是 {got}")
    return problems


def _missing_cell_problems(rows: list[dict[str, Any]]) -> list[str]:
    """判据 b 的纯函数：缺格 ⇒ 两条都是 `not_recorded`（不是 `false`）。"""
    problems: list[str] = []
    if not rows:
        return ["一条命题行都没有读出来（判据失去对象）"]
    got = rows[0].get("optimized_paths")
    if not isinstance(got, list):
        return [f"命题行上没有 optimized_paths 这一格：{got!r}"]
    states = [row.get("state") for row in got if isinstance(row, dict)]
    if states != ["not_recorded", "not_recorded"]:
        problems.append(f"缺格没有读成 not_recorded，而是 {states}")
    if any(state == "false" for state in states):
        problems.append("缺格被折成了 false（页面会写成「未优化」）")
    return problems


def test_a_two_proofs_read_true_and_false(ws_two_states: pathlib.Path) -> None:
    """判据 a（后端）：`{"1": true, "2": false}` ⇒ 两条分别是 `true` / `false`。"""
    rows = R.evidence_chain(ws_two_states)["statements"]
    assert _two_state_problems(rows) == [], _two_state_problems(rows)
    # 三态 token 与页面上的词是两件事：这里只钉"后端给的是 token"，
    # 词在页面那一半（`_page_problems`）。
    assert [row["state"] for row in rows[0]["optimized_paths"]] == ["true", "false"], (
        rows[0]["optimized_paths"])


def test_b_a_missing_cell_is_not_recorded_not_false(ws_missing_cell: pathlib.Path) -> None:
    """判据 b（后端）：缺格 ⇒ `not_recorded`（不是 `false`）。"""
    rows = R.evidence_chain(ws_missing_cell)["statements"]
    assert _missing_cell_problems(rows) == [], _missing_cell_problems(rows)


def test_b_a_row_with_no_proof_tables_at_all_is_not_recorded(
        tmp_path: pathlib.Path) -> None:
    """判据 b 的边界：连逐条签那两张表都没有 ⇒ 没有证明号可列，但也不许写「未优化」。

    这一档是"说不出是哪一份"：页面回退成一句带说明的「未记录」，而不是一条假的
    「#p1 未优化」。
    """
    ws = _statement_ws(tmp_path, None, bits_missing=True)
    row = _statement(ws)
    assert row["optimized_paths"] == [], row["optimized_paths"]
    assert "未记录（这一条没有逐证明的记录" in _page_body(), (
        "页面没有为『没有逐证明记录』那一档写一句「未记录」")


# ====================================================================== 页面那一半
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _strip_js_comments(text: str) -> str:
    """剥掉块注释与整行注释（注释上不了屏，判据只看会渲染的部分）。"""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _page_body() -> str:
    """`Evidence.tsx` 剥过注释的正文（页面不在盘上 ⇒ 判据失去对象，直接红）。"""
    assert EVIDENCE_TSX.is_file(), f"{EVIDENCE_TSX} 不在盘上（证据链页还没落地）"
    return _strip_js_comments(EVIDENCE_TSX.read_text(encoding="utf-8"))


def _page_problems(source: str) -> list[str]:
    """判据 a / b 的页面那一半：有「优化」列，三档词都在，且按证明逐份读 `state`。

    纯函数：负控喂改前那一段源码（没有这一列）就能证明它会报。
    """
    body = _strip_js_comments(source)
    problems: list[str] = []
    if "optimized_paths" not in body:
        problems.append("Evidence 页没有读 optimized_paths（优化那一格没有读数）")
    if 'title: "优化"' not in body:
        problems.append("命题台账没有「优化」这一列")
    for word in OPTIMIZED_WORDS:
        if f'"{word}"' not in body:
            problems.append(f"页面上没有「{word}」这一档")
    if "p.state" not in body:
        problems.append("优化那一格没有按证明逐份读 state（折成一句汇总了？）")
    if "p.proof_no" not in body:
        problems.append("优化那一格没有按证明逐份印证明号（看不出是哪一份）")
    return problems


def test_a_the_page_shows_the_two_words() -> None:
    """判据 a（页面）：读那一格、列名「优化」、两档词在。"""
    assert _page_problems(_page_body()) == [], _page_problems(_page_body())


def test_b_the_page_says_not_recorded_not_unoptimized() -> None:
    """判据 b（页面）：三档词齐全（「未记录」不是「未优化」），回退那一句写「未记录」。"""
    body = _page_body()
    assert "未记录" in body, body
    assert "这是「未记录」那一档" in body or "说不出是哪一份" in body, (
        "页面没有把『没有逐证明记录』与『未优化』分开")
    problems = _page_problems(body.replace('"未记录"', '"未优化"'))
    assert problems, "把「未记录」换成「未优化」之后，页面判据居然不报"


def test_a_negative_control_a_page_without_the_column_is_reported() -> None:
    """反真空（页面）：改前那种只有 reviewed 列、没有「优化」列的写法 ⇒ 必须报。"""
    old = """
      columns={[
        { key: "reviewed_paths", title: "第 3 位·reviewed（按证明）", render: (r) => reviewedCell(r) },
      ]}
    """
    problems = _page_problems(old)
    assert problems, "没有「优化」列的页面居然通过了"
    assert any("优化" in p for p in problems), problems


# ====================================================================== 判据 c（反真空 · 后端）
def test_c_stubbing_the_reading_to_constant_true_makes_a_red(
        ws_two_states: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 c：把读口 `optimized_by_proof` 打桩成恒 true ⇒ 判据 a 必须红。

    为什么打这一层而不是 `optimized_state`：`optimized_state` 是唯一读口，
    它内部读的就是这张表 —— 把**表**打桩，测的是"读模型真的经那个读口取数"
    这件事本身；只打 `optimized_state` 会把"读模型自己另判了一次"这种错放过。
    """
    before = R.evidence_chain(ws_two_states)["statements"]
    assert _two_state_problems(before) == [], _two_state_problems(before)

    monkeypatch.setattr(EB, "optimized_by_proof",
                        lambda row: {1: True, 2: True}, raising=True)
    after = R.evidence_chain(ws_two_states)["statements"]
    problems = _two_state_problems(after)
    assert problems, "读口打桩成恒 true 之后，判据 a 居然还绿着（读数没走那个读口）"
    assert any("false" in p for p in problems), problems
