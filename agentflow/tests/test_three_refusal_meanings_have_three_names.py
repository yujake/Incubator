# -*- coding: utf-8 -*-
"""判据（先红 · 未修）：`refusals` 一词三义，各用其名（2026-11-03，153-U-09）。

## 三义（同一件事此前三个地方都叫 `refusals`）

| 落点 | 它数的是什么 | 应该有名字 |
|---|---|---|
| `statusreport.collect` 的 `refusals` | `tasks` 表里 `outcome="refused"` 的动作行 | `action_refusals` |
| `clock.patrol_anomalies` 的 `refusals`（巡查的 ④） | 会话里的 `final_refused` 事件（收工被拒） | `final_refusals` |
| `secretary.registration_refusals`（上一轮已落） | 名册写口拒过的号（`out/roster/refusals/` 流水） | `registration_refusals` |

三件事的分母、范围、读者都不同：动作行在台账里、收工拒信在会话里、名册拒绝在流水里。
同一个键名会让"被拒了多少次"这个问题有三个互不相等的答案，而三个都自称是答案。

## 这条判据钉什么

1. 两格各用其名（`action_refusals` / `final_refusals`），同一份返回里不再出现 `refusals`；
2. 改名不改值：动作被拒 1 行 ⇒ `action_refusals.total == 1`、`by_reason == {"invalid_params": 1}`；
   一段会话里一次 `final_refused` ⇒ `final_refusals.count == 1`、行里 `kind` 仍是 `final_refused`；
3. 三义互不复用：`registration_refusals` 与 `action_refusals` 同在一份状态报告里、各是各的格；
4. 反向：全仓 `src/` 里不许再出现不带限定的 `refusals` 字典键 —— 登记表已清零
   （2026-11-03 第二笔：`agenttrace` 那处改成 `subtask_refusals`、`search_tools`
   那处改成 `source_refusals`，与出口那本 multi 已有的名字同一个），
   于是这一条从"除两处之外"收紧成"一处都不许有"。

## 第二笔做了什么（这一笔是"登记过期"那一半的兑现）

上一笔把两处别的含义「登记」在这里、没有改名（改名要动 `returns=` 与冻结快照，
属 FC-27 的 eval-criteria）。业主 2026-11-02 批准动禁改区 ⇒ 这一笔把它们改掉，
登记表随之清零：

| 落点 | 改前 | 改后 | 值 |
|---|---|---|---|
| `agenttrace.node_facts` 的节点读数 | `refusals` | `subtask_refusals` | 逐字不变（`_refusals()` 的返回原样搬过去） |
| `tools.search_tools._multi_source_reading` | `refusals` | `source_refusals` | 逐字不变（`mp.last_refusals` 原样搬过去；出口那本 multi 早就叫这个名字） |

登记表只增不减会烂成噪音 —— 所以下面两条正向判据不只是"新名字在"，还钉住
"值没变"（改名的唯一合法形态）。
"""
from __future__ import annotations

import ast
import pathlib
import types

import pytest

from agentflow import agenttrace as AT
from agentflow import clock as C
from agentflow import sessions as SS
from agentflow import statusreport as SR
from agentflow.store import Store
from agentflow.tools import clock_tools as CT
from agentflow.tools import search_tools as ST

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"


# ---------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return ws, st


def _refused_action(st: Store) -> None:
    """落一行"动作被拒"（`outcome=refused` + `refusal_reason`）—— `action_refusals` 的来源。"""
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {"task_id": "t-0001", "role": "D", "action": "consider",
                            "params": {}, "status": "done", "outcome": "refused",
                            "refusal_reason": "invalid_params", "called_by": "M", "depth": 1,
                            "input_key": "k", "started_at": "2026-10-05T00:00:00+08:00",
                            "ended_at": "2026-10-05T00:00:01+08:00",
                            "detail": "参数不合法（夹具）", "error": None, "artifacts": []})


def _final_refused_session(root: pathlib.Path) -> None:
    """一段会话里落一步"收工被拒"（`final_refused`）—— `final_refusals` 的来源。"""
    SS.append(root, {"kind": "agent_step", "role": "M",
                     "result": {"final_refused": {"why": "名下还有没销号的子代理",
                                                  "root": "t-000001"}}},
              sid="s-final")


# ---------------------------------------------------------------- ① 两格各用其名


def test_the_status_report_cell_is_named_action_refusals(tmp_path: pathlib.Path) -> None:
    """① 状态报告那一格叫 `action_refusals`，且不再有同义的 `refusals`。"""
    ws, st = _ws(tmp_path)
    _refused_action(st)
    report = SR.collect(st, ws)
    assert "action_refusals" in report, sorted(report)
    assert "refusals" not in report, (
        "状态报告里还有 `refusals` 这个键 ⇒ 三义仍共用一个名字", sorted(report))


def test_the_patrol_cell_is_named_final_refusals(tmp_path: pathlib.Path) -> None:
    """① 巡查 ④ 那一格叫 `final_refusals`，且不再有同义的 `refusals`。

    两层各查一次：工具层的读口（`clock_tools._patrol_probe` 交回去的那份）与
    时钟层收下之后的那份（`clock.patrol_anomalies` 按名取格）。
    """
    ws, _st = _ws(tmp_path)
    _final_refused_session(ws)
    probe = CT._patrol_probe(str(ws), "t-000001")
    assert "final_refusals" in probe, sorted(probe)
    assert "refusals" not in probe, (
        "工具层的巡查读口里还有 `refusals` 这个键 ⇒ 三义仍共用一个名字", sorted(probe))
    C.set_patrol_probe(lambda _w, _t: dict(probe, checked=True))
    try:
        got = C.patrol_anomalies(ws, task_id="t-000001")
    finally:
        C.set_patrol_probe(None)
    assert "final_refusals" in got, sorted(got)
    assert "refusals" not in got, (
        "时钟层的巡查读数里还有 `refusals` 这个键 ⇒ 三义仍共用一个名字", sorted(got))


# ---------------------------------------------------------------- ② 改名不改值


def test_the_action_refusals_keep_their_values(tmp_path: pathlib.Path) -> None:
    """② 改名不改值：1 行动作被拒 ⇒ `total=1` / `by_reason` 仍是那一份。"""
    ws, st = _ws(tmp_path)
    _refused_action(st)
    cell = SR.collect(st, ws)["action_refusals"]
    assert cell["total"] == 1, cell
    assert cell["by_reason"] == {"invalid_params": 1}, cell
    assert cell["recent"][0]["task_id"] == "t-0001", cell
    assert cell["recent"][0]["reason"] == "invalid_params", cell


def test_the_final_refusals_keep_their_values(tmp_path: pathlib.Path) -> None:
    """② 改名不改值：一次收工被拒 ⇒ `count=1`，行里的 `kind` 仍是 `final_refused`。"""
    ws, _st = _ws(tmp_path)
    _final_refused_session(ws)
    probe = CT._patrol_probe(str(ws), "t-000001")
    C.set_patrol_probe(lambda _w, _t: dict(probe, checked=True))
    try:
        got = C.patrol_anomalies(ws, task_id="t-000001")
        text = C.patrol_text(got)
    finally:
        C.set_patrol_probe(None)
    cell = got["final_refusals"]
    assert cell["checked"] is True and cell["count"] == 1, cell
    assert cell["rows"][0]["kind"] == "final_refused", cell
    assert cell["rows"][0]["task_id"] == "t-000001", cell
    assert "④ 被拦的结项原因 条数 1" in text, text


# ---------------------------------------------------------------- ③ 三义互不复用


def test_the_three_meanings_have_three_names(tmp_path: pathlib.Path) -> None:
    """③ 三格各用其名：同一份状态报告里 `action_refusals` 与 `registration_refusals`
    并排、各是各的格；巡查那一格是第三个名字 —— 三个字面量互不相等。"""
    ws, st = _ws(tmp_path)
    _refused_action(st)
    report = SR.collect(st, ws)
    names = {"action_refusals", "final_refusals", "registration_refusals"}
    assert len(names) == 3
    # 名册那一格在 `in_flight` 里面（它属于"在飞/名册"那一节），动作那一格在顶层
    assert "action_refusals" in report, sorted(report)
    assert "registration_refusals" in report["in_flight"], sorted(report["in_flight"])
    assert "refusals" not in report
    # 两格的值不是同一个东西：动作被拒 1 行，名册拒绝 0 行（这一份夹具没写过名册）
    assert report["action_refusals"]["total"] == 1, report["action_refusals"]
    assert report["in_flight"]["registration_refusals"]["count"] == 0, \
        report["in_flight"]["registration_refusals"]


# ---------------------------------------------------------------- ③b 两处改名：值必须逐字不变

#: 子任务被拒那一格用的夹具行（一条台账里 `outcome=refused` 的行）。
_SUBTASK_ROW = {
    "task_id": "t-000001", "role": "D", "status": "done", "outcome": "refused",
    "refusal_reason": "forbidden_edge", "kind": "", "detail": "越权边（夹具）",
    "started_at": "", "ended_at": "",
}


def _subtask_cell(tmp_path: pathlib.Path) -> dict:
    ws = tmp_path / "ws"
    ws.mkdir()
    st = Store(ws)
    st.init()
    return dict(AT.node_facts(st, ws, dict(_SUBTASK_ROW)))


def test_the_subtask_cell_is_named_subtask_refusals(tmp_path: pathlib.Path) -> None:
    """① `agenttrace` 那一格改名成 `subtask_refusals`，且值逐字不变（改名不改值）。

    "逐字不变"的对照：这一份 dict 就是改名前同一个夹具上 `node_facts()["refusals"]`
    的返回值（2026-11-03 改前用 `temp/probe_153_u09_before_after.py` 落过盘）。
    """
    got = _subtask_cell(tmp_path)
    assert "subtask_refusals" in got, sorted(got)
    assert "refusals" not in got, (
        "子任务读数里还有裸 `refusals` ⇒ 它与动作/收工/名册三义仍共用一个名字", sorted(got))
    assert got["subtask_refusals"] == {
        "count": 1,
        "by_category": {"forbidden_edge": 1},
        "samples": [{"code": "forbidden_edge", "category": "forbidden_edge",
                     "text": "forbidden_edge"}],
        "unclassified": 0,
        "checked": True,
    }, got["subtask_refusals"]


def test_the_search_cell_is_named_source_refusals() -> None:
    """① `search_tools._multi_source_reading` 那一格改名成 `source_refusals`。

    出口那本 multi 早就叫 `source_refusals`（`_h_literature` 的 data 里那一格），
    改前只有函数内部这一份 dict 叫裸 `refusals` —— 同一个量两个名字。
    值仍逐字是 `mp.last_refusals`（这里钉的就是"原样搬过去"）。
    """
    class _Stat:
        status = "query_not_applicable_cjk"
        count = 0
        error_kind = "query_not_applicable"
        error = "查询对这条通道不适用（夹具）"
        delivered = False
        refused = True

    mp = types.SimpleNamespace(
        last_stats={"openalex": _Stat(), "crossref": _Stat()},
        last_refusals={"openalex": "查询对这条通道不适用（夹具）",
                       "crossref": "查询对这条通道不适用（夹具）"},
    )
    multi = ST._multi_source_reading(mp)
    assert "source_refusals" in multi, sorted(multi)
    assert "refusals" not in multi, (
        "检索读数里还有裸 `refusals` ⇒ 同一个量在函数内部与出口各叫一个名字", sorted(multi))
    assert multi["source_refusals"] == mp.last_refusals, multi["source_refusals"]


# ---------------------------------------------------------------- ④ 反向：不许再有无名的 refusals 键

#: 仍然叫裸 `refusals` 的那两处，逐条登记（含义 + 为什么不在这三义里）。
#: 2026-11-03（153-U-09 第二笔）：登记表已清零 —— 两处都改了名
#: （`subtask_refusals` / `source_refusals`）。只增不减的登记表会烂成噪音，
#: 所以这里留着一个空表而不是删掉这段：下一处再出现裸键时，
#: 判据的报错会指向这张表（"要么改名，要么逐条登记"，二选一都得说清）。
KNOWN_BARE_KEYS: dict[str, str] = {}

#: 扫的键名：不带限定的 `refusals`（`action_refusals` 之类带前缀的不算）。
_BARE = "refusals"


def _bare_key_files(tree: ast.AST) -> set[str]:
    """一棵 AST 里所有"字典字面量的键恰好是 `refusals`"的位置（返回空串表示命中过）。"""
    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if isinstance(key, ast.Constant) and key.value == _BARE:
                hits.add("")
    return hits


def _scan(text: str) -> bool:
    """这段源码里有没有不带限定的 `refusals` 字典键（注释与字符串里出现不算）。"""
    return bool(_bare_key_files(ast.parse(text)))


def test_the_scanner_catches_a_new_bare_key() -> None:
    """反向判据的负控：判据本身能红（造一段带 `refusals` 键的源码 ⇒ 扫得出来）。"""
    assert _scan('x = {"refusals": 1}\n') is True
    assert _scan('x = {"action_refusals": 1}\n') is False
    assert _scan('# 历史注释里的 refusals 不算键\nx = {}\n') is False


def test_no_unregistered_bare_refusals_key_in_src() -> None:
    """④ 全仓 `src/` 的字典键：裸 `refusals` 只许出现在登记过的那两处（且登记不许过期）。"""
    found: dict[str, set[int]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == _BARE:
                    lines.add(int(getattr(key, "lineno", 0)))
        if lines:
            found[path.relative_to(SRC).as_posix()] = lines

    unexpected = sorted(set(found) - set(KNOWN_BARE_KEYS))
    assert not unexpected, (
        "这些文件里还有不带限定的 `refusals` 字典键 —— 三义（动作被拒 / 收工被拒 / 名册拒绝）"
        f"之外又多出一个同名量：{unexpected}（登记表里的两处见 KNOWN_BARE_KEYS）")

    stale = sorted(set(KNOWN_BARE_KEYS) - set(found))
    assert not stale, (
        f"登记过期的裸 `refusals` 键：{stale} —— 那两处已经改了名/删了，"
        "登记必须从 KNOWN_BARE_KEYS 里删掉（一张只增不减的登记表会烂成噪音）")
