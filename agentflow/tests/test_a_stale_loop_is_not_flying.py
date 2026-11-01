# -*- coding: utf-8 -*-
"""判据（2026-11-01，82 的定格数据）：未收尾的循环不是「在飞」。

## 改前是什么样（缺陷现场）

`projects/paper-rewrite-82/sessions/20261101.jsonl` 的定格读数：
`agent_run_start=37`、`agent_run_end=35` ⇒ 差 2；`tasks` 里 `running=0`。
两个数各自都对，而 `/live` 的「在飞」表列着 2 行 D（20:38:22 / 20:38:23 起）、
写着"结论：有"；同页名册三态合计却是「在飞 0」。那 2 行是被父叫停打断的
循环记录（顶趟 `t-000001` 在 20:59:28 以 `stop_file` 收尾、宿主进程已退出），
它们不是活着的。

根因只有一句话：页面把"有 start 没 end 的循环记录"叫成了"在飞"。

## 这一份守什么

| 判据 | 形态 | 期望 |
|---|---|---|
| ① 已收尾 | 两条 run 都有 end | 两条 `stale_loop` 都是 `False`；`未收尾=0` |
| ② 未收尾且顶趟已 done | 子 run 有 start 没 end，顶趟收到 end | 子 `stale_loop=True`、顶趟 `False`；`在飞=0`、`未收尾=1`、`answer=没有` |
| ③ 未收尾但顶趟还在跑 | 两条 run 都只有 start | 两条 `stale_loop=False`（这时它真的还在飞） |
| ④ 两个读口 | `state.snapshot()` 与 `readers.run_view()` | 同一批 `stale_loop`（逐字相同） |
| ⑤ 页面口径 | `ui/src/pages/Live.tsx` | 两个数并列；循环表叫「未收尾的循环」；死行写"宿主进程已退出/被叫停，不是活着" |
| ⑥ 反真空 | 把页面改回旧口径 / 把读数层改回"没 end 就算在飞" | ⑤ / ②③ 的检查必须响 |

## 为什么这一条不冻结 82 的数字

82 的定格数据只用来说明缺陷，不用来当夹具（判据要在任何工作区上可复跑）：
上面三类形态都是现造的临时工作区。82 那一份的"反真空"复算写在
`temp/_verify_82_stale_loop.py`（跑在只读复制品上，不进默认测试 ——
默认测试不该依赖某个项目的运行数据，它随时会被清理）。

## 三态纪律

`stale_loop` 是一个布尔读数，但它的"读不到"方向是保守的：顶趟没收到 end
（或判不了）⇒ `False`（不替循环宣布死亡）；只有"这一趟没 end 且顶趟已收尾"
才 `True`。所以它永远不把"没收到 end"说成"还在跑" —— 那正是这一批要修的那句话。
"""
from __future__ import annotations

import pathlib

from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.store import Store
from agentflow.webui import readers as R
from agentflow.webui import state as W

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
LIVE_TSX = REPO / "ui" / "src" / "pages" / "Live.tsx"

#: 判据自己的会话号（不碰任何真工作区）。
SID = "s-stale-loop"

#: 三条形态共用的时间戳（哪一年不重要：判据不用"现在"）。
TS = "2026-11-01T00:00:00+08:00"


# ====================================================================== 夹具体
def _append(root: pathlib.Path, **event: object) -> None:
    """落一条会话事件（走 `sessions.append`，不手拼 JSON 行；`ts` 缺省补上）。"""
    event.setdefault("ts", TS)
    SS.append(root, event, sid=SID)


def _task(root: pathlib.Path, task_id: str, role: str, status: str,
          detail: str = "") -> None:
    """写一行 `tasks` 台账（顶趟 / 子循环各一行；`running` 行不带 `ended_at`）。"""
    with Store(root).tx("tasks", actor="fixture", note="judge:stale-loop") as tx:
        tx.upsert("tasks", S.Task(
            task_id=task_id, role=role, action="run",
            called_by="user" if role == "M" else "M",
            status=status,
            outcome="ok" if status != "running" else None,
            detail=detail,
            input_key=f"{role}.run",
            started_at=TS,
            ended_at=TS if status == "done" else None,
        ).to_dict())


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    Store(root).init()
    return root


def _closed_loop_with_done_top(tmp_path: pathlib.Path) -> pathlib.Path:
    """② 的形态：子循环有 start 没 end，而顶趟已 done（宿主走了 / 被父叫停）。"""
    root = _workspace(tmp_path)
    _task(root, "t-000001", "M", "done", detail="顶趟收工（stop_file）")
    _task(root, "t-000002", "D", "pending")
    _append(root, kind="agent_run_start", role="M", task="顶趟", task_id="t-000001")
    _append(root, kind="agent_run_start", role="D", task="被叫停的子循环",
            task_id="t-000002", ts="2026-11-01T00:10:00+08:00")
    _append(root, kind="agent_run_end", role="M", task_id="t-000001",
            stop_reason="stop_file", ts="2026-11-01T01:00:00+08:00")
    return root


def _open_loop_top_running(tmp_path: pathlib.Path) -> pathlib.Path:
    """③ 的形态：两条 run 都只有 start —— 顶趟还在跑，子循环这时真的还在飞。"""
    root = _workspace(tmp_path)
    _task(root, "t-000001", "M", "running")
    _task(root, "t-000002", "D", "running")
    _append(root, kind="agent_run_start", role="M", task="顶趟", task_id="t-000001")
    _append(root, kind="agent_run_start", role="D", task="子循环",
            task_id="t-000002", ts="2026-11-01T00:10:00+08:00")
    return root


def _both_ends(tmp_path: pathlib.Path) -> pathlib.Path:
    """① 的形态：两条 run 都收到了自己的 end（已收尾）。"""
    root = _workspace(tmp_path)
    _task(root, "t-000001", "M", "done", detail="顶趟收工")
    _task(root, "t-000002", "D", "done", detail="子循环收工")
    _append(root, kind="agent_run_start", role="M", task="顶趟", task_id="t-000001")
    _append(root, kind="agent_run_start", role="D", task="子循环",
            task_id="t-000002", ts="2026-11-01T00:10:00+08:00")
    _append(root, kind="agent_run_end", role="D", task_id="t-000002", stop_reason="final",
            ts="2026-11-01T00:20:00+08:00")
    _append(root, kind="agent_run_end", role="M", task_id="t-000001", stop_reason="final",
            ts="2026-11-01T01:00:00+08:00")
    return root


def _readings(root: pathlib.Path) -> dict[str, object]:
    """同一份盘上事实的三次读：`/api/state` 的 runs、`/api/run` 的 runs、`/api/live`。

    三个读口各取"这一趟的 `stale_loop` 是哪一档"，外加页面要用的两个数
    （`tasks_running` / `unclosed_loops`）与 `answer` —— 一处一次读全，
    免得判据在三个地方各读一遍时把"哪一档来自哪里"读丢。
    """
    snap = W.snapshot(root)
    view = R.run_view(root, SID)
    live = R.live_face(root)
    return {
        "state_runs": {str(r.get("task_id")): r.get("stale_loop") for r in snap["runs"]},
        "view_runs": {str(r.get("task_id")): r.get("stale_loop") for r in view["runs"]},
        "live_runs": {str(r.get("task_id")): r.get("stale_loop")
                      for r in live["running"] if str(r.get("task_id") or "")},
        "tasks_running": live["tasks_running"],
        "unclosed_loops": live["unclosed_loops"],
        "answer": live["answer"],
        "live": live,
    }


# ====================================================================== ① 已收尾
def test_a_closed_loop_is_not_stale(tmp_path: pathlib.Path) -> None:
    """① 有 start 有 end ⇒ `stale_loop=False`，「未收尾」读 0。"""
    got = _readings(_both_ends(tmp_path))
    assert got["state_runs"] == {"t-000001": False, "t-000002": False}, got
    assert got["view_runs"] == got["state_runs"], got
    assert got["live_runs"] == {}, got
    assert got["unclosed_loops"] == 0, got
    assert got["answer"] == "没有", got


# ====================================================================== ② 未收尾 + 顶趟已 done
def test_an_unclosed_loop_under_a_done_top_is_stale_not_flying(
        tmp_path: pathlib.Path) -> None:
    """② 82 的形态：子循环有 start 没 end、顶趟已 done ⇒ stale，不是在飞。

    这一条就是缺陷现场：改前页面会把它列进「在飞」并写"结论：有"。
    改后逐格读数必须是：`stale_loop=True`、页面「在飞（tasks 里 running）」读 0、
    「未收尾的循环」读 1、`answer` 读「没有」。
    """
    got = _readings(_closed_loop_with_done_top(tmp_path))
    assert got["state_runs"] == {"t-000001": False, "t-000002": True}, got
    assert got["view_runs"] == got["state_runs"], got
    assert got["live_runs"] == {"t-000002": True}, got
    # 页面那两个数（/api/live 的顶层两格）：在飞 0 / 未收尾 1。
    assert got["tasks_running"] == 0, got
    assert got["unclosed_loops"] == 1, got
    # 只剩"没收到 end"的循环记录、又没有活进程 ⇒ 不许再说「有」。
    assert got["answer"] == "没有", got


# ====================================================================== ③ 未收尾但顶趟在跑
def test_an_unclosed_loop_under_a_running_top_is_not_stale(
        tmp_path: pathlib.Path) -> None:
    """③ 有 start 没 end，顶趟还在跑 ⇒ `stale_loop=False`（这时它真的在飞）。

    这一条是 ② 的反面：`stale_loop` 不是"没有 end"的同义词 —— 没有这一条，
    ② 可以靠"凡没 end 就 stale"混过去，而那正好会把真在跑的循环说成死的。
    """
    got = _readings(_open_loop_top_running(tmp_path))
    assert got["state_runs"] == {"t-000001": False, "t-000002": False}, got
    assert got["view_runs"] == got["state_runs"], got
    assert got["live_runs"] == {"t-000001": False, "t-000002": False}, got
    # 两条 run 都还开着 ⇒ 「未收尾的循环」读 2（两行都不是 stale：它们真的还在飞）。
    assert got["unclosed_loops"] == 2, got
    # tasks 里两行都是 running ⇒ 「在飞」（tasks 口径）读 2，而不是 0。
    assert got["tasks_running"] == 2, got
    assert got["answer"] == "有", got


# ====================================================================== ⑤ 页面口径
#: 循环表那一句表头（改前它是「在飞」）。
LOOP_TITLE = "未收尾的循环"

#: 死行必须逐字写出的那句话（业主 2026-11-01 的口径）。
DEAD_WORDING = "宿主进程已退出/被叫停，不是活着"

#: 「在飞」在两数并列里的那一半（只许用在 tasks 状态上）。
FLYING_TITLE = "在飞（tasks 里 running）"


def _page_problems(source: str) -> list[str]:
    """页面口径的判据本体（纯函数：给负控喂人造源码用）。

    五件事，缺一件就能被"看起来对"的页面蒙过去：
    1. 两个数并列：`在飞（tasks 里 running）= N` 与 `未收尾的循环 = M` 在同一句里；
    2. 两个数各自从 `tasks_running` / `unclosed_loops` 读（不是页面自己再数一遍）；
    3. 循环表的标题是「未收尾的循环」，不是「在飞」；
    4. 行尾按 `stale_loop` 分档，死行逐字写「宿主进程已退出/被叫停，不是活着」；
    5. 旧口径的那句 `empty="没有在跑的循环。"` 已经退场（它把"没有 start/end 记录"
       说成"没有在跑"）。
    """
    problems: list[str] = []
    pairs = [ln for ln in source.splitlines()
             if FLYING_TITLE in ln and LOOP_TITLE in ln and "unclosed_loops" in ln]
    if len(pairs) < 2:
        problems.append(
            f"两个数并列的地方不够：「结论」与表标题都要同时出现 {FLYING_TITLE!r} 与 "
            f"「{LOOP_TITLE}」（读到 {len(pairs)} 处）")
    if "cell(l.tasks_running)" not in source:
        problems.append("「在飞」那一格没有从 `tasks_running` 读（页面自己再数一遍就是第二份口径）")
    if "cell(l.unclosed_loops)" not in source:
        problems.append("「未收尾的循环」那一格没有从 `unclosed_loops` 读")
    if "r.stale_loop ?" not in source:
        problems.append("循环表的行尾没有按 `stale_loop` 分档（死行与在跑的行会印同一句）")
    if DEAD_WORDING not in source:
        problems.append(f"死行没有逐字写出 {DEAD_WORDING!r}")
    if 'empty="没有在跑的循环。"' in source:
        problems.append(
            '旧口径 `empty="没有在跑的循环。"` 还在：它把"没有 start/end 记录"说成"没有在跑"')
    return problems


def test_the_live_page_names_the_two_numbers_and_the_dead_rows() -> None:
    """⑤ 页面照做了：两个数并列、循环表改名、死行写"不是活着"。"""
    source = LIVE_TSX.read_text(encoding="utf-8")
    problems = _page_problems(source)
    assert problems == [], "\n".join(problems)
    # 正控（读数是给人看的）：旧卡片标题只剩「在飞」的那种形态已经不在了。
    assert 'title="在飞"' not in source, "卡片标题还是旧的 `title=\"在飞\"`"


def test_negative_control_the_old_loop_title_and_the_dead_wording_are_both_reported() -> None:
    """⑥（反真空）：把页面改回旧口径 ⇒ ⑤ 的检查必须响。

    没有这一条，⑤ 可能是"读了几行、但读的那几行与循环表无关" —— 一个永远绿的
    断言与一条被删掉的判据在输出上没有区别。
    """
    source = LIVE_TSX.read_text(encoding="utf-8")
    assert _page_problems(source) == [], "前提：真源码本身是绿的"

    old_title = source.replace(f"<b>{LOOP_TITLE} =", "<b>在飞 =", 1)
    assert old_title != source
    problems = _page_problems(old_title)
    assert problems, "把表标题里的「未收尾的循环」改回「在飞」之后判据没响"
    assert any(LOOP_TITLE in p for p in problems), problems

    no_dead = source.replace(DEAD_WORDING, "")
    assert no_dead != source
    problems = _page_problems(no_dead)
    assert problems, "把死行那句话删掉之后判据没响"
    assert any(DEAD_WORDING in p for p in problems), problems

    no_stale = source.replace("r.stale_loop ?", "")
    assert no_stale != source
    problems = _page_problems(no_stale)
    assert problems, "把行尾的 `stale_loop` 分档删掉之后判据没响"

    no_number = source.replace("cell(l.tasks_running)", "")
    assert no_number != source
    problems = _page_problems(no_number)
    assert problems, "把「在飞」那一格的读数删掉之后判据没响"
