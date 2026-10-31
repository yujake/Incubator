# -- coding: utf-8 --
"""趟次索引与事件的对账判据（裁定 O2；`draft/75 §3` 的判据 F）。
## 这一组守什么
索引是派生数据：它可能与源不一致。所以这里的第一条纪律不是"索引读得出来"，而是"索引与 `sessions/*.jsonl` 的事件现算结果逐趟一致"，且不一致时报出来：
| 用例 | 正控 / 负控 | 造什么 | 该红还是该绿 |
|---|---|---|---|
| `test_the_index_agrees_with_the_events_run_by_run` | 正控 | 两场各两趟 ⇒ 索引逐趟 == 现算 | 绿 |
| `test_a_tampered_index_byte_is_caught` | 负控 | 手改索引里的 `steps` 一个字节 | 红（`drift`） |
| `test_a_deleted_session_while_the_index_still_has_it_reports_drift` | 负控 | 删掉一场会话、索引还在 | 红（`drift` 点名那场会话） |
| `test_an_absent_index_is_unreadable_not_computed` | 负控（三态） | 索引不在盘上 | `tri=unreadable`，不是 `computed` |
| `test_an_empty_workspace_is_not_applicable` | 负控（三态） | 一场会话都没有 | `tri=not_applicable` |
| `test_the_event_kind_constants_match_userio` | 反真空 | 字面量与 `userio` 的常量 | 相等 |
## 名字的边界（不许混用）
这里的「趟次」是会话内的第几趟（一条 `agent_run_start` → `agent_run_end`）。`projects.py` 的 `run_index: int` 是"这个项目第几趟"（配 `out/run-<n>`）
——另一个概念，本文件一个字都不碰它（`draft/78 §7` 的提醒）。
## 「红前绿后」是怎么做到的
负控都先断言正控那一份是绿的（`usable is True` / `drift == []`），再改一个字节，再断言它红了。少了前面那一步，"改坏了也没红"这件事可能是因为尺子本来就没接上。
"""

from __future__ import annotations

import json
import pathlib

from agentflow import sessions as SS
from agentflow import userio as U

#: 固定时间戳（与 `tests/conftest.py` 的口径一致：判据不依赖当前时间）。
TS = "2026-01-01T00:00:00+00:00"


def _one_run(root: pathlib.Path, sid: str, *, steps: int, usd: float | None) -> None:
    """给某个会话写一趟（开场 → 若干步 → 一次 llm_call → 收尾）。"""
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": f"{sid} 的活",
                     "ts": TS}, sid=sid)
    for i in range(steps):
        SS.append(root, {"kind": "agent_step", "role": "M", "index": i,
                         "shape": "fs.write"}, sid=sid)
    SS.append(root, {"kind": "llm_call", "role": "M", "ok": True, "usd": usd,
                     "tokens_in": 3, "tokens_out": 4}, sid=sid)
    SS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final",
                     "steps": steps, "final_chars": 6, "summons": 1, "messages": 0,
                     "elapsed_sec": 2.5, "ts": TS}, sid=sid)


def _two_sessions_two_runs(root: pathlib.Path) -> None:
    """两场会话、各两趟（一场里连续两趟，另一场一趟正常一趟缺收尾）。"""
    _one_run(root, "s-alpha", steps=1, usd=0.25)
    _one_run(root, "s-alpha", steps=3, usd=None)
    _one_run(root, "s-beta", steps=0, usd=0.5)
    SS.append(root, {"kind": "agent_run_start", "role": "A", "task": "没跑完的那趟",
                     "ts": TS}, sid="s-beta")
    SS.append(root, {"kind": "agent_step", "role": "A", "index": 0, "shape": "fs.read"},
              sid="s-beta")


# ====================================================================== 正控
def test_the_index_agrees_with_the_events_run_by_run(tmp_path: pathlib.Path) -> None:
    """正控：两场会话 ⇒ 索引与事件现算结果逐趟一致，且索引真的落到了盘上。

    对账不是"两边都读得出来"就算过：这里逐趟比 `runs` 的每一格（`json.dumps` 规范化
    之后逐字节比），所以字段少一个、值差一个都会红。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _two_sessions_two_runs(root)
    index = SS.rebuild_run_index(root)
    assert SS.run_index_path(root).is_file(), "重建之后索引必须真的在盘上"

    report = SS.run_index_report(root)
    assert report["usable"] is True, report
    assert report["tri"] == "computed", report
    assert report["drift"] == [], report["drift"]

    live = SS.compute_run_index(root)["sessions"]
    assert sorted(live) == ["s-alpha", "s-beta"], sorted(live)
    assert [len(live[s]["runs"]) for s in sorted(live)] == [2, 2], live
    for sid in sorted(live):
        assert index["sessions"][sid]["digest"] == live[sid]["digest"], sid
        assert json.dumps(index["sessions"][sid]["runs"], sort_keys=True,
                          ensure_ascii=False) == json.dumps(live[sid]["runs"],
                                                            sort_keys=True,
                                                            ensure_ascii=False), sid
    # 读数本身也要对：第一场第一趟 1 步 0.25 美元、第二趟 3 步但价钱算不出
    first, second = index["sessions"]["s-alpha"]["runs"]
    assert (first["steps"], first["llm_calls"], first["usd"],
            first["unknown_usd"]) == (1, 1, 0.25, 0)
    assert (second["steps"], second["usd"], second["unknown_usd"]) == (3, None, 1)
    assert second["usd"] is None, "算不出价钱是 None，不是 0"
    # 缺收尾的那一趟：end_index/end_ts 是 None/""（三态，不是 0），终点取文件尾
    unfinished = index["sessions"]["s-beta"]["runs"][1]
    assert unfinished["end_index"] is None and unfinished["end_ts"] == ""
    assert unfinished["events_in_run"] == 2, unfinished
    # 重复重建是幂等的（除了 generated_at 那只钟）
    again = SS.rebuild_run_index(root)
    for sid in sorted(live):
        assert again["sessions"][sid]["digest"] == index["sessions"][sid]["digest"]
    assert SS.run_index_report(root)["usable"] is True


def test_a_pending_question_lands_on_the_run_that_waits_for_it(
        tmp_path: pathlib.Path) -> None:
    """正控（待答与趟次的挂接）：没答的问题挂在它之后的那一趟上，`waiting` 随之变真。"""
    root = tmp_path / "ws"
    root.mkdir()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "问一句", "ts": TS},
              sid="s-q")
    out = U.ask_user(root, role="M", question="这四处改动要不要保留？",
                     options=({"label": "保留"},), timeout_sec=0, sid="s-q")
    runs = SS.compute_run_index(root)["sessions"]["s-q"]["runs"]
    assert [r["waiting_on"] for r in runs] == [[out.qid]], runs
    assert runs[0]["waiting"] is True and runs[0]["stop_reason"] == "waiting_for_user"
    # 答了之后就不再挂着（同一份现算，不缓存）
    U.answer_question(root, qid=out.qid, selected=("保留",), sid="s-q")
    runs2 = SS.compute_run_index(root)["sessions"]["s-q"]["runs"]
    assert runs2[0]["waiting_on"] == [] and runs2[0]["waiting"] is False, runs2


# ====================================================================== 负控 ① 手改索引
def test_a_tampered_index_byte_is_caught(tmp_path: pathlib.Path) -> None:
    """负控（判据 F 的第一半）：手改索引里的一个数字 ⇒ 对账必须报出来。

    改的是 `steps`（一个真读数）。为什么这一改一定能被看见：索引里每一场都存着
    它自己 `runs` 的摘要，而重建时又存了"当时盘上现算"的摘要 —— 两个摘要都要复算。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _two_sessions_two_runs(root)
    SS.rebuild_run_index(root)
    good = SS.run_index_report(root)
    assert good["usable"] is True and good["drift"] == [], good   # 负控前：绿

    path = SS.run_index_path(root)
    text = path.read_text(encoding="utf-8")
    mark = '"steps": 3'
    assert text.count(mark) >= 1, "负控没找到要改的那个字节（索引格式变了）"
    path.write_text(text.replace(mark, '"steps": 9', 1), encoding="utf-8")

    bad = SS.run_index_report(root)
    assert bad["usable"] is False, bad          # 负控后：红
    assert bad["tri"] == "unreadable", bad
    assert bad["drift"], bad
    assert any("手改" in d or "不一致" in d for d in bad["drift"]), bad["drift"]
    # 撤回去 ⇒ 又绿（证明红的成因就是那一字节，而不是别的东西坏了）
    path.write_text(text, encoding="utf-8")
    assert SS.run_index_report(root)["usable"] is True
    assert SS.run_index_report(root)["drift"] == []


# ====================================================================== 负控 ② 删会话
def test_a_deleted_session_while_the_index_still_has_it_reports_drift(
        tmp_path: pathlib.Path) -> None:
    """负控（判据 F 的第二半）：删一场会话而索引还在 ⇒ 必须报 `drift` 并点名它。

    这是"索引里留着一场已经不存在的会话"那类漂移：读者若信索引，就会显示一场
    盘上早就没有的会话。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _two_sessions_two_runs(root)
    SS.rebuild_run_index(root)
    assert SS.run_index_report(root)["drift"] == []        # 负控前：绿

    (root / "sessions" / "s-beta.jsonl").unlink()
    after = SS.run_index_report(root)
    assert after["usable"] is False, after
    assert after["tri"] == "unreadable", after
    assert any("s-beta" in d for d in after["drift"]), after["drift"]
    assert any("盘上已经没有这场会话" in d for d in after["drift"]), after["drift"]
    # 重建之后又一致（索引是派生的：源变了就重建，不许手工修补）
    SS.rebuild_run_index(root)
    fixed = SS.run_index_report(root)
    assert fixed["usable"] is True and fixed["drift"] == [], fixed
    assert fixed["sessions"] == ["s-alpha"], fixed["sessions"]


# ====================================================================== 负控 ③ 索引缺席
def test_an_absent_index_is_unreadable_not_computed(tmp_path: pathlib.Path) -> None:
    """负控（三态）：索引不在盘上 ⇒ `unreadable` + 理由，不许报 `computed`。

    把"还没建索引"折成"对账通过"正是本项目最贵的一类缺陷：读者会以为"索引与事件
    一致"，而其实一个索引都没有。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _two_sessions_two_runs(root)
    assert not SS.run_index_path(root).is_file()
    index, why = SS.load_run_index(root)
    assert index is None and why, (index, why)
    assert "不在盘上" in why, why
    report = SS.run_index_report(root)
    assert report["usable"] is False and report["tri"] == "unreadable", report
    assert report["reason"], report
    # 现算那条路照常可用（回退口径：索引没了不等于读数没了）
    assert SS.compute_run_index(root)["sessions"], "现算不该受索引缺席影响"


def test_a_corrupt_index_is_unreadable_not_empty(tmp_path: pathlib.Path) -> None:
    """负控（三态）：索引文件在、但内容不是 JSON ⇒ `unreadable` 并带异常类型。"""
    root = tmp_path / "ws"
    root.mkdir()
    _one_run(root, "s-x", steps=1, usd=0.1)
    path = SS.run_index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{这不是 JSON\n", encoding="utf-8")
    index, why = SS.load_run_index(root)
    assert index is None, index
    assert "读不出来" in why and "JSONDecodeError" in why, why
    assert SS.run_index_report(root)["tri"] == "unreadable"


def test_an_empty_workspace_is_not_applicable(tmp_path: pathlib.Path) -> None:
    """负控（三态）：一场会话都没有 ⇒ `not_applicable`，不是"对上了"、也不是"读不到"。"""
    root = tmp_path / "ws"
    root.mkdir()
    report = SS.run_index_report(root)
    assert report["tri"] == "not_applicable", report
    assert report["drift"] == [] and "一场会话都没有" in report["reason"], report


# ====================================================================== 反真空
def test_the_event_kind_constants_match_userio() -> None:
    """反真空：本模块那两个 kind 字面量与 `userio` 的常量一致。

    为什么要这一条：`sessions.py` 不能导入 `userio`（会成环），所以它抄了一份字面量。
    抄的那一份一旦漂移，索引会把"待答问题"读成空集 —— 而那是一种静默的错读数。
    """
    assert SS.QUESTION_EVENT_KIND == U.ASK_KIND, (SS.QUESTION_EVENT_KIND, U.ASK_KIND)
    assert SS.ANSWER_EVENT_KIND == U.ANSWER_KIND, (SS.ANSWER_EVENT_KIND, U.ANSWER_KIND)


def test_the_local_question_scan_agrees_with_userio(tmp_path: pathlib.Path) -> None:
    """反真空：本模块的 `session_ids_with_questions` 与 `userio` 的同名读数一致。"""
    root = tmp_path / "ws"
    root.mkdir()
    _one_run(root, "s-has-none", steps=1, usd=0.1)
    _one_run(root, "s-has-one", steps=1, usd=0.1)
    U.ask_user(root, role="M", question="有问题的那一场", timeout_sec=0, sid="s-has-one")
    assert SS.session_ids_with_questions(root) == U.session_ids_with_questions(root)
    assert SS.session_ids_with_questions(root) == ["s-has-one"]


# ====================================================================== 多代理交错
# 为什么单列一组（`draft/158` §三）：会话文件是一个工作区一天一份、所有子代理共写的，
# 而切趟规则此前假设"一次只有一趟"（每一条 start 覆盖 `cur`、每一条 end 关掉"当前那趟"，
# 两端都不看 `task_id`）。81 那趟 71 条 start / 71 条 end 实测 63/71 行不可用
# （36 条 `end_ts=None`，有 end 的 35 条里 27 条挂的是别人的 end），M 那趟读出 4 步 / 4 次
# 调用，而它自己的收工行写着 111 步 / 110 次调用。
#
# 上面那些单代理用例天然过（顺序追加，`cur` 恰好就是那一趟），盖不住这一档。所以这里
# 直接拿"交错"当夹具，并且不靠 `run_index_report` 判对错：索引与对账同源
# （`reconcile_run_index` 现算用的就是 `runs_in_session`），配错了两边一起错、`drift`
# 照样是空的 —— 自洽的错不算漂移。真正的判据是直接读那几趟的读数。

def _ev(kind: str, **fields: object) -> dict:
    """一行事件（`ts` 由调用方给：这一组要按 ts 认"这条 end 是不是它自己的"）。"""
    row: dict = {"kind": kind}
    row.update(fields)
    return row


def _nested_parent_and_child(root: pathlib.Path, sid: str) -> None:
    """父 start → 子 start → 子的步与调用 → 子 end → 父的步与调用 → 父 end。

    这是最普通的一趟父子：父派活之后等子跑完（子那一段整个嵌在父的窗口里）。
    """
    A = SS.append
    A(root, _ev("agent_run_start", role="M", task="父的活", task_id="t-000001",
                ts="2026-01-01T00:00:00+00:00"), sid=sid)
    A(root, _ev("agent_step", role="M", index=0, shape="fs.write",
                ts="2026-01-01T00:00:01+00:00"), sid=sid)
    A(root, _ev("llm_call", role="M", task_id="t-000001", ok=True, usd=0.5,
                ts="2026-01-01T00:00:02+00:00"), sid=sid)
    A(root, _ev("agent_run_start", role="D", task="子的活", task_id="t-000002",
                ts="2026-01-01T00:00:03+00:00"), sid=sid)
    A(root, _ev("agent_step", role="D", index=0, shape="fs.read",
                ts="2026-01-01T00:00:04+00:00"), sid=sid)
    A(root, _ev("agent_step", role="D", index=1, shape="fs.write",
                ts="2026-01-01T00:00:05+00:00"), sid=sid)
    A(root, _ev("llm_call", role="D", task_id="t-000002", ok=True, usd=0.25,
                ts="2026-01-01T00:00:06+00:00"), sid=sid)
    A(root, _ev("agent_run_end", role="D", task_id="t-000002", stop_reason="final",
                steps=2, spend={"calls": 1, "usd": 0.25},
                ts="2026-01-01T00:00:07+00:00"), sid=sid)
    A(root, _ev("agent_step", role="M", index=1, shape="fs.read",
                ts="2026-01-01T00:00:08+00:00"), sid=sid)
    A(root, _ev("agent_step", role="M", index=2, shape="fs.write",
                ts="2026-01-01T00:00:09+00:00"), sid=sid)
    A(root, _ev("llm_call", role="M", task_id="t-000001", ok=True, usd=0.125,
                ts="2026-01-01T00:00:10+00:00"), sid=sid)
    A(root, _ev("agent_run_end", role="M", task_id="t-000001", stop_reason="final",
                steps=3, spend={"calls": 2, "usd": 0.625},
                ts="2026-01-01T00:00:11+00:00"), sid=sid)


def test_an_interleaved_child_does_not_steal_the_parents_readings(
        tmp_path: pathlib.Path) -> None:
    """判据 ①：父 start → 子 start → 子 end → 父 end ⇒ 父那趟的 steps/calls/终态必须对得上。

    改前必红（实测这一条在 `2b7b98b5` 上）：
    - 子那条 start 把 `cur` 从父顶掉 ⇒ 父的 `steps` 停在 1；
    - 子那条 end 关掉"当前那趟"（= 子）之后 `cur` 是 None ⇒ 父后半段的步与调用整条丢弃，
      父自己的 end 也落不上去 —— 于是父读出 `steps=1 / llm_calls=1 / stop_reason="" /
      end_ts=""`，而它的收工行写的是 3 步 / 2 次调用 / final。
    """
    root = tmp_path / "ws"
    root.mkdir()
    sid = "s-nested"
    _nested_parent_and_child(root, sid)
    runs = SS.runs_in_session(SS.read_session(root, sid=sid)[0], sid=sid)
    assert [r["role"] for r in runs] == ["M", "D"], runs
    parent, child = runs
    assert (parent["steps"], parent["llm_calls"], parent["stop_reason"]) == (3, 2, "final"), parent
    assert parent["end_ts"] == "2026-01-01T00:00:11+00:00", parent
    assert parent["end_index"] == 11, parent
    assert parent["usd"] == 0.625 and parent["unknown_usd"] == 0, parent
    assert (child["steps"], child["llm_calls"], child["stop_reason"]) == (2, 1, "final"), child
    assert child["end_ts"] == "2026-01-01T00:00:07+00:00", child
    assert child["usd"] == 0.25, child
    # 这一格也写进落盘索引（网页与 CLI 读的是同一份口径）
    index = SS.rebuild_run_index(root)
    assert [r["steps"] for r in index["sessions"][sid]["runs"]] == [3, 2], index


def _interleaved_six(root: pathlib.Path, sid: str) -> dict[str, str]:
    """81 趟那种形态的缩本：6 趟同时开着、start 顺序与 end 顺序不一致。

    与 81 的对应关系：
    - 6 趟共写一份会话（父 M 一 + 五个子代理，其中三个同角色 D —— 81 里是 7 个 D）；
    - 每条 end 带着自己的 `task_id` / `stop_reason` / `ts` / `steps`；
    - 有一家的步（`t-000003` 的第二条）落在另一家已开跑之后：按事件位置数只能算到
      别家头上（`agent_step` 事件里没有任务号），所以每趟的步数必须读它自己的收工行。

    返回 `{task_id: 它的 end ts}`，判据据此认"这条 end 是不是它自己的"。
    """
    A = SS.append
    ends = {"t-000001": "2026-01-01T00:00:30+00:00", "t-000002": "2026-01-01T00:00:27+00:00",
            "t-000003": "2026-01-01T00:00:26+00:00", "t-000004": "2026-01-01T00:00:24+00:00",
            "t-000005": "2026-01-01T00:00:28+00:00", "t-000006": "2026-01-01T00:00:25+00:00"}
    stops = {"t-000001": "final", "t-000002": "max_steps", "t-000003": "error",
             "t-000004": "interrupted", "t-000005": "no_tool_call", "t-000006": "waiting_for_user"}
    clock = 0

    def tick() -> str:
        nonlocal clock
        clock += 1
        return f"2026-01-01T00:00:{clock:02d}+00:00"

    A(root, _ev("agent_run_start", role="M", task="父", task_id="t-000001", ts=tick()), sid=sid)
    A(root, _ev("agent_run_start", role="D", task="子一", task_id="t-000002", ts=tick()), sid=sid)
    A(root, _ev("agent_step", role="M", index=0, shape="fs.write", ts=tick()), sid=sid)
    A(root, _ev("agent_step", role="D", index=0, shape="fs.read", ts=tick()), sid=sid)
    A(root, _ev("agent_run_start", role="D", task="子二", task_id="t-000003", ts=tick()), sid=sid)
    A(root, _ev("agent_step", role="D", index=0, shape="fs.read", ts=tick()), sid=sid)
    A(root, _ev("llm_call", role="D", task_id="t-000002", ok=True, usd=0.1, ts=tick()), sid=sid)
    A(root, _ev("agent_run_start", role="E", task="子三", task_id="t-000004", ts=tick()), sid=sid)
    A(root, _ev("agent_step", role="E", index=0, shape="fs.read", ts=tick()), sid=sid)
    A(root, _ev("llm_call", role="M", task_id="t-000001", ok=True, usd=0.2, ts=tick()), sid=sid)
    A(root, _ev("agent_run_start", role="D", task="子四", task_id="t-000005", ts=tick()), sid=sid)
    # 子二的那一步落在子四已开跑之后：按位置数只会记到子四头上。
    A(root, _ev("agent_step", role="D", index=1, shape="fs.write", ts=tick()), sid=sid)
    A(root, _ev("agent_run_start", role="F", task="子五", task_id="t-000006", ts=tick()), sid=sid)
    A(root, _ev("agent_step", role="F", index=0, shape="fs.read", ts=tick()), sid=sid)
    # end 的顺序与 start 完全错开（81 的读数就是这种形态）
    for tid in ("t-000004", "t-000006", "t-000003", "t-000002", "t-000005", "t-000001"):
        A(root, _ev("agent_run_end", role="", task_id=tid, stop_reason=stops[tid],
                    steps=1, spend={"calls": 1, "usd": 0.1}, ts=ends[tid]), sid=sid)
    return ends


def test_the_interleaved_shape_of_81_pairs_every_end_with_its_own_run(
        tmp_path: pathlib.Path) -> None:
    """判据 ②：71 start / 71 end 交错 ⇒ 每趟的 `end_ts` 与 `stop_reason` 都非空且属自己。

    81 那趟的实测形态：`sessions/20261101.jsonl` 71 条 start / 71 条 end，索引里 36 条
    `end_ts=""`、有 end 的 35 条里 27 条挂的是别人的 end（例：`start t-000026(F) ←
    end of t-000010(D)`）。这里把那个形态缩到 6 趟，并且让 end 的落盘顺序与 start 错开。

    改前必红：每条 end 关的都是"当前那趟"，而"当前那趟"是最后一条 start ⇒ 除最后一趟外
    每条 run 的 `end_ts` 要么空、要么是别人的 ts。
    """
    root = tmp_path / "ws"
    root.mkdir()
    sid = "s-braid"
    ends = _interleaved_six(root, sid)
    runs = SS.runs_in_session(SS.read_session(root, sid=sid)[0], sid=sid)
    by_tid = {"t-000001": "final", "t-000002": "max_steps", "t-000003": "error",
              "t-000004": "interrupted", "t-000005": "no_tool_call",
              "t-000006": "waiting_for_user"}
    assert len(runs) == 6, runs
    for run in runs:
        # 角色不唯一（三个 D）⇒ 认领靠 end_ts，不靠角色
        assert run["end_ts"], f"这一趟没有 end_ts（被别人的 start 顶掉了）：{run}"
        assert run["stop_reason"], f"这一趟没有 stop_reason：{run}"
        owners = [t for t, ts in ends.items() if ts == run["end_ts"]]
        assert owners, f"它的 end_ts 不属于任何一趟：{run}"
        assert by_tid[owners[0]] == run["stop_reason"], (owners, run)
    # end_ts 两两不同（一条 end 只被一趟认领，没有张冠李戴）
    assert len({r["end_ts"] for r in runs}) == 6, sorted(r["end_ts"] for r in runs)
    # 每一趟的步数读的是它自己的收工行：子二的第二条步落在子四开跑之后，按位置数只能
    # 算到子四头上（子二会变 2、子四会变 2），而两条收工行都写 1。
    assert {r["steps"] for r in runs} == {1}, [(r["steps"], r["end_ts"]) for r in runs]
    # 对账看不见这一类错（索引与现算同源）：这条在这里是"为什么上面的直接读数才是判据"
    # 的机器记录，不是本用例的正题。
    SS.rebuild_run_index(root)
    report = SS.run_index_report(root)
    assert report["usable"] is True and report["drift"] == [], report


def test_a_single_agent_run_is_still_read_the_same(tmp_path: pathlib.Path) -> None:
    """判据 ③（反真空）：没有交错时读数逐格不变 —— 配对键换了，单趟的账不能变。

    改前/改后都必须绿：它守的是"为了让交错对上而把单代理那一档改坏"。
    """
    root = tmp_path / "ws"
    root.mkdir()
    sid = "s-solo"
    A = SS.append
    A(root, _ev("agent_run_start", role="M", task="独跑一趟", task_id="t-000001",
                ts="2026-01-01T00:00:00+00:00"), sid=sid)
    for i in range(3):
        A(root, _ev("agent_step", role="M", index=i, shape="fs.write",
                    ts=f"2026-01-01T00:00:0{i + 1}+00:00"), sid=sid)
    A(root, _ev("llm_call", role="M", task_id="t-000001", ok=True, usd=0.25,
                ts="2026-01-01T00:00:04+00:00"), sid=sid)
    A(root, _ev("llm_call", role="M", task_id="t-000001", ok=True, usd=None,
                ts="2026-01-01T00:00:05+00:00"), sid=sid)
    A(root, _ev("agent_run_end", role="M", task_id="t-000001", stop_reason="final",
                steps=3, final_chars=6, summons=1, messages=0, elapsed_sec=2.5,
                spend={"calls": 2, "usd": 0.25}, ts="2026-01-01T00:00:06+00:00"), sid=sid)
    runs = SS.runs_in_session(SS.read_session(root, sid=sid)[0], sid=sid)
    assert len(runs) == 1, runs
    run = runs[0]
    assert (run["steps"], run["llm_calls"], run["stop_reason"]) == (3, 2, "final"), run
    assert (run["usd"], run["unknown_usd"]) == (0.25, 1), run
    assert (run["start_index"], run["end_index"]) == (0, 6), run
    assert (run["start_ts"], run["end_ts"]) == ("2026-01-01T00:00:00+00:00",
                                                "2026-01-01T00:00:06+00:00"), run
    assert (run["final_chars"], run["summons"], run["messages"], run["elapsed_sec"]) == \
        (6, 1, 0, 2.5), run
    assert run["events_in_run"] == 6, run
    assert (run["last_shape"], run["waiting_on"], run["waiting"]) == ("fs.write", [], False), run
