# -*- coding: utf-8 -*-
"""R26 第三段的数据半（`draft/37` §14.5 第 4 件 / §16 P3 的"问用户续跑"）。

## 这一组守什么（以及不守什么）

R26 要的是三段读数：问 → 答 → 续跑。前两段已经有判据（§22 的门判"还有问题没答
就必须停在等待用户"；§24 的验收判"问过/答过/还欠"两个读数）。这一组补的是第三段的数据半：

1. `--resume` 那一次必须读得到用户刚写下的回答（`_latest_user_answer` 走的是与
   `agentflow answer` 完全同一条事件流 —— 两处各读一份就会分家）；
2. 没有回答不许读成同意：一次都没答时返回空串（而不是"上次那句"或某个默认值），
   否则"我没回答"会被当成"我默许了"——这正是三态纪律要挡的形态；
3. 用户说停（`STOP_TOKEN`）那一条路必须在开跑下一轮之前生效
   （`_stop_before_round` 的顺序是 rounds → budget → stop_file → user_stop）。

不守什么：真的跑一次 `run_autonomous(resume=True)` 并把报告更新出来 —— 那需要一次
完整的模型循环；本环境没有 key（§23.6），所以那一段留给 §17.3 的真机轮次。
把边界写在这里，免得读的人以为第三段已经全验了。
"""
from __future__ import annotations

import pathlib

from agentflow import autonomy as AU
from agentflow import userio as U


def _ask_and_answer(root: pathlib.Path, *, qid: str, question: str, answer: str | None) -> None:
    """问一个问题（超时即"没答"），可选地写一条回答 —— 走的就是 CLI 的那两个入口。"""
    got = U.ask_user(root, role="D", question=question, timeout_sec=0.0, qid=qid)
    assert got.problem == "user_no_answer", got
    if answer is not None:
        assert U.answer_question(root, qid=qid, answer=answer) == ""


def test_resume_reads_back_the_answer_the_user_just_wrote(tmp_path: pathlib.Path):
    """第三段（数据半）：`agentflow answer` 写下的那句话，`--resume` 那一次读得回来。"""
    root = tmp_path / "ws"
    root.mkdir()
    _ask_and_answer(root, qid="q0001", question="「审」还是「研」？", answer="审")
    answer, notes = AU._latest_user_answer(root, "D", sid=None)
    assert answer == "审", (answer, notes)
    assert notes == [] or all("读会话记录" in n for n in notes), notes


def test_no_answer_does_not_read_as_consent(tmp_path: pathlib.Path):
    """反真空（三态）：一次都没答 ⇒ 空串，不许读成同意（也不许读成上次那句）。"""
    root = tmp_path / "ws"
    root.mkdir()
    _ask_and_answer(root, qid="q0001", question="要不要换一篇来源？", answer=None)
    answer, _notes = AU._latest_user_answer(root, "D", sid=None)
    assert answer == "", f"没回答却读出了 {answer!r} —— 这是把「没答」当成了「答了」"


def test_the_latest_answer_wins_when_the_user_changes_their_mind(tmp_path: pathlib.Path):
    """用户改主意：最后一条才算数（续跑读的是最新那句话，不是第一条）。"""
    root = tmp_path / "ws"
    root.mkdir()
    _ask_and_answer(root, qid="q0001", question="先问一次", answer="再审一轮")
    _ask_and_answer(root, qid="q0002", question="再问一次", answer="算了，收工")
    answer, _notes = AU._latest_user_answer(root, "D", sid=None)
    assert answer == "算了，收工", answer


def test_saying_stop_halts_before_the_next_round(tmp_path: pathlib.Path):
    """说停那一条路：`STOP_TOKEN` 必须在开跑下一轮之前生效（不是跑完才看）。"""
    assert AU._stop_before_round(1, rounds=9, spent_usd=0.0, usd_budget=None,
                                 stop_path=None, user_answer="") == ""
    assert AU._stop_before_round(1, rounds=9, spent_usd=0.0, usd_budget=None,
                                 stop_path=None, user_answer=f"别做了 {AU.STOP_TOKEN}") == "user_stop"
    # 顺序是确定的：轮次先于预算先于停止文件先于用户的话（多条同时成立时只给一个答案）
    stop_file = tmp_path / "STOP"
    stop_file.write_text("x", encoding="utf-8")
    assert AU._stop_before_round(10, rounds=9, spent_usd=99.0, usd_budget=1.0,
                                 stop_path=stop_file, user_answer=AU.STOP_TOKEN) == "rounds"


def test_a_round_that_stopped_waiting_for_the_user_stops_the_driver(tmp_path: pathlib.Path):
    """`draft/37` §72：上一轮停在等用户、而那个问题还挂着 ⇒ 多轮驱动「不许」开下一轮。

    三个方向都要判（少一个就有个静默方向）：
    ① 停过 + 问题还在 ⇒ 停成 `waiting_for_user`；
    ② 停过 + 人已经答了（待答清单空了）⇒ 「放行」（那一轮要带着回答接着跑，
       这正是 `tests/test_resume_runs_and_consumes_answer.py` 守的那条路）；
    ③ 上一轮正常收工 ⇒ 不许误伤（负控）。
    """
    base = dict(rounds=9, spent_usd=0.0, usd_budget=None, stop_path=None)
    assert AU._stop_before_round(2, user_answer="", last_stop_reason="waiting_for_user",
                                 pending_qids=("q0001",), **base) == "waiting_for_user"
    assert AU._stop_before_round(2, user_answer="审这篇论文",
                                 last_stop_reason="waiting_for_user",
                                 pending_qids=(), **base) == ""
    assert AU._stop_before_round(2, user_answer="", last_stop_reason="final",
                                 pending_qids=("q0001",), **base) == ""
    # 旧口径（不给这两个新参数）行为不变：这一条是"不回归"的钉子
    assert AU._stop_before_round(2, user_answer="", **base) == ""


def test_the_three_segments_are_readable_from_the_same_records(tmp_path: pathlib.Path):
    """三段读数从同一份记录里读得出（问 / 答 / 还欠），而且三段互相咬。"""
    root = tmp_path / "ws"
    root.mkdir()
    _ask_and_answer(root, qid="q0001", question="这条要不要问用户？", answer="要，先问")
    _ask_and_answer(root, qid="q0002", question="第二个问题", answer=None)
    asked = U.pending_questions(root)
    replies = U.read_replies(root)
    assert len(asked) == 1 and asked[0].qid == "q0002", asked
    assert len(replies) == 1 and replies[0]["qid"] == "q0001", replies
    assert replies[0]["answer"] == "要，先问"
    # 第三段读得到最新回答，而"还欠一个"这件事同时看得见 —— 两者不许互相盖掉
    answer, _ = AU._latest_user_answer(root, "D", sid=None)
    assert answer == "要，先问"
