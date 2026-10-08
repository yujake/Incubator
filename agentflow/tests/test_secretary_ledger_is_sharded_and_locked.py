# -*- coding: utf-8 -*-
"""S1m：秘书台账分片 + 追加加锁 + `seq` 锁内读改写 + 存活读数（`draft/92` §3.3）。

## 为什么要这一批（只读核实的读数）

`draft/91` §7 与 `draft/94` §1/§2：真机上 61 个工作区里只有 2 个有秘书台账、
文件名只有 `M`、合计 79 行、`seq` 0 重号。⇒ 这两条缺陷（D106 文件只有角色维度、
D107 写入无锁且 `seq` 是"读后写"）在真机上没发生过，因为同角色同时只有一个秘书在写。
但并发是框架自己允许的（`summon_many` 的多 `instance`）⇒ 判据只能自造并发。

## 本文件钉住五件事

1. 正控（分片 + 并发）：同角色的两个实例各 200 行并发追加 ⇒ 每片 200 行、
   `seq` 严格 1..200 无重号（改前必红：两个实例写同一个文件、`seq` 读后写 ⇒ 重号）；
2. 正控（读侧兼容）：老 `<role>.jsonl` 仍可读，且 `decisions()` 把"老文件 + 本实例片"
   一起交回；`merged_decisions()` 给整角色视图（WebUI 那一面靠它）；
3. 负控（一个写者一片）：两片互不污染（A 片的行不出现在 B 片里）；
4. 反真空（存活三态）：绑过 = 标记在 + pid 活着；没绑过/已注销 = `checked=True, alive=False`；
   标记坏掉 = `checked=False`（"没查成"与"没绑过"分开）；
5. 同生同死：`close()` 之后标记消失、`alive=False`，且重复 close 幂等。
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import pathlib
from typing import Any

from agentflow.secretary import Secretary, append_jsonl, decisions_path


def _rows(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def test_two_instances_append_concurrently_without_duplicate_seq(tmp_path: pathlib.Path):
    """正控（本批的主判据）：两个实例并发各追加 200 行 ⇒ 每片 200 行、`seq` 无重号。

    改前必红：`note_decision` 先读全表算 `seq`、再裸 `open("a")` ⇒ 两个实例写同一个文件，
    并发下会拿到同一个 `seq`（`draft/91` §7 的 D107），而且两边的 400 行混在一个文件里。
    """
    a = Secretary("D", root=tmp_path)
    b = Secretary("D", root=tmp_path)
    a.bind_task("t-0011")
    b.bind_task("t-0012")
    assert a.decisions_path() != b.decisions_path(), (a.decisions_path(), b.decisions_path())

    def _write(sec: Secretary, n: int) -> None:
        for i in range(n):
            sec.note_decision(duty=1, kind="secretary_optimized", decision="已优化",
                              reason=f"并发写入 {i}")

    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda f: f(), [lambda: _write(a, 200), lambda: _write(b, 200)]))

    ra = _rows(a.decisions_path())
    rb = _rows(b.decisions_path())
    assert len(ra) == 200 and len(rb) == 200, (len(ra), len(rb))
    for rows, who in ((ra, "t-0011"), (rb, "t-0012")):
        seqs = [int(r["seq"]) for r in rows]
        assert sorted(seqs) == list(range(1, 201)), (who, sorted(seqs)[:5], sorted(seqs)[-5:])
        assert {str(r.get("task_id")) for r in rows} == {who}, who


def test_legacy_file_is_still_readable_and_merged(tmp_path: pathlib.Path):
    """正控（读侧兼容）：老文件仍在、仍可读；`decisions()` = 老文件 + 本实例片。"""
    root = tmp_path
    legacy = decisions_path(root, "D")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    ok, why = append_jsonl(legacy, {"at": "2026-10-08T21:00:00+08:00", "role": "D",
                                    "kind": "secretary_decision", "decision": "可派",
                                    "reason": "历史行"})
    assert ok, why

    s = Secretary("D", root=root)
    s.bind_task("t-0021")
    s.note_decision(duty=1, kind="secretary_optimized", decision="已优化", reason="本实例")
    got = s.decisions()
    assert len(got) == 2, got
    assert {str(r.get("reason")) for r in got} == {"历史行", "本实例"}, got
    merged = s.merged_decisions()
    assert len(merged) == 2, merged          # 整角色视图：老文件 + 全部分片


def test_two_shards_do_not_pollute_each_other(tmp_path: pathlib.Path):
    """负控（一个写者一片）：A 片的行不出现在 B 片里（分片不是"换个地方混写"）。"""
    a = Secretary("D", root=tmp_path)
    b = Secretary("D", root=tmp_path)
    a.bind_task("t-0031")
    b.bind_task("t-0032")
    a.note_decision(duty=1, kind="secretary_optimized", decision="已优化", reason="A 的行")
    b.note_decision(duty=1, kind="secretary_optimized", decision="已优化", reason="B 的行")
    assert [r["reason"] for r in _rows(a.decisions_path())] == ["A 的行"]
    assert [r["reason"] for r in _rows(b.decisions_path())] == ["B 的行"]


def test_alive_reading_is_three_state_and_closes(tmp_path: pathlib.Path):
    """反真空 + 同生同死：绑过 ⇒ 活着；注销 ⇒ 不活着；没绑过 / 标记坏 ⇒ 三态各一格。"""
    s = Secretary("D", root=tmp_path)
    never = s.secretary_alive()
    assert never["checked"] is True and never["alive"] is False, never

    s.bind_task("t-0041")
    hot = s.secretary_alive()
    assert hot["checked"] is True and hot["alive"] is True and hot["pid"] > 0, hot
    assert s.close()["closed"] is True
    after = s.secretary_alive()
    assert after["checked"] is True and after["alive"] is False, after

    # 标记坏掉 ⇒ 没读成（不许折成"死"或"活"）
    s.bind_task("t-0042")
    s.alive_path().write_text("{不是 JSON\n", encoding="utf-8")
    bad = s.secretary_alive()
    assert bad["checked"] is False and "读不成" in bad["reason"], bad
    s.close()


def test_close_is_idempotent_and_unbound_close_is_three_state(tmp_path: pathlib.Path):
    """边界：重复 close 幂等；没绑过的秘书 close 要如实说"没绑"（不许假装收过了）。"""
    s = Secretary("D", root=tmp_path)
    first = s.close()
    assert first["checked"] is False and "没绑定" in first["reason"], first
    s.bind_task("t-0051")
    assert s.close()["closed"] is True
    again = s.close()
    assert again["checked"] is True and again["closed"] is True, again
