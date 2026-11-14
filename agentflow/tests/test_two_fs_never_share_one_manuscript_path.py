# -*- coding: utf-8 -*-
"""判据（E / 并发 P1）：同一稿件路径写互斥 —— 两个写者不许共用一个文件名。

现场（`temp/analysis/10-concurrency-budget.md` §2.1）：两个并行的 F（`F#1` / `F#2`）
把稿落到同一个 `reports/f-proof-000001.md` 上（一个起草、一个改稿+转送），两条送审
路径因此指向同一个正文 sha。改前号源只回答"盘上这个号被占了没有"，回答不了
"这一份稿归谁写" —— 第二笔会就地覆盖第一份。

选的是「受控拒」（不是「自动分号」）：走到落稿那一刻 `mid` 已经是调用方点名要写的
那一份（`product.manuscript_id` / 上一轮沿用的号），悄悄换号会把它后面的读数
（`manuscript_path(mid)` / 送审 / 收录）指到另一份稿上。自动分号只发生在"还没有号"
的分配那一支（`next_manuscript_id` 跳过别人占着的号）——判据 b 量的就是它。

判据：
1. 同路径二次落稿（另一个写者）⇒ 受控拒 `manuscript_path_taken`，盘上那份一个字没变；
2. 负控：两个写者各自新开稿 ⇒ 各拿各的号、互不影响（自动分号那一半）；
3. 同一写者续写自己的稿 ⇒ 照常（`mine`，续跑不被自己上一次的占用挡住）；
4. 反真空：把占用判据打成恒 `free` ⇒ 第 1 条必红（第二笔真的覆盖了第一份）。
"""
from __future__ import annotations

import pathlib

from agentflow import manuscriptids as MID
from agentflow.agent_f import AgentF
from agentflow.store import Store

FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
SG = {"sid": "s1", "text": "证明弦长函数非常值"}
PLAN = {"plan_id": "p-1"}


def _product(tag: str) -> dict:
    return {"proposition": f"{FULL}（{tag}）",
            "steps": [{"text": f"第 1 步：{tag}", "cites": []},
                      {"text": f"第 2 步：{tag}", "cites": []}]}


def _writer(st: Store, name: str) -> AgentF:
    """一个 F 写者：`actor` 就是 host 造的写者身份（真机 `F#1` / `F#2` 两实例）。"""
    return AgentF(st, config={"workspace_root": str(st.root)}, actor=name)


def _env(tmp_path: pathlib.Path) -> tuple[Store, AgentF, AgentF]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, _writer(st, "agent-F-F#1"), _writer(st, "agent-F-F#2")


def test_another_writer_cannot_take_the_same_manuscript_path(tmp_path: pathlib.Path) -> None:
    """同路径二次落稿（另一个写者）⇒ 受控拒，盘上那份一个字没变。"""
    st, f1, f2 = _env(tmp_path)
    first = f1.proof_manuscript(_product("甲"), sg=SG, plan=PLAN)
    assert first["ok"] is True, first
    rel, mid = str(first["path"]), str(first["manuscript_id"])
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")

    second = f2.proof_manuscript(_product("乙"), sg=SG, plan=PLAN, manuscript_id=mid)

    assert second["ok"] is False, second
    assert second["refused"] == "manuscript_path_taken", second
    assert second["kind"] == "manuscript_path_taken", second
    assert second["written"] is False, second
    assert str(second["path"]) == rel, second
    assert "agent-F-F#1" in str(second["why"]), second["why"]
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before, (
        "被拒之后盘上那份稿还是被改了 —— 互斥没生效")
    # 占用登记读得出来：这一份归 F#1。
    got = MID.claim_for_write(st.root, rel, owner="agent-F-F#1")
    assert got["state"] == "mine", got


def test_two_writers_each_open_their_own_manuscript(tmp_path: pathlib.Path) -> None:
    """负控：两个写者各自新开稿 ⇒ 各拿各的号（自动分号），互不影响。"""
    st, f1, f2 = _env(tmp_path)
    one = f1.proof_manuscript(_product("甲"), sg=SG, plan=PLAN)
    two = f2.proof_manuscript(_product("乙"), sg=SG, plan=PLAN)

    assert one["ok"] is True and two["ok"] is True, (one, two)
    assert one["path"] != two["path"], (one["path"], two["path"])
    assert one["manuscript_id"] != two["manuscript_id"], (one, two)
    assert (pathlib.Path(st.root) / one["path"]).is_file()
    assert (pathlib.Path(st.root) / two["path"]).is_file()


def test_the_same_writer_may_rewrite_its_own_manuscript(tmp_path: pathlib.Path) -> None:
    """同一写者续写自己的稿 ⇒ 照常（`mine`）：续跑不被自己上一次的占用挡住。"""
    st, f1, _f2 = _env(tmp_path)
    first = f1.proof_manuscript(_product("甲"), sg=SG, plan=PLAN)
    assert first["ok"] is True, first
    again = f1.proof_manuscript(_product("甲改"), sg=SG, plan=PLAN,
                                manuscript_id=str(first["manuscript_id"]))
    assert again["ok"] is True, again
    assert again["path"] == first["path"], (again, first)
    assert "甲改" in (pathlib.Path(st.root) / str(again["path"])).read_text(encoding="utf-8")


def test_anti_vacuum_stubbing_the_occupancy_judge_lets_it_overwrite(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：占用判据打成恒 free ⇒ 第二笔真的覆盖第一份（第 1 条必红）。"""
    st, f1, f2 = _env(tmp_path)
    first = f1.proof_manuscript(_product("甲"), sg=SG, plan=PLAN)
    assert first["ok"] is True, first
    rel, mid = str(first["path"]), str(first["manuscript_id"])
    monkeypatch.setattr(MID, "claim_for_write",
                        lambda *a, **kw: {"checked": True, "state": "free",
                                          "rel": str(kw.get("rel") or a[1]),
                                          "holder": {}, "why": "打桩：恒 free"})

    second = f2.proof_manuscript(_product("乙"), sg=SG, plan=PLAN, manuscript_id=mid)

    assert second["ok"] is True, ("打桩之后仍然被拒 —— 打桩没生效，反真空不成立", second)
    body = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert "乙" in body, ("打桩之后第二笔没有覆盖 —— 反真空不成立", body[:200])
