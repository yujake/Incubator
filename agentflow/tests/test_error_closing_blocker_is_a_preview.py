# -*- coding: utf-8 -*-
"""「现算预演」这一档的判据（业主 2026-11-20：这一栏不许被读成「M 想收工 N 次」）。

`closing_blocker` 的数不是"发生过几次错误动作"，而是"以此刻盘面看，现在收工会被什么拦"：
`errorstats._read_closing` 每读一次现算一次（`closing.check_closing`），不累加、不随历史增长。
它此前与真正的发生次数同列在一张表里，页面上会被读成"M 想收工 N 次"。

这一组钉四件事：

| 判据 | 查什么 |
|---|---|
| a 标记 | `readouts.errors_readout()` 的 `data.classes[]` 里 closing_blocker 带 `computed: true`；其它类一行都不带；它也不许进"发生次数"那张 `categories` 表 |
| b 释义 | `SYSTEM_CATEGORIES` 里 closing_blocker 那一句写明「现算预演 / 不是发生过的动作 / 不计入发生次数」 |
| c 页面 | `RoleErrors.tsx` 读那个标记、把这一类单独成组（独立一张表，计数列不叫「条数」） |
| d 正控 | 标记不许动真·发生次数：把 `computed` 剥掉之后，`classes` 与"标记关掉"那一份逐字节相同（计数 / 排序 / 每个格都不许变） |

反真空：标记打桩掉 ⇒ a 必红；释义里删掉「预演」⇒ b 必红；页面里删掉分组或删掉角标 ⇒ c 必红。
每一条负控都从盘上真实的源码/常量出发去破坏，不在判据里另写一份期望值。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import errorstats as ES
from agentflow import readouts as RD

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
ROLE_ERRORS_TSX = REPO / "ui" / "src" / "components" / "RoleErrors.tsx"

#: 事件流里那三行被拒/失败的任务（每个角色撞上不同的一类判据）。
_EVENT_ROWS: tuple[dict[str, Any], ...] = (
    {"task_id": "t-000001", "role": "B", "called_by": "M",
     "outcome": "refused", "refusal_reason": "forbidden_edge"},
    {"task_id": "t-000002", "role": "B", "outcome": "refused",
     "refusal_reason": "缺少必填参数"},
    {"task_id": "t-000003", "role": "F", "outcome": "failed",
     "refusal_reason": "direct_write_refused"},
)

#: 会话记录里那两行（工具层拒信 + 判据层坏 JSON）。
_STEP_ROWS: tuple[dict[str, Any], ...] = (
    {"kind": "agent_step", "role": "A", "result": {"error": "参数错误：x"}},
    {"kind": "llm_call", "role": "D", "problem": "judge_bad_json"},
)


def _write_ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """造一个既有"发生过的错误动作"、又有"此刻收工 blocker"的工作区。

    `out/` 必须在：`_read_closing` 只在有产物的工作区上现算收工门（没有 `out/` 是
    `not_applicable`）—— 那样夹具里就没有 closing_blocker，判据失去对象。
    """
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    (root / "sessions").mkdir()
    (root / "out").mkdir()
    events = [{"table": "tasks", "op": "upsert", "row": row} for row in _EVENT_ROWS]
    (root / "data" / "events.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    (root / "sessions" / "B-1.jsonl").write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in _STEP_ROWS),
        encoding="utf-8")
    return root


def _read(root: pathlib.Path) -> dict[str, Any]:
    api = RD.errors_readout(root)
    assert api["state"] == "checked", api
    return api


def _row(api: dict[str, Any], category: str) -> dict[str, Any] | None:
    return next((one for one in api["data"]["classes"] if one["category"] == category), None)


def _expected_preview() -> set[str]:
    """标记的期望集合 = 真身常量（不许在判据里另写一份类目名）。"""
    return set(getattr(ES, "PREVIEW_CATEGORIES", frozenset()))


# ====================================================================== a 标记
def _marker_problems(api: dict[str, Any], expect: set[str]) -> list[str]:
    """`computed` 标记是不是恰好落在 `expect` 这几个类目上（空 = 合格）。"""
    problems: list[str] = []
    rows = api["data"]["classes"]
    marked = {one["category"] for one in rows if one.get("computed") is True}
    if marked != expect:
        problems.append(f"带 computed=true 的类目是 {sorted(marked)}，应为 {sorted(expect)}")
    for one in rows:
        if one["category"] not in expect and "computed" in one:
            problems.append(f"{one['category']} 也带了 computed（它不是现算预演）")
    closing = _row(api, "closing_blocker")
    if closing is None or closing.get("computed") is not True:
        problems.append("closing_blocker 那一行没有 computed=true")
    return problems


def test_a_the_api_marks_closing_blocker_as_computed_preview(tmp_path: pathlib.Path) -> None:
    """a 正控：API 里 closing_blocker 带 `computed` 标记，其它类不带。"""
    api = _read(_write_ws(tmp_path))
    # 反真空：夹具必须真的有数（5 条发生过的错误动作 + 2 条此刻的 blocker）
    assert api["data"]["total"] == 5, api["data"]
    closing = _row(api, "closing_blocker")
    assert closing is not None and closing["count"] >= 1, closing
    expect = _expected_preview()
    assert "closing_blocker" in expect, (
        "errorstats.PREVIEW_CATEGORIES 里没有 closing_blocker —— 标记没有真身")
    assert _marker_problems(api, expect) == [], _marker_problems(api, expect)
    # 它也不许混进"发生次数"那张表（`categories` 只数错误动作）
    assert "closing_blocker" not in api["data"]["categories"], api["data"]["categories"]
    # 而它在系统侧读数里仍然看得见（不是被删掉，是被标出来）
    assert api["data"]["system"].get("closing_blocker") == closing["count"], api["data"]["system"]


def test_a_stubbing_the_marker_off_makes_the_check_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e 反真空（标记）：把 `PREVIEW_CATEGORIES` 打桩成空 ⇒ a 的标记判据必红。"""
    root = _write_ws(tmp_path)
    expect = _expected_preview()
    assert expect, "反真空：真身常量本来就是空的，a 无从被判红"
    monkeypatch.setattr(ES, "PREVIEW_CATEGORIES", frozenset(), raising=False)
    api = _read(root)
    problems = _marker_problems(api, expect)
    assert problems, "标记被打桩掉之后 a 仍绿 ⇒ a 比的不是标记"
    assert any("closing_blocker" in one for one in problems), problems


# ====================================================================== b 释义
def _gloss_problems(gloss: str) -> list[str]:
    """类目释义是不是写清了"这是现算预演、不是发生次数"（空 = 合格）。"""
    problems: list[str] = []
    if "现算预演" not in gloss:
        problems.append("closing_blocker 的释义没有『现算预演』四个字")
    if "不是发生过的动作" not in gloss:
        problems.append("closing_blocker 的释义没有写明『不是发生过的动作』")
    if "不计入" not in gloss or "发生次数" not in gloss:
        problems.append("closing_blocker 的释义没有写明『不计入……发生次数』")
    return problems


def test_b_the_gloss_says_it_is_a_preview_not_an_occurrence_count() -> None:
    """b 正控：类目释义里写明这是现算预演、不是发生过的动作。"""
    gloss = dict(ES.SYSTEM_CATEGORIES).get("closing_blocker", "")
    assert gloss, "SYSTEM_CATEGORIES 里没有 closing_blocker 那一条释义"
    assert _gloss_problems(gloss) == [], _gloss_problems(gloss)


def test_b_removing_the_preview_words_makes_the_gloss_check_red() -> None:
    """e 反真空（释义）：把释义里的「预演」删掉 ⇒ b 必红。"""
    gloss = dict(ES.SYSTEM_CATEGORIES).get("closing_blocker", "")
    assert _gloss_problems(gloss) == [], _gloss_problems(gloss)
    for broken in (gloss.replace("现算预演", "收工门"),
                   gloss.replace("不是发生过的动作", ""),
                   gloss.replace("不计入", "")):
        assert _gloss_problems(broken) != [], "删掉那一句判据却一声不吭"


# ====================================================================== c 页面
#: 页面必须有这几样（各一句"缺了会被读成什么"）。
_PAGE_NEEDS: tuple[tuple[str, str], ...] = (
    ("现算预演", "页面没有『现算预演』这个组名 / 角标"),
    ("previewClasses(view)", "页面没有把现算预演那一类单独取出来"),
    ("countedClasses(view)", "主表没有排除现算预演那一类（仍然混排）"),
    ("one.computed === true", "页面没有读 API 的 computed 标记（只按类目名写死就不算标记）"),
    ("此刻 blocker 条数", "现算预演那一组的计数列还叫『条数』（会被读成发生次数）"),
)


def _page_problems(text: str) -> list[str]:
    """页面是不是读标记、单独成组、而且计数列换了名字（空 = 合格）。"""
    problems = [why for needle, why in _PAGE_NEEDS if needle not in text]
    # 单独一张表：按类表 + 按角色矩阵 + 现算预演表 = 三张 err-matrix
    if text.count('class="grid err-matrix"') < 3:
        problems.append("现算预演没有自己的一张表（与发生次数挤在同一张表里）")
    return problems


def test_c_the_page_groups_preview_apart_from_occurrence_counts() -> None:
    """c 正控（结构）：页面读 `computed` 标记并把这一类单独成组。"""
    assert ROLE_ERRORS_TSX.is_file(), f"{ROLE_ERRORS_TSX} 不在盘上 —— 这一栏没有落点"
    text = ROLE_ERRORS_TSX.read_text(encoding="utf-8")
    assert _page_problems(text) == [], _page_problems(text)


def test_c_removing_the_marker_or_the_badge_makes_the_page_check_red() -> None:
    """e 反真空（页面）：删标记 / 删组名 / 删分组 ⇒ c 必红。"""
    text = ROLE_ERRORS_TSX.read_text(encoding="utf-8")
    assert _page_problems(text) == [], _page_problems(text)
    for broken in (text.replace("现算预演", ""),
                   text.replace("one.computed === true", "false"),
                   text.replace("previewClasses(view)", "[]"),
                   text.replace("countedClasses(view)", "classRows(view)")):
        assert _page_problems(broken) != [], "抽掉那一格判据却一声不吭"


# ====================================================================== d 正控
def test_d_the_marker_does_not_touch_real_counts_or_their_order(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d 正控：标记只加一格，计数与排序一个字节不动。

    做法：同一份盘读两次 —— 一次带标记，一次把 `PREVIEW_CATEGORIES` 打桩成空；
    把带标记那一份的 `computed` 剥掉之后，两份 `classes` 必须逐字节相同。
    这比"挑几个数核对"更强：`count` / `bucket` / `state` / `this_run` / `samples` /
    `by_role` 与整张表的顺序全在那一条等式里。
    """
    root = _write_ws(tmp_path)
    full_api = _read(root)["data"]
    full = full_api["classes"]
    expect = _expected_preview()
    assert any(one.get("computed") is True for one in full), "反真空：带标记的那一份没有标记"
    monkeypatch.setattr(ES, "PREVIEW_CATEGORIES", frozenset(), raising=False)
    off_api = _read(root)["data"]
    off = off_api["classes"]
    stripped = [{k: v for k, v in one.items() if k != "computed"} for one in full]
    assert stripped == off, "标记把别的格或排序动了"
    # 计数与排序也不许被标记动：除 `classes` 外整份 `data` 逐格相同
    assert ({k: v for k, v in full_api.items() if k != "classes"}
            == {k: v for k, v in off_api.items() if k != "classes"}), "标记动了计数那一层"
    # 夹具的真读数仍在那里（正控不能靠"两个空表相等"变绿）
    counts = {one["category"]: one["count"] for one in full}
    assert counts["closing_blocker"] == 2, counts
    assert counts["param_invalid"] == 2 and counts["direct_write"] == 1, counts
    assert [one["category"] for one in full] == [one["category"] for one in off]
