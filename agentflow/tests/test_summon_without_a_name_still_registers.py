"""召唤时名册整份漏写：写侧兜底与逐份读数（2026-10-24 sylow4 真机缺陷的回归判据）。

## 事故（只读盘上证据，`projects/sylow4`）

台账 22 行代理，而 `out/roster/` 里只有 8 个父有文件；`t-000012` 与 `t-000015` 三份名册
文件一份都没有（`<父>.jsonl` / `<父>-index.jsonl` / `<父>-surfaces.jsonl`），它们的子
`t-000013` / `t-000016` 在任何名册文件里零命中 ⇒ 读侧 `unplaced=2`。

根因不是读侧拼不上，是写侧整份没落。两个 F 派 V 时给的那句简介分别是 68 / 70 字，
`Secretary.roster_add` 的内容闸（单行、不超过 `BRIEF_MAX` 字）在写盘之前就拒收了整份
登记 ⇒ 连 `surface_alloc` 都没跑到 ⇒ 三份文件一个都没被创建。可抢占派活的父代理那一步
只拿到"还在跑"（`_do_summon` 在句柄没落定时提前返回，读不到 `roster_problem`），
于是在现场这一次整份漏写是静默的 —— 唯一的事后读数是读侧的 `unplaced`。

## 修法（只加不删，既有语义不动）

- 召唤即登记：调用方没给 `name`、也没给 `reuse` ⇒ 显式走 `new=role`，名字由
  `Secretary.next_name` 按用过的最大序号顺延（不靠父记得给，也不会把同一个名字发给两个子代理）；
- 写侧兜底：父那句进不了名册（超长 / 多行）⇒ 改交空简介 + 任务原文，走秘书代写那一支
  （登记行里 `brief_source=secretary`），父的原文与被替换的理由进 `roster_note`；
- 逐份读数：`_register_roster` 写完之后读盘核对三份，缺哪一份、为什么，逐份进
  `roster_problem`；三态落 `SummonResult.roster_state`（`written` / `missing` / `unknown`）。

## 五条判据（a-e 与真机一一对应）

| 条 | 这条问什么 | 改前红在哪 |
|---|---|---|
| a | 不带 `name` 的子一派出，名册三份立刻各有一行 | 改前 brief 68 字被内容闸拒在写盘之前 ⇒ 三份都不存在 |
| b | 派两个同类 ⇒ 名字顺延 E1 / E2（不是两个无名、也不重号） | 改前两次都整份漏写，一条名字也发不出来 |
| c | 写侧说"成功"却没写盘 ⇒ `roster_problem` 逐份点名（负控：不许静默） | 改前只信秘书的返回值，盘上一行都没有也不报 |
| d | 反真空：把"自动发名"打桩成空 ⇒ a 必红 | 这一条证明 a 真的在测"名字由框架发"，不是被空名顺手带绿 |
| e | `summon_many` 同形：批量里每个不带名字的子各自登记 | 改前整批零行（与 a 同一处写侧缺口） |

一条对照（不是新判据）：`name` 由父给、简介正常的那一路，改前也写三份 —— 这一份不动它，
免得"只加"变成"顺手改既有语义"。

## 纪律

零模型调用（假后端只回一个 dict，一次网络/模型调用都不发）；盘上读数一律读文件
（`secretary.roster_path` 那一组），不读视图。
"""
from __future__ import annotations

import json
import pathlib
import threading
from typing import Any, Mapping

import pytest

from agentflow import secretary as SEC
from agentflow.conductor import Conductor
from agentflow.store import Store

MY_ROLE = "M"
CHILD = "E"
TASK = "对 statements 000002 的证明正文做逐行走审（proof 级复核）。材料：statements 000002 的 proof_text。"

#: sylow4 里 `t-000013` 的那一句（68 字）：超过 `BRIEF_MAX` ⇒ 改前整份登记被拒在写盘之前。
BRIEF_TOO_LONG = ("逐行走审 stmt 000002 Sylow 三定理 McKay 路线证明，"
                  "三态落 verifications/000002.jsonl")
#: sylow4 里 `t-000016` 的那一句（70 字）：同一个形状的第二例。
BRIEF_TOO_LONG_2 = ("逐行审 statements/000003 的 Wielandt Sylow 证明并签 "
                    "verifications/000003.jsonl")


class _Backend:
    """假后端：只回一个结果，不跑任何角色循环。

    `gated=True` 时它卡在放行上 —— 用来把"名册在派出去那一刻就在盘上"这件事做成结构事实
    （检查名册的时候孩子一定还在跑），而不是"我们跑得比它快"。
    """

    name = "fake"

    def __init__(self, *, gated: bool = False) -> None:
        self.gated = bool(gated)
        self.gate = threading.Event()
        self.calls: list[str] = []

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        self.calls.append(str(task_id))
        if self.gated and not self.gate.wait(timeout=20.0):
            return {"outcome": "no_result", "detail": "判据：等放行超时"}
        return {"outcome": "ok", "detail": "跑完了", "payload": {"ok": True}}

    def release(self) -> None:
        self.gate.set()


class _HalfSink:
    """写侧替身：只写三份里点名的那些（或者一份都不写），却照样回"成功"。

    为什么需要它：判据 c 问的是"写的不是盘上的事实时，召唤结果说不说"。真实秘书只在
    磁盘真坏时才走到那一档，那样的现场造不出来；而"秘书回了成功、盘上没有"恰好就是
    sylow4 那次的形态（区别只在那一次是秘书如实拒收、读数却到不了父手里）。
    """

    def __init__(self, root: pathlib.Path, *, write: tuple[str, ...] = ()) -> None:
        self.root = pathlib.Path(root)
        self.write = tuple(write)

    def roster_add(self, **kw: Any) -> dict[str, Any]:
        owner = str(kw.get("owner") or "")
        tid = str(kw.get("task_id") or "")
        name = str(kw.get("want_name") or "") or "E1"
        now = "2026-10-24T23:25:00+08:00"
        if "index" in self.write:
            SEC.append_jsonl(SEC.roster_index_path(self.root, owner),
                             {"kind": "bind", "owner": owner, "name": name,
                              "role": str(kw.get("role") or ""), "task_id": tid,
                              "at": now, "first": True})
        if "roster" in self.write:
            SEC.append_jsonl(SEC.roster_path(self.root, owner),
                             {"kind": "add", "owner": owner, "name": name,
                              "role": str(kw.get("role") or ""), "task_id": tid,
                              "first_task_id": tid, "brief": str(kw.get("brief") or ""),
                              "brief_source": "parent", "surface": "S01", "at": now})
        if "surfaces" in self.write:
            SEC.append_jsonl(SEC.surfaces_path(self.root, owner),
                             {"kind": "alloc", "owner": owner, "slot": "S01",
                              "name": name, "at": now})
        return {"name": name, "role": str(kw.get("role") or ""), "task_id": tid,
                "brief": str(kw.get("brief") or ""), "surface": "S01", "problem": ""}


def _env(tmp_path: pathlib.Path, *, sink: Any = None,
         gated: bool = True) -> dict[str, Any]:
    """一个工作区 + 一个顶趟 + 一个带名册写入口的主控。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    backend = _Backend(gated=gated)
    writer = sink if sink is not None else SEC.Secretary("M", root=ws, store=st)
    cond = Conductor(st, policy=None, backend=backend, roster_sink=writer)
    me = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    return {"ws": ws, "st": st, "cond": cond, "me": me, "backend": backend,
            "sink": writer}


def _files(ws: pathlib.Path, owner: str) -> dict[str, pathlib.Path]:
    return {"roster": SEC.roster_path(ws, owner),
            "index": SEC.roster_index_path(ws, owner),
            "surfaces": SEC.surfaces_path(ws, owner)}


def _rows(path: pathlib.Path, kind: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    got = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
           if line.strip()]
    return [r for r in got if str(r.get("kind") or "") == kind]


def _dispatch_without_name(env: dict[str, Any], *, key: str,
                           brief: str = BRIEF_TOO_LONG) -> Any:
    """按 sylow4 的形状派一个子：不给 `name`，父给的那句简介超长。"""
    return env["cond"].summon_preemptible(
        CHILD, "", {"task": TASK}, by=MY_ROLE, parent_task_id=env["me"],
        input_key=key, roster={"brief": brief, "task": TASK})


# ---------------------------------------------------------------- 判据 a（正控）


def _a_nameless_summon_lands_all_three(env: dict[str, Any]) -> dict[str, Any]:
    """判据 a 的正控内容（判据 d 复用同一份断言来做反真空）。返回盘上的那一份读数。"""
    handle = _dispatch_without_name(env, key="a")
    assert handle.task_id, handle.describe()
    assert not handle.done(), "孩子应当还卡在假后端里（这一条判的是派出去那一刻就在盘上）"
    paths = _files(env["ws"], env["me"])
    # 改前红：三份一份都不存在（内容闸拒收发生在写盘之前）。
    assert all(p.is_file() for p in paths.values()), \
        ("名册三份没有各建一份", {k: p.exists() for k, p in paths.items()})
    adds = _rows(paths["roster"], "add")
    binds = _rows(paths["index"], "bind")
    allocs = _rows(paths["surfaces"], "alloc")
    assert len(adds) == len(binds) == len(allocs) == 1, (adds, binds, allocs)
    assert str(adds[0].get("task_id")) == str(handle.task_id), adds
    assert str(adds[0].get("owner")) == env["me"], adds
    name = str(adds[0].get("name") or "")
    assert name, ("名册项必须有名字（名字由框架发）", adds)
    assert str(binds[0].get("name")) == name, binds
    assert str(allocs[0].get("name")) == name, allocs
    assert str(adds[0].get("brief_source")) == "secretary", (
        "父那句超长 ⇒ 由秘书按任务原文代写并留痕", adds)
    assert len(str(adds[0].get("brief") or "")) <= SEC.BRIEF_MAX, adds
    # 读数面：登记在给孩子跑之前就已经写成（句柄不必等孩子落定）。
    reading = handle.roster_reading()
    assert reading["roster_state"] == "written", reading
    assert reading["roster_name"] == name, reading
    assert not reading["roster_problem"], reading
    assert reading["roster_note"], ("父那句被换掉这件事不许静默", reading)
    return {"name": name, "paths": paths, "handle": handle}


def test_a_summon_without_a_name_lands_all_three_roster_files(
        tmp_path: pathlib.Path) -> None:
    """判据 a：不带 `name` 的子一派出 ⇒ 名册三份各一行（改前：三份都不存在）。"""
    env = _env(tmp_path)
    try:
        got = _a_nameless_summon_lands_all_three(env)
        res = got["handle"].result(timeout=0.1)
        assert res.roster_state == "written", res
        assert res.roster_name == got["name"], res
        assert res.status == "running", ("孩子还卡着，这条不是终态", res)
    finally:
        env["backend"].release()
    handle = got["handle"]
    assert handle.wait(20.0), "假后端放行之后应当落定"
    assert handle.result().status == "done", handle.result()


def test_a_control_named_and_wellbriefed_summon_is_unchanged(
        tmp_path: pathlib.Path) -> None:
    """对照（不是新判据）：父给名字、简介正常 ⇒ 三份各一行，简介逐字是父给的那句。

    盘上那三件事（三份文件、父给的简介、`brief_source=parent`）在改前就是对的 ——
    这一条不许被"写侧兜底"顺手改掉；它的红只来自新加的那几格读数。
    """
    env = _env(tmp_path, gated=False)
    res = env["cond"].summon(CHILD, "", {"task": TASK}, by=MY_ROLE,
                             parent_task_id=env["me"], input_key="ctrl",
                             roster={"brief": "逐行走审 stmt 000002", "name": "E1",
                                     "task": TASK})
    assert res.ok, res
    paths = _files(env["ws"], env["me"])
    assert all(p.is_file() for p in paths.values()), paths
    adds = _rows(paths["roster"], "add")
    assert [str(a.get("name")) for a in adds] == ["E1"], adds
    assert str(adds[0].get("brief")) == "逐行走审 stmt 000002", adds
    assert str(adds[0].get("brief_source")) == "parent", adds
    assert res.roster_state == "written" and not res.roster_problem, res
    assert not res.roster_note, res


# ---------------------------------------------------------------- 判据 b（顺延）


def test_b_two_nameless_children_get_F1_F2_by_sequence(tmp_path: pathlib.Path) -> None:
    """判据 b：派两个同类 ⇒ 名字顺延 E1 / E2（不是两个无名，也不重号）。

    改前红：两次都整份漏写，盘上一条名字都没有（不是"重号"，是"零行"）。
    """
    env = _env(tmp_path)
    try:
        first = _dispatch_without_name(env, key="b1")
        second = _dispatch_without_name(env, key="b2", brief=BRIEF_TOO_LONG_2)
        paths = _files(env["ws"], env["me"])
        adds = _rows(paths["roster"], "add")
        binds = _rows(paths["index"], "bind")
        allocs = _rows(paths["surfaces"], "alloc")
        assert len(adds) == len(binds) == len(allocs) == 2, (adds, binds, allocs)
        names = [str(a.get("name") or "") for a in adds]
        assert names == ["E1", "E2"], ("名字必须顺延，且不重号", names)
        assert all(names), names
        assert [str(a.get("task_id")) for a in adds] == \
               [str(first.task_id), str(second.task_id)], adds
        assert [str(b.get("name")) for b in binds] == names, binds
        assert [str(a.get("name")) for a in allocs] == names, allocs
        assert [first.roster_reading()["roster_name"],
                second.roster_reading()["roster_name"]] == names
    finally:
        env["backend"].release()
    assert first.wait(20.0) and second.wait(20.0)


# ---------------------------------------------------------------- 判据 c（负控）


def test_c_a_write_that_did_not_land_is_named_per_file(tmp_path: pathlib.Path) -> None:
    """判据 c：写侧说"成功"、盘上一行都没有 ⇒ `roster_problem` 逐份点名（不许静默）。

    改前红：改前只信 `roster_add` 的返回值（`problem` 空就当写成了），盘上一行都没有也
    一个字都不报 —— 这正是 sylow4 里"读数面只有 `unplaced`"的那半截。
    """
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=_Backend(gated=False),
                     roster_sink=_HalfSink(ws))
    me = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    res = cond.summon(CHILD, "", {"task": TASK}, by=MY_ROLE, parent_task_id=me,
                      input_key="c", roster={"brief": "一句正常简介", "task": TASK})
    # 登记失败不许带走这次派活：孩子照跑，账照样落。
    assert res.ok, res
    assert res.task_id, res
    problem = str(res.roster_problem or "")
    for label in ("名册正文", "对照表", "面池"):
        assert label in problem, ("逐份点名：缺了哪一份要说出来", label, problem)
    for name in (f"{me}.jsonl", f"{me}-index.jsonl", f"{me}-surfaces.jsonl"):
        assert name in problem, ("逐份点名：文件名要逐字给", name, problem)
    assert "没写成" in problem, problem
    assert res.roster_state == "missing", res
    assert all(not p.is_file() for p in _files(ws, me).values())


def test_c2_a_half_written_roster_names_only_the_missing_files(
        tmp_path: pathlib.Path) -> None:
    """判据 c 的第二半：只写成三份里的一份 ⇒ 只点名缺的那两份（写成了的不冤枉）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    sink = _HalfSink(ws, write=("index",))
    cond = Conductor(st, policy=None, backend=_Backend(gated=False), roster_sink=sink)
    me = cond.open_top_level_run(MY_ROLE, "顶层这一趟")
    res = cond.summon(CHILD, "", {"task": TASK}, by=MY_ROLE, parent_task_id=me,
                      input_key="c2", roster={"brief": "一句正常简介", "task": TASK})
    problem = str(res.roster_problem or "")
    assert "名册正文" in problem and "面池" in problem, problem
    assert "对照表" not in problem, ("写成了的那一份不许被点名", problem)
    assert "名册正文 t-000001.jsonl 没写成" in problem, problem
    assert res.roster_state == "missing", res
    assert (ws / "out" / "roster" / f"{me}-index.jsonl").is_file(), "夹具前提"


# ---------------------------------------------------------------- 判据 d（反真空）


def test_d_negctl_without_the_auto_name_a_is_red(tmp_path: pathlib.Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 d：把"自动发名"打桩成空（`next_name` 恒返回空串）⇒ 判据 a 必红。

    为什么这一条必须存在：判据 a 若能被"空名字也算登记"顺手带绿，那它就只测了
    "文件被创建"，没测"名字由框架发"。
    """
    env = _env(tmp_path)
    monkeypatch.setattr(SEC.Secretary, "next_name",
                        lambda self, owner, role: ("", ""))
    try:
        with pytest.raises(AssertionError):
            _a_nameless_summon_lands_all_three(env)
    finally:
        env["backend"].release()


# ---------------------------------------------------------------- 判据 e（批量同形）


def test_e_summon_many_registers_every_nameless_child(tmp_path: pathlib.Path) -> None:
    """判据 e：`summon_many` 同形 —— 批量里每个不带名字的子各自登记（各有一行、各有一个名字）。

    改前红：整批零行（同一处写侧缺口，只是走 `run_plan` 那条路）。
    """
    from agentflow.scheduler import TaskCall

    env = _env(tmp_path, gated=False)
    plan = [TaskCall(role=CHILD, action="", params={"task": TASK}, by=MY_ROLE,
                     parent_task_id=env["me"], input_key=f"e{i}",
                     roster={"brief": brief, "task": TASK})
            for i, brief in enumerate((BRIEF_TOO_LONG, BRIEF_TOO_LONG_2), 1)]
    results = env["cond"].run_plan(plan)
    assert len(results) == 2, results
    assert all(r.status == "done" for r in results), [r.status for r in results]
    paths = _files(env["ws"], env["me"])
    adds = _rows(paths["roster"], "add")
    binds = _rows(paths["index"], "bind")
    allocs = _rows(paths["surfaces"], "alloc")
    assert len(adds) == len(binds) == len(allocs) == 2, (adds, binds, allocs)
    names = [str(a.get("name") or "") for a in adds]
    assert len(set(names)) == 2 and all(names), ("不许两个无名，也不许重号", names)
    assert sorted(str(a.get("task_id")) for a in adds) == \
           sorted(str(r.task_id) for r in results), adds
    assert all(r.roster_state == "written" for r in results), \
        [r.roster_state for r in results]
    assert not any(r.roster_problem for r in results), [r.roster_problem for r in results]
    assert sorted(str(r.roster_name) for r in results) == sorted(names)
