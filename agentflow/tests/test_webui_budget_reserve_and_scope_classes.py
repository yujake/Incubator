"""判据：预算页必须看得见「为什么停了」与「账本行是三类，不是调用总数」。

## 三件事、三个来源

1. 收工储备线（M 自设 $1.00）：`budget.PAPERWORK_RESERVE_USD`。M 按它叫停时
   （`stopctl` 那句「按预算保留线叫停」），页面上若只有"剩余 1.32"这一个数，
   读的人读不出"为什么停"。所以 `budget_face()` 读的是
   `budget.paperwork_first_reading()`（多给 `reserve_usd` / `below_reserve` /
   `note` / `paperwork_first_rule`），不是 `budget.reading()`。
2. 账本行 = `reason` + `summon` + `extract` 三类（真机 lp-ball-10 是
   1200 + 55 + 0 = 1255 行），不是 `llm_call` 总数：一次调用可能记 0..n 行。
   读数来源只有一个：`tokenmeter.by_scope()`（六个 `USAGE_SCOPES` 档 +
   `unclassified`，零值档也出现）。
3. 无人认领那笔钱按会话口径：`sessions.unattributed_usd_of()` —— 与
   `/api/state` 的 `sessions[].unattributed_usd`、收工面
   `closing.cost.unattributed_usd` 同一个函数。会话读不出来 ⇒ `None`，不是 0。

## 反真空

- 负控一：`budget.reading()` 里没有 `reserve_usd`（阈值只在
  `paperwork_first_reading()` 那一份）⇒ 谁把 `budget_face` 退回 `reading()`，
  这一格当场变成"键不在"，判据红。
- 负控二：把余额花到储备线以下 ⇒ `below_reserve` 必须是 `True` 且 `note` 里
  出现「低于收工储备线」（不是永远 False）。
- 负控三：页面源码里三类归口少写一个（extract）⇒ 页面判据当场报。

## 量法

不替预算模块再写一份阈值或算术：本判据 import `budget` 与 `webui.readers`，
阈值直接与 `PAPERWORK_RESERVE_USD` 比，无人认领直接与会话函数比。
"""
from __future__ import annotations

import json
import pathlib
import re

from agentflow import budget as B
from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.webui import readers as RD

REPO = pathlib.Path(__file__).resolve().parents[1]
BUDGET_TSX = REPO / "ui" / "src" / "pages" / "Budget.tsx"


def _ws(tmp_path: pathlib.Path, *, scopes: tuple[str, ...], total: float = 5.0,
        per_row_usd: float = 0.5) -> pathlib.Path:
    """一个最小工作区：`budget.json` + `data/usage_ledger.json`（只有这几行）。"""
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    rows = [
        {"usage_id": f"{i:06d}", "scope": scope, "role": "B", "task_id": "t-000001",
         "usd": per_row_usd, "tokens_total": 100, "attempts": 1,
         "at": "2026-11-19T00:00:00+08:00", "idem_key": f"idem-{i}"}
        for i, scope in enumerate(scopes)
    ]
    (tmp_path / "data" / "usage_ledger.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": rows},
                   ensure_ascii=False),
        encoding="utf-8")
    (tmp_path / "budget.json").write_text(
        json.dumps({"total_usd": total, "added": []}, ensure_ascii=False),
        encoding="utf-8")
    return tmp_path


def test_the_reserve_line_is_the_budget_modules_number(tmp_path: pathlib.Path) -> None:
    """正控：储备线与阈值逐字相等；余额在阈值之上 ⇒ `below_reserve=False`。"""
    root = _ws(tmp_path, scopes=("reason", "reason", "summon", "extract"))
    face = RD.budget_face(root)
    assert face["reserve_usd"] == B.PAPERWORK_RESERVE_USD, face["reserve_usd"]
    assert face["below_reserve"] is False, face
    assert face["remaining_usd"] == 3.0, face
    assert face["note"], "note 是空的 ⇒ 页面又只剩一个数字，读不出为什么停"
    assert "储备线" in face["note"], face["note"]
    assert face["paperwork_first_rule"] == B.PAPERWORK_FIRST_RULE, face["paperwork_first_rule"]


def test_the_reserve_line_flips_when_the_money_runs_low(tmp_path: pathlib.Path) -> None:
    """负控（反真空）：花到储备线以下 ⇒ `below_reserve=True` 且 note 说清。"""
    # 4 行 × $1.05 = $4.20，总额 $5.00 ⇒ 只剩 $0.80 < $1.00。
    root = _ws(tmp_path, scopes=("reason", "reason", "summon", "extract"),
               per_row_usd=1.05)
    face = RD.budget_face(root)
    assert face["remaining_usd"] is not None and face["remaining_usd"] < B.PAPERWORK_RESERVE_USD
    assert face["below_reserve"] is True, face
    assert "低于收工储备线" in face["note"], face["note"]


def test_the_reading_without_the_reserve_line_is_really_gone() -> None:
    """负控：`budget.reading()` 没有 `reserve_usd` —— 退回它，前面几条就失去对象。"""
    assert "reserve_usd" not in B.reading(".", spent_usd=0.0)
    assert "reserve_usd" in B.paperwork_first_reading(".", spent_usd=0.0)


def test_the_ledger_rows_are_three_classes_not_a_call_total(tmp_path: pathlib.Path) -> None:
    """正控：账本 4 行 = reason 2 + summon 1 + extract 1；零值档也在。"""
    root = _ws(tmp_path, scopes=("reason", "reason", "summon", "extract"))
    face = RD.budget_face(root)
    assert face["entries"] == 4, face
    scope = face["by_scope"]
    assert set(scope) == set(S.USAGE_SCOPES) | {S.SCOPE_UNCLASSIFIED}, sorted(scope)
    assert scope["reason"]["entries"] == 2, scope["reason"]
    assert scope["summon"]["entries"] == 1, scope["summon"]
    assert scope["extract"]["entries"] == 1, scope["extract"]
    # 零值档必须出现（"查过、没花钱"与"没有这个归口"是两件事）。
    for name in S.USAGE_SCOPES:
        assert name in scope, (name, sorted(scope))


def test_unattributed_money_is_the_session_caliber(tmp_path: pathlib.Path) -> None:
    """正控 + 三态：没有会话 ⇒ 0.0；会话读不出来 ⇒ None + 原因（不是 0）。"""
    root = _ws(tmp_path, scopes=("reason",))
    face = RD.budget_face(root)
    assert face["unattributed_usd"] == SS.unattributed_usd_of([], []), face
    assert face["unattributed_reason"] == "", face
    assert "会话口径" in face["unattributed_source"], face["unattributed_source"]
    # 负控：一份坏字节的会话文件 ⇒ read_all_sessions 判没查成 ⇒ 这一格 None。
    (root / "sessions").mkdir()
    (root / "sessions" / "2026-11-20.jsonl").write_bytes(b"\xff\xfe not utf8\n")
    broken = RD.budget_face(root)
    assert broken["unattributed_usd"] is None, broken["unattributed_usd"]
    assert broken["unattributed_reason"] != "", broken


#: 预算页必须读到的几格（源码层；本仓没有 JS 测试设施，页面那一半按源码判）。
#: 认的是"真的去读那一格"的表达式，不是字面词 —— 否则把读法删掉、只留一句
#: 展示文字也能让判据绿（负控就是钉这件事的）。
_PAGE_MUST_HAVE = (
    "b.reserve_usd",
    "b.below_reserve",
    "b.note",
    'scopeEntries("reason")',
    'scopeEntries("summon")',
    'scopeEntries("extract")',
    "b.unattributed_usd",
    "不是 llm_call 总数",
)


def _page_problems(source: str) -> list[str]:
    """纯函数（可负控）：预算页有没有把储备线 / 三类账本行 / 无人认领写给读的人。

    只看代码：块注释与行注释先剥掉 —— 否则"注释里写了 extract、代码里没写"
    也能让这一条绿（负控就是钉这件事的）。
    """
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    at = code.find("预算")
    if at < 0:
        return ["页面里没有预算卡"]
    region = code[at:]
    return [f"预算页没有读/写 `{name}`" for name in _PAGE_MUST_HAVE if name not in region]


def test_the_page_shows_the_reserve_line_and_the_three_classes() -> None:
    """页面那一半：储备线 / 三类账本行 / 无人认领都上屏；负控能抓住缺一类。"""
    source = BUDGET_TSX.read_text(encoding="utf-8")
    assert _page_problems(source) == [], _page_problems(source)
    doctored = source.replace('scopeEntries("extract")', 'scopeEntries("nothing")', 1)
    assert doctored != source, "负控没改到源码"
    assert any("extract" in p for p in _page_problems(doctored)), _page_problems(doctored)
