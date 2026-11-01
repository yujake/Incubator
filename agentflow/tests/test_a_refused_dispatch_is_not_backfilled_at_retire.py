# -*- coding: utf-8 -*-
"""判据：被写口拒掉的派活，不许在收工兜底里被补成新名字；真孤儿仍要补。

## 业主 2026-11-02 的裁定（收窄 `retire` 的收工兜底）

上一版：`retire` 在解析名字之前先跑 `roster_repair`，把"台账有、名册没有"的行全部
补上。于是派活时被 `name_taken` / `task_id_reused` 拒掉的号，会在下一次任何人销号时
拿到一个新名字（`temp/probe_h11_leftovers.py` 的 L 读数：`adds_after_retire` 多出
`D2/t-000012 repaired=true`）。业主裁定：被拒是一次有记录的决定，收口时再把它变成
子节点等于悄悄改写事实 —— 而这正是这一轮在治的病。

收窄后的口径：只补"从未登记过、也没有一次被拒记录"的行。判别式为什么是"拒绝记录"
而不是时间戳：拒绝当时名册三份一个字节都没写，跨进程唯一靠得住的证据就是拒绝那一刻
落下的那一条流水（`out/roster/refusals/<父>.jsonl`）。

## 这一组守什么

1. 正题（`name_taken`，2026-11-01 新口径）：第二件活撞名被拒、但它真跑过
   （`status=done / outcome=ok`）⇒ 销号时补一个从未用过的新名字（不是 D1），
   add 行三格齐全，按新名寻址/销号都叫得到，第二次自愈 `fixed=0`；
2. 正题（`not_in_roster`，新号）：复用一个名册里没有的名字被拒、但真跑过 ⇒ 同上。
   为什么不再用 `task_id_reused`：那个理由码的前提恰恰是"这个号已经在 known 里"，
   于是销号兜底本来就不会补它 —— 实测两棵树的 `adds_after_retire` 完全相同（都只有
   `D1/t1`）⇒ 那条判据恒绿，等于没量。换成新号之后，改前（2c7b29da）销号会真的多出
   一行 `D2/t2`（行为红），改后才不多；
3. 反真空（真孤儿）：台账里有、名册里没有、没有拒绝记录 ⇒ 收工兜底仍然要补，
   否则 79 那趟"11 个节点卡住"会复发；
4. 三态：拒绝流水读不出来 ⇒ `roster_repair` 不补（返回非空问题），不许把"读不到"
   当成"没被拒过"；
5. 负控：把 `roster_repair` 打桩成 no-op ⇒ 第 3 条（真孤儿仍要补）必红。没有这一条，
   第 3 条的绿可能来自别处顺手补的行，"补的行为还在"就没有被人量过。
6. 正题（第三个口，`draft/158` 二-1）：被派活闸拒掉的号（`outcome="refused"`）不许被
   补成新名字 —— 那种拒绝只写在台账行上、不进 `refusals/*.jsonl`，本文件前五条盖不住；
7. 同批：上面那条收窄不许顺手把真孤儿排掉（第 3 条的加强版），且补出来的行要带
   `surface`（81 实测 13/13 条补登记行无面，正常行 52/52 有面）。

## 2026-11-01 业主裁定后的口径变更（`draft/160` 三-4 的丁案）

上一版把"被写口拒过"与"没跑过"折成同一类，于是 81 的 `t-000106`（真跑、`done/ok`、
有产物，只是父点名的 `E2` 被一个从没跑过的号占着）永久无名。业主裁定：判据从
"被拒过的号"改成"没跑过的号"。落地后本文件第 1、2 条改判：

- 没跑过的号（`outcome="refused"`，即派活闸拒掉的）永远不许补名 —— 原样保留
  （这是 d9ebb7fe 的实质，见下面第 6 条那两条正题）；
- 真跑过的无名号必须补一个从未用过的新名（不许是被拒的那个，B1 不动），
  且 add 行带 `named_after_run` / `requested_name` / `refusal_code` 三格留痕；
- 补名之后 `name_of` / `surface_of` / `retire(name=新名)` 都叫得到；
- 同一号不许补两次（第二次 `roster_repair` 必须 `fixed=0`）。

这不是放宽：改判的三条判据都是加强（三格留痕、可寻址、幂等），而被宽的只有
"真跑过、只是名字没落"这一档。

## 在旧树（2c7b29da）上怎么读

旧树没有 `SEC.refusals_path` 这个 API。若判据一开口就调它，红的是
`AttributeError: module 'agentflow.secretary' has no attribute 'refusals_path'`
—— 那是"新 API 不存在"，不是"retire 之后名册多一行"。所以本文件：

- 用 `_refusals_path()` 解析落点（新树走 API，旧树按同一份落点约定拼路径，只读）；
- 把"名册有没有多一行"的断言排在任何拒绝流水断言之前。

于是旧树上的红是行为红（`_ids` 多出被拒的号），而不是 API 缺失。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.secretary = Secretary("M", root=ws, store=st, enable_model=False)
    cond.roster_sink = cond.secretary
    top = cond.open_top_level_run("M", "顶趟这一趟")
    return cond, str(top), ws


def _child(cond: Conductor, parent: str, *, tag: str) -> str:
    return str(cond._write_new_row({
        "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 1, "input_key": f"judge:{tag}",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "判据夹具：一条已经收口的子行", "error": None,
        "started_at": BR, "ended_at": BR,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="judge:child"))


def _orphan(cond: Conductor, parent: str) -> str:
    """真孤儿：台账里有一行、名册里没有、也没有任何拒绝记录（实例分派那条路留下的形态）。"""
    return str(cond._write_new_row({
        "role": "D", "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "@orphan", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "D#1", "detail": "",
        "error": None, "started_at": BR, "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": ["conductor:admitted"],
    }, note="judge:orphan"))


def _gate_refused_child(cond: Conductor, parent: str, *, tag: str = "gate") -> str:
    """派活闸拒掉的号：一条真台账行，`outcome="refused"`，但从没跑过。

    这是 `draft/158` §一 的 ④ 那一档、也是本文件改前盖不住的那一档：`Conductor._refuse`
    给被闸拒的召唤建的就是这种行（`outcome="refused"`、`refusal_reason` 非空、
    `started_at == ended_at`、`tokens=0`、`parent_task_id` 保留），而它不进
    `out/roster/refusals/<父>.jsonl`（那份流水只记名册写口的拒绝）——
    于是只读流水的那一格看不见它，补登记会把它当成"真孤儿"发一个新名字。
    """
    return str(cond._write_new_row({
        "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 1, "input_key": f"judge:{tag}",
        "status": "done", "outcome": "refused",
        "refusal_reason": "concurrency_exceeded",
        "instance": "", "detail": "判据夹具：被派活闸拒掉的那一次（没跑，没有可登记的子代理）",
        "error": None, "started_at": BR, "ended_at": BR,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="judge:gate_refused"))


def _ids(cond: Conductor, parent: str) -> list[str]:
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    return [str(r.get("task_id")) for r in rows]


def _row_of(cond: Conductor, parent: str, task_id: str) -> dict:
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    row = next((r for r in rows if str(r.get("task_id")) == task_id), None)
    assert row is not None, (task_id, rows)
    return row


def _refusals_path(ws: pathlib.Path, owner: str) -> pathlib.Path:
    """拒绝流水的落点：新树走 `secretary.refusals_path`，旧树（2c7b29da）没有这个 API。

    为什么判据自己拼一次旧落点：这一组要量的行为是"销号之后名册里有没有多一行"，
    它不依赖那个函数存在。旧树上一开口就调未定义的 API，红的是 AttributeError
    （量到的是"新 API 不存在"），而不是"被拒的号被补了一行"（行为红）。这里只解析
    路径（同一份落点约定 `out/roster/refusals/<父>.jsonl`），不碰写侧、不改断言。
    """
    fn = getattr(SEC, "refusals_path", None)
    if callable(fn):
        return pathlib.Path(fn(ws, owner))
    return pathlib.Path(ws).joinpath("out", "roster", "refusals", f"{owner}.jsonl")


def _refused_lines(ws: pathlib.Path, owner: str) -> list[dict]:
    path = _refusals_path(ws, owner)
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _new_named_row(cond, parent: str, task_id: str) -> dict:
    """那个号补出来的 add 行（读盘上的行，不读折叠视图 —— 留痕三格只在 add 行上）。"""
    path = SEC.roster_path(cond.store.root, parent)
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    got = [r for r in rows if str(r.get("kind") or "") == "add"
           and str(r.get("task_id") or "") == task_id]
    assert len(got) == 1, (task_id, rows)
    return got[0]


def _a_really_ran_refusal_is_named(cond, parent: str, t1: str, t2: str,
                                   want: str, code: str) -> None:
    """判据①②③④的共用断言（2026-11-01 新口径）。"""
    sec = cond.secretary
    rows = _ids(cond, parent)
    assert rows == [t1, t2], (
        "真跑过的那一件必须被补名（新口径：判据从『被拒过』改成『没跑过』）", rows)
    row2 = _row_of(cond, parent, t2)
    new = str(row2.get("name") or "")
    assert new and new != want, ("不许复用被拒的那个名字（B1）", row2)
    # ② 三格留痕：它当初想叫什么、哪一档拒的、是不是跑过之后才补的名
    disk = _new_named_row(cond, parent, t2)
    assert disk.get("named_after_run") is True, disk
    assert str(disk.get("requested_name") or "") == want, disk
    assert str(disk.get("refusal_code") or "") == code, disk
    assert str(disk.get("surface") or ""), ("补出来的行也要有面（1cdacbf6 的口径）", disk)
    # ③ 补名之后按新名寻址 / 按新名销号都叫得到
    assert sec.name_of(owner=parent, task_id=t2)[0] == new
    assert sec.resolve_down(owner=parent, name=new)[0] == t2
    assert sec.surface_of(owner=parent, task_id=t2).get("checked") is True
    # ④ 同一号不许补两次（第二次自愈 fixed=0，名册不多行）
    assert sec.roster_repair(owner=parent) == (0, "", [])
    assert _ids(cond, parent) == [t1, t2]


def test_a_name_taken_dispatch_is_named_at_retire_under_the_new_ruling(
        tmp_path: pathlib.Path) -> None:
    """正题（2026-11-01 新口径）：撞名被拒但真跑过的那件活，销号时补一个从未用过的新名。"""
    cond, parent, ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    t2 = _child(cond, parent, tag="second")      # 判据夹具：done/ok ⇒ 真跑过
    rec = cond._register_roster(task_id=t2, role="D", owner=parent,
                                meta={"name": "D1", "brief": "第二件活", "task": "接着做"})
    assert str(rec.get("refusal_code") or "") == "name_taken", rec
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="判据")
    assert got.get("ok") is True, got
    # 拒绝流水一条不少（拒绝本身没被改写）
    refused = _refused_lines(ws, parent)
    assert [str(r.get("task_id")) for r in refused] == [t2], refused
    assert str(refused[0].get("refusal_code")) == "name_taken", refused
    # 回执要说清"它当初点名 D1 被拒、现在叫什么"
    assert any("补名" in str(w) and "D1" in str(w) for w in (got.get("why") or [])), got
    _a_really_ran_refusal_is_named(cond, parent, t1, t2, "D1", "name_taken")


def test_a_not_in_roster_dispatch_is_named_at_retire_under_the_new_ruling(
        tmp_path: pathlib.Path) -> None:
    """正题（2026-11-01 新口径）：复用一个名册里没有的名字被拒、但真跑过 ⇒ 同样补新名。"""
    cond, parent, ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    t2 = _child(cond, parent, tag="second")
    before = _ids(cond, parent)
    assert t2 not in before, before
    rec = cond._register_roster(task_id=t2, role="D", owner=parent,
                                meta={"reuse": "D9", "brief": "复用一个不存在的名字",
                                      "task": "接着做"})
    assert str(rec.get("refusal_code") or "") == "not_in_roster", rec
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="判据")
    assert got.get("ok") is True, got
    refused = _refused_lines(ws, parent)
    assert [str(r.get("task_id")) for r in refused] == [t2], refused
    assert [str(r.get("refusal_code")) for r in refused] == ["not_in_roster"], refused
    _a_really_ran_refusal_is_named(cond, parent, t1, t2, "D9", "not_in_roster")


def _running_child(cond, parent: str, *, tag: str) -> str:
    """一条还在飞的子行（`status=running`、没有 `ended_at`）：真跑证据不成立。"""
    return str(cond._write_new_row({
        "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 1, "input_key": f"judge:{tag}",
        "status": "running", "outcome": None, "refusal_reason": None, "instance": "",
        "detail": "判据夹具：还在跑", "error": None,
        "started_at": "2026-10-29T17:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"judge:running:{tag}"))


def test_a_refused_registration_without_run_evidence_is_never_named(
        tmp_path: pathlib.Path) -> None:
    """①（新口径的硬边）：写口拒过、但没有真跑证据（还在飞/无 `ended_at`）⇒ 永远不补。

    这一条与上面两条是同一口径的两端：判据从"被拒过"改成"没跑过"，而"跑没跑"由
    `status` / `ended_at` 判 —— 还在飞的号既不是"跑过"，也不许被补名（159 的洞）。
    它落定之后才补：见下一条。
    """
    cond, parent, _ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    flying = _running_child(cond, parent, tag="flying")
    rec = cond._register_roster(task_id=flying, role="D", owner=parent,
                                meta={"name": "D1", "brief": "还在跑的那件", "task": "接着做"})
    assert str(rec.get("refusal_code") or "") == "name_taken", rec
    fixed, why, skipped = sec.roster_repair(owner=parent)
    assert fixed == 0 and why == "", (fixed, why, skipped)
    assert flying not in _ids(cond, parent), ("还在飞的不许被补名", _ids(cond, parent))
    # 把拒绝流水那条留着（拒绝是真的），但号没跑完 ⇒ 依然不补
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="判据")
    assert got.get("ok") is True, got
    assert flying not in _ids(cond, parent)


def test_the_same_number_is_named_once_it_really_ran(tmp_path: pathlib.Path) -> None:
    """①→②：同一号落定（有 `ended_at`、`done/ok`）之后，下一次自愈必须补它，且只补一次。"""
    cond, parent, _ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    flying = _running_child(cond, parent, tag="flying")
    cond._register_roster(task_id=flying, role="D", owner=parent,
                          meta={"name": "D1", "brief": "还在跑的那件", "task": "接着做"})
    assert sec.roster_repair(owner=parent)[0] == 0
    # 落定：它真跑完了
    row = dict(cond._task(flying) or {})
    row.update({"status": "done", "outcome": "ok",
                "ended_at": "2026-10-29T17:05:00+08:00"})
    with cond.store.tx("tasks", actor="test", note="judge:settle") as tx:
        tx.upsert("tasks", row, note="judge:settle")
    fixed, why, _skipped = sec.roster_repair(owner=parent)
    assert fixed == 1 and why == "", (fixed, why, _ids(cond, parent))
    named = _row_of(cond, parent, flying)
    assert str(named.get("name") or "") not in ("", "D1"), named
    disk = _new_named_row(cond, parent, flying)
    assert str(disk.get("requested_name") or "") == "D1", disk
    assert disk.get("named_after_run") is True, disk
    # 幂等：再跑一次 fixed=0
    assert sec.roster_repair(owner=parent) == (0, "", [])


def test_a_real_orphan_is_still_backfilled(tmp_path: pathlib.Path) -> None:
    """反真空：台账有、名册没有、也没有拒绝记录 ⇒ 收工兜底仍然补（79 那趟的形态）。"""
    cond, parent, _ws = _env(tmp_path)
    orphan = _orphan(cond, parent)
    before = _ids(cond, parent)
    assert orphan not in before, before
    got = cond.secretary.retire(owner=parent, name="谁都不叫这个名字", by_task_id=parent)
    assert got.get("ok") is False, got            # 名字不存在 ⇒ 仍被拒
    assert orphan in _ids(cond, parent), (
        "真孤儿也没补上：收窄过头了（79 那趟'11 个节点卡住'会复发）", _ids(cond, parent))


# ====================================================================== 第三个口：派活闸
# `draft/158` §一/§二-1（2026-11-01 的 81 趟）：13 行 `repaired` 里 7 条
# （t-000078/79/80、t-000027/28、t-000030/31）是 `concurrency_exceeded` 派活闸拒掉的号。
# 它们不是"被写口拒掉的派活"（本文件上面那两条正题），而是另一种拒绝：
# `Conductor._refuse` 给被闸拒的召唤建一条真台账行（`outcome="refused"`、
# `refusal_reason` 非空、`started_at==ended_at`、`tokens=0`），但它不进
# `out/roster/refusals/<父>.jsonl` —— 于是只读那份流水的 `roster_repair` 把它当成真孤儿。
# 换句话说：d9ebb7fe 只堵了"名册写口拒绝"这一个口，派活闸是第三个口。

def test_a_gate_refused_dispatch_is_not_backfilled(tmp_path: pathlib.Path) -> None:
    """正题：`outcome=refused`（`concurrency_exceeded`）的子不许被补登记发名字。

    改前必红（在 `2b7b98b5` 上实测）：`roster_repair` 的 todo 只排除 `known` 与
    `refusals/<父>.jsonl`，不看台账行的 `outcome` ⇒ 返回 `fixed=1`，名册里多一行
    `D2/t2 repaired=true`（81 那趟就是这么冒出 7 条假名册项的）。判据落点：
    `secretary.roster_repair` 的 todo 那一行。
    """
    cond, parent, ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    refused = _gate_refused_child(cond, parent)
    # 前提：它确实在台账里、且确实不在名册里、也不在拒绝流水里（那只记写口拒的）
    assert refused not in _ids(cond, parent)
    assert refused not in [str(r.get("task_id")) for r in _refused_lines(ws, parent)]
    fixed, why, _skipped = sec.roster_repair(owner=parent)
    assert fixed == 0, ("被派活闸拒掉的号被补成新名字了", fixed, why, _ids(cond, parent))
    assert why == "", why
    assert _ids(cond, parent) == [t1], _ids(cond, parent)


def test_a_gate_refused_dispatch_is_not_backfilled_at_retire(tmp_path: pathlib.Path) -> None:
    """正题（收工兜底那一侧）：销号触发的那一次 `roster_repair` 同样不许补它。

    与上一条分开写：上面量的是"补登记这个函数"，这里量的是"收工时它真的被调了一次"
    （`Secretary.retire` 里那一处），两条路各自都会把 81 那 7 条补成假名册项。
    """
    cond, parent, ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    refused = _gate_refused_child(cond, parent)
    assert refused not in _ids(cond, parent)
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="判据")
    assert got.get("ok") is True, got
    assert _ids(cond, parent) == [t1], (
        "销号兜底把派活闸拒掉的号补成了新名字", _ids(cond, parent))
    assert refused not in [str(r.get("task_id")) for r in _refused_lines(ws, parent)]


def test_the_gate_refusal_does_not_shadow_a_real_orphan(tmp_path: pathlib.Path) -> None:
    """反真空 + 补登记要有面：同一批里真孤儿仍要补，而补出来的 add 行带 `surface`。

    两半是一笔里的两件事：
    ① 只排除 `outcome=refused` 不许顺手把真孤儿也排掉（79 那趟"11 个节点卡住"会复发）；
    ② 补出来的行要走 `surface_alloc`：81 实测 13/13 条 repaired add 行没有 `surface`
       （正常的 52/52 条都有），于是 6 个真跑过的子代理一次都没切读写面
       （`out/roster/t-000015-surfaces.jsonl` 的 `alloc` 里 F3/F4 没有槽位）。
    """
    cond, parent, ws = _env(tmp_path)
    orphan = _orphan(cond, parent)
    refused = _gate_refused_child(cond, parent)
    fixed, why, _skipped = cond.secretary.roster_repair(owner=parent)
    assert (fixed, why) == (1, ""), (fixed, why, _ids(cond, parent))
    assert _ids(cond, parent) == [orphan], _ids(cond, parent)
    assert refused not in _ids(cond, parent), _ids(cond, parent)
    row = _row_of(cond, parent, orphan)
    assert str(row.get("surface") or ""), (
        "补登记行没有面：那条真跑过的子代理在 `surface_of` 里读到空槽，一次都切不到读写面",
        row)
    # 面上的 `alloc` 那一行也要在（不是只往名册里写了一个字符串）：池事件流是面分配的真身
    surfaces = pathlib.Path(ws).joinpath("out", "roster", f"{parent}-surfaces.jsonl")
    assert surfaces.is_file(), surfaces
    allocs = [json.loads(x) for x in surfaces.read_text(encoding="utf-8").splitlines() if x.strip()]
    allocs = [r for r in allocs
              if str(r.get("kind")) == "alloc" and str(r.get("name")) == str(row.get("name"))]
    assert len(allocs) == 1 and str(allocs[0].get("slot")) == str(row.get("surface")), allocs


def test_an_unreadable_refusal_ledger_is_not_an_empty_one(tmp_path: pathlib.Path) -> None:
    """三态：拒绝流水读不出来 ⇒ 不补（"读不到"不是"没被拒过"）。"""
    cond, parent, ws = _env(tmp_path)
    orphan = _orphan(cond, parent)
    ledger = _refusals_path(ws, parent)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("这不是 JSON\n", encoding="utf-8")
    fixed, why, _skipped = cond.secretary.roster_repair(owner=parent)
    assert fixed == 0, (fixed, why)
    assert why, ("拒绝流水读不出来却当成'没被拒过'补了行", _ids(cond, parent))
    assert orphan not in _ids(cond, parent), _ids(cond, parent)


def test_negative_control_a_noop_repair_makes_the_orphan_judgement_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：`roster_repair` 打桩成 no-op ⇒ 第 3 条（真孤儿仍要补）必红。

    为什么负控要写进判据文件：第 3 条绿只说明"孤儿在名册里"，不说明"是收工兜底补的"。
    只有在"把补登记拿掉它必红"时，"补的行为还在"才算被量过。打桩点取
    `Secretary.roster_repair`（`retire` 唯一的补登记入口），no-op 返回 `(0, "", [])`，
    不改生产代码、不放宽第 3 条的任何断言。
    """
    monkeypatch.setattr(Secretary, "roster_repair", lambda self, *, owner: (0, "", []))
    with pytest.raises(AssertionError) as caught:
        test_a_real_orphan_is_still_backfilled(tmp_path)
    assert "真孤儿也没补上" in str(caught.value), caught.value
    # 另起一份干净夹具，把"打桩之后名册里确实没有孤儿"读出来（读数，不靠猜）。
    cond, parent, _ws = _env(tmp_path / "neg")
    orphan = _orphan(cond, parent)
    got = cond.secretary.retire(owner=parent, name="谁都不叫这个名字", by_task_id=parent)
    assert got.get("ok") is False, got
    assert orphan not in _ids(cond, parent), _ids(cond, parent)
