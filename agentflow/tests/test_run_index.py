# -- coding: utf-8 --
"""趟次索引与事件的对账判据（裁定 O2；`draft/75 §3` 的判据 F）。

## 这一组守什么

索引是派生数据：它可能与源不一致。所以这里的第一条纪律不是"索引读得出来"，
而是"索引与 `sessions/*.jsonl` 的事件现算结果逐趟一致"，且不一致时报出来：

| 用例 | 正控 / 负控 | 造什么 | 该红还是该绿 |
|---|---|---|---|
| `test_the_index_agrees_with_the_events_run_by_run` | 正控 | 两场各两趟 ⇒ 索引逐趟 == 现算 | 绿 |
| `test_a_tampered_index_byte_is_caught` | 负控 | 手改索引里的 `steps` 一个字节 | 红（`drift`） |
| `test_a_deleted_session_while_the_index_still_has_it_reports_drift` | 负控 | 删掉一场会话、索引还在 | 红（`drift` 点名那场会话） |
| `test_an_absent_index_is_unreadable_not_computed` | 负控（三态） | 索引不在盘上 | `tri=unreadable`，不是 `computed` |
| `test_an_empty_workspace_is_not_applicable` | 负控（三态） | 一场会话都没有 | `tri=not_applicable` |
| `test_the_event_kind_constants_match_userio` | 反真空 | 字面量与 `userio` 的常量 | 相等 |

## 名字的边界（不许混用）

这里的「趟次」是会话内的第几趟（一条 `agent_run_start` → `agent_run_end`）。
`projects.py` 的 `run_index: int` 是"这个项目第几趟"（配 `out/run-<n>`）——另一个概念，
本文件一个字都不碰它（`draft/78 §7` 的提醒）。

## 「红前绿后」是怎么做到的

负控都先断言正控那一份是绿的（`usable is True` / `drift == []`），再改一个字节，
再断言它红了。少了前面那一步，"改坏了也没红"这件事可能是因为尺子本来就没接上。
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
