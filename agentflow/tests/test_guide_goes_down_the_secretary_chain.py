# -*- coding: utf-8 -*-
"""M 向深层子代理发指导：只走秘书链，逐级转发，最后一级的秘书才读内容。

业主 2026-10-26 原话（唯一权威）：

    「关于M侧向某很下层的子代理发信息进行工作指导 … 建议直接全走秘书，即M给绝对
      编码链例如000001->000005->000012->000024之类，M的秘书发给000005的秘书消息有
      链000005->000012->000024，然后000005的秘书继续发给下级秘书，直到000024的
      秘书收到后才具体读消息内容 … 我取消我之前说的要让各级父代理知道该消息的
      说法。M的轮查工具务必能反馈绝对编码链。」

这一份把业主点名的那条链变成机器读数（零模型：只有台账、名册、板项与转发台账）：

| 判据 | 守的那件事 | 改前形态 |
|---|---|---|
| a | 整条链发一条 ⇒ 链上四位秘书各经手一次、只有链尾那一个代理读到正文，链上其余三位代理本人 0 条 | 没有链式寻址、也没有逐级转发（`to` 只认单个 4–8 字台账号；写整条链会被 schema 拒） |
| b | 某一跳不是上一跳的直接下级 ⇒ `broken_chain`，逐跳点名「X 不是 Y 的直接下级（它的直接下级是 …）」 | 没有这条校验（写链先被判非法，逐跳点名这句不存在） |
| c | 链尾已销号 ⇒ `retired_target` | 不查销号（只查台账里有没有那一行） |
| d | 回执沿链回传：`delivered_to` = 链尾、每一跳有时间、同一个 `relay_id` 贯穿全链 | 没有 `delivered_to` / `hops` / `relay_id` 这三格 |
| e | 轮查工具（`conductor.watch` / `conductor.ledger` 的 tree）每一行都带 `chain` 与 `chain_text`，与真实父子关系一致（含第 4 层） | 两格都不存在（只有 `parent_task_id` / `level`，深层节点要调用方自己拼） |
| f | 反真空：把"只交给秘书"打桩成"每一跳都交给代理本人" ⇒ a 必红 | 这一条量的就是"a 真的在看中间各跳有没有拿到内容" |

零模型：链上的秘书是确定性对象（不调模型），转发台账是 append-only 的 JSONL。
边界：只用 `tmp_path` 里的工作区；不碰真机 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import conductor as COND
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "chain-forward"

#: 业主点名的那个场景逐字（链尾那一句"请你停止正在进行的穷举实验"）。
BODY = "请你停止正在进行的穷举实验，另一个代理已研究出关于该命题的纯理论证明"


# ---------------------------------------------------------------- 夹具


def _agent_row(cond: Conductor, *, role: str, parent: str, key: str) -> str:
    """建一条子代理实例行（与 `summon` 建的那种同形；实例行的唯一建行点）。"""
    prow = cond._task(parent) or {}
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": key, "status": "running", "outcome": None,
        "refusal_reason": None, "instance": "", "detail": f"{role} 的活（{key}）",
        "error": None, "started_at": "2026-10-27T00:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:chain")


def _env(root: pathlib.Path, *, levels: int = 3) -> dict[str, Any]:
    """一条从顶趟往下的链 + 每一级都登记进名册（`levels` = 顶趟下面几层）。

    默认三层下级 ⇒ 链是四跳（顶趟 + 3）—— 业主说的"第 4 层"就是最后那一跳。
    """
    ws = root / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run("M", "链式指导的顶趟")
    chain = [top]
    roles = ["D", "E", "F", "G", "H"]
    for i in range(levels):
        chain.append(_agent_row(cond, role=roles[min(i, len(roles) - 1)],
                                parent=chain[-1], key=f"chain@{i}"))
    writer = SEC.for_role("M", root=ws, store=st)
    names: list[str] = []
    for parent, kid, role in ((chain[i], chain[i + 1], roles[min(i, len(roles) - 1)])
                              for i in range(len(chain) - 1)):
        got = writer.roster_add(owner=parent, role=role, task_id=kid, brief="链上一跳")
        assert got["problem"] == "", got
        names.append(str(got["name"]))
    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "top": top,
            "chain": chain, "names": names, "writer": writer}


def _guide(env: dict[str, Any], to: str, *, text: str = BODY) -> Any:
    """以顶趟那一行（M）的身份调 `conductor.guide`（生产路径由 `_do_tool` 挂同一个身份）。"""
    with calling_as(env["top"], "M", session_root=str(env["ws"]), sid=SID):
        return env["reg"].call("conductor.guide", role="M", to=to, text=text)


def _relay_rows(ws: pathlib.Path) -> list[dict[str, Any]]:
    """转发台账的行（`out/secretary/relay.jsonl`）。读不到 ⇒ 空列表（断言会红）。"""
    path = ws / "out" / "secretary" / "relay.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _items(cond: Conductor, tid: str) -> list[dict[str, Any]]:
    """某个代理名下未消的板项（"代理本人收到了什么"的唯一投递面）。"""
    return [dict(r) for r in cond.open_items_of(tid)]


def _chain_text(chain: list[str]) -> str:
    return "->".join(chain)


# ---------------------------------------------------------------- a) 逐级转发

def _forwarded_chain(root: pathlib.Path) -> dict[str, Any]:
    """判据 a 的全部断言（正控与反真空共用这一份）。"""
    env = _env(root, levels=3)
    chain = env["chain"]
    assert len(chain) == 4, chain
    res = _guide(env, _chain_text(chain))
    data = res.data
    assert res.ok, res.to_dict()
    assert data["status"] == "delivered", data
    assert data["chain"] == chain, data["chain"]
    assert data["chain_text"] == _chain_text(chain), data["chain_text"]
    assert data["delivered_to"] == [chain[-1]], data["delivered_to"]
    assert data["to_role"] == "F", data["to_role"]

    # ---- 四个秘书各收到一次转发（每个秘书只经手一跳）
    rows = _relay_rows(env["ws"])
    assert len(rows) == 4, rows
    assert [r["secretary_task_id"] for r in rows] == chain, rows
    assert [r["mode"] for r in rows] == ["forward", "forward", "forward", "deliver"], rows
    assert [r["content_read"] for r in rows] == [False, False, False, True], rows
    assert len({r["relay_id"] for r in rows}) == 1, rows
    assert rows[-1]["item_id"] == data["item_id"], (rows[-1], data["item_id"])

    # ---- 中间三位代理本人收到 0 条；链尾那一个收到 1 条正文
    for tid in chain[:-1]:
        assert _items(env["cond"], tid) == [], ("中间各跳不许给代理本人开板项", tid,
                                                _items(env["cond"], tid))
    tail_items = _items(env["cond"], chain[-1])
    assert len(tail_items) == 1, tail_items
    assert str(tail_items[0]["task_id"]) == data["item_id"], tail_items
    assert BODY in str(tail_items[0].get("detail") or ""), tail_items
    return {"env": env, "data": data, "rows": rows}


def test_a_the_guide_walks_the_secretary_chain_and_only_the_tail_reads_it(
        tmp_path: pathlib.Path) -> None:
    """判据 a：整条链发一条 ⇒ 四个秘书各转发一次、只有链尾代理读到正文。

    改前红：这件工具只认单个 4–8 字台账号（写整条链先被参数 schema 拒），也没有
    逐级转发 —— 它给目标与它的每一级父各开一条板项，于是"中间三个代理本人收到 0 次"
    这一条在改前恰好相反。
    """
    got = _forwarded_chain(tmp_path)
    data = got["data"]
    assert len(data["hops"]) == 4, data["hops"]
    assert [h["content_read"] for h in data["hops"]] == [False, False, False, True], data["hops"]
    assert [h["remaining_chain"] for h in data["hops"]] == [
        [got["env"]["chain"][2], got["env"]["chain"][3]],
        [got["env"]["chain"][3]], [], []], data["hops"]


def test_a2_a_five_hop_chain_leaves_three_intermediate_agents_at_zero(
        tmp_path: pathlib.Path) -> None:
    """判据 a 的第二档：五跳的链 ⇒ 五个秘书各一次、中间三个代理各 0 条、链尾 1 条。

    为什么另给一条：业主原话里的链是四跳（顶趟 + 3），那一档的"中间代理"是两位；
    这一条把"链更长时中间那些代理一个都收不到"也钉住（链长不该改变规则）。
    """
    env = _env(tmp_path, levels=4)
    chain = env["chain"]
    assert len(chain) == 5, chain
    res = _guide(env, _chain_text(chain))
    assert res.data["status"] == "delivered", res.data
    rows = _relay_rows(env["ws"])
    assert [r["secretary_task_id"] for r in rows] == chain, rows
    assert [r["content_read"] for r in rows] == [False, False, False, False, True], rows
    for tid in chain[:-1]:
        assert _items(env["cond"], tid) == [], (tid, _items(env["cond"], tid))
    assert len(_items(env["cond"], chain[-1])) == 1, _items(env["cond"], chain[-1])


def test_a3_only_the_chain_tail_needs_writing_and_the_chain_is_derived(
        tmp_path: pathlib.Path) -> None:
    """判据 a 的第三档（兼容档）：模型只写链尾 ⇒ 链条由台账现算，转发规则一字不变。

    为什么必须有这一档：业主的判据是"给链"，而现实里模型更可能只写"发给谁"；
    只写链尾也必须落到同一条秘书链上（否则"只在写全链时才安全"）。改前红：改前
    只写链尾确实能发，但它直接给那一个开板项、不经过任何秘书。
    """
    env = _env(tmp_path, levels=3)
    res = _guide(env, env["chain"][-1])
    assert res.data["status"] == "delivered", res.data
    assert res.data["chain"] == env["chain"], res.data["chain"]
    assert res.data["chain_text"] == _chain_text(env["chain"]), res.data["chain_text"]
    assert len(_relay_rows(env["ws"])) == 4, _relay_rows(env["ws"])


def test_a4_a_roster_name_chain_is_resolved_hop_by_hop(tmp_path: pathlib.Path) -> None:
    """判据 a 的第四档：名册名混写（`M->D1->E1->F1`）⇒ 内部解析成绝对编号链。

    业主 ①：「也接受名册名混写：`M->D1->F2->V1`，但内部一律先解析成绝对编号链，
    读数里给 `chain=[…]`」。每一跳的名册名都在"上一跳"的名册里译（相对名的作用域
    就是"谁的名册"）——所以同一串名字在不同父名下能指不同实例，读数必须给绝对编号。

    改前红：改前 `to` 只认单个台账号/单个名册名，一串 `->` 连起来的名册名直接判非法。
    """
    env = _env(tmp_path, levels=3)
    chain = env["chain"]
    names = ["M"] + list(env["names"])
    written = "->".join(names)
    res = _guide(env, written)
    assert res.data["status"] == "delivered", res.data
    assert res.data["chain"] == chain, (written, res.data["chain"], chain)
    assert res.data["chain_text"] == _chain_text(chain), res.data["chain_text"]
    assert res.data["names"] == ["", *env["names"]], res.data["names"]
    assert res.data["delivered_to"] == [chain[-1]], res.data["delivered_to"]


# ---------------------------------------------------------------- b) 断链

def test_b_a_broken_chain_is_refused_and_names_every_hop(tmp_path: pathlib.Path) -> None:
    """判据 b（负控）：某一跳不是上一跳的直接下级 ⇒ `broken_chain`，逐跳点名。

    夹具：顶趟另有一个直接子 `cousin`（与链上第二位是兄弟）。写
    `top->cousin->tail` ⇒ `tail` 不是 `cousin` 的直接下级。

    改前红：没有这条校验（整条链在 schema 那一层就被拒），也就不存在
    「X 不是 Y 的直接下级（它的直接下级是 …）」这句逐跳点名。
    """
    env = _env(tmp_path, levels=3)
    chain = env["chain"]
    cousin = _agent_row(env["cond"], role="G", parent=chain[0], key="chain@cousin")
    got = env["writer"].roster_add(owner=chain[0], role="G", task_id=cousin, brief="兄弟一支")
    assert got["problem"] == "", got
    res = _guide(env, _chain_text([chain[0], cousin, chain[-1]]))
    data = res.data
    assert res.ok, res.to_dict()
    assert data["status"] == "refused", data
    assert data["refused"] == "broken_chain", data
    text = str(data["error"])
    assert f"{chain[-1]} 不是 {cousin} 的直接下级" in text, text
    assert "它的直接下级是" in text, text
    # 逐跳点名：cousin 的直接下级就是它自己的下级（这里没有 ⇒ 明确写"没有"）
    assert "（没有直接下级）" in text, text
    assert data["skipped"] == [chain[-1]], data["skipped"]
    # 受控拒绝不许留下半条：一条转发都没有、一个板项都没有
    assert _relay_rows(env["ws"]) == [], _relay_rows(env["ws"])
    for tid in chain + [cousin]:
        assert _items(env["cond"], tid) == [], (tid, _items(env["cond"], tid))


def test_b3_without_the_parent_check_the_broken_chain_gets_delivered(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 b 的改前红（可跑）：把"逐跳校验父子关系"打桩成照单全收 ⇒ b 必红。

    替身就是改前那一层：写法里出现几跳就照抄几跳、不查 `parent_task_id`。判据 b
    的"受控拒绝 + 逐跳点名"因此一条也拿不到（它会一路投到链尾）。
    """
    def blind(self: Any, written: Any, *, sender_task_id: str = "",
              sender_role: str = "") -> dict[str, Any]:
        tokens, problem = COND.parse_chain_address(written)
        chain = [str(sender_task_id)] + [str(t) for t in tokens[1:]]
        return {"checked": True, "status": "resolved", "written": str(written),
                "tokens": tokens, "chain": chain, "chain_text": self.chain_text(chain),
                "names": [""] * len(chain), "roles": [""] * len(chain), "hops": [],
                "skipped": [], "refused": problem, "error": "", "callable": "",
                "note": ""}

    monkeypatch.setattr(COND.Conductor, "resolve_chain", blind)
    with pytest.raises(AssertionError):
        test_b_a_broken_chain_is_refused_and_names_every_hop(tmp_path)


def test_b2_a_target_outside_the_senders_branch_is_refused_not_guessed(
        tmp_path: pathlib.Path) -> None:
    """判据 b 的第二档：目标不在发送方这一支下面 ⇒ `broken_chain`，不猜一条路。

    夹具：同一个工作区里另开一趟顶趟（另一棵树），用第一棵树的 M 去发第二棵树
    里的节点 —— 台账里那一行是存在的，只是"从发送方往上追不到它"。

    改前红：改前这件工具只按台账号开板项，"这一支"这个概念根本没有读数。
    """
    env = _env(tmp_path, levels=1)
    other_top = env["cond"].open_top_level_run("M", "另一棵树")
    other_kid = _agent_row(env["cond"], role="G", parent=other_top, key="chain@other")
    res = _guide(env, other_kid)
    data = res.data
    assert data["status"] == "refused", data
    assert data["refused"] == "broken_chain", data
    assert "不在发送方" in str(data["error"]), data["error"]
    for tid in env["chain"] + [other_top, other_kid]:
        assert _items(env["cond"], tid) == [], (tid, env["cond"].open_items_of(tid))
    assert _relay_rows(env["ws"]) == [], _relay_rows(env["ws"])


# ---------------------------------------------------------------- c) 链尾已销号

def test_c_a_retired_tail_is_refused(tmp_path: pathlib.Path) -> None:
    """判据 c（负控）：链尾已销号 ⇒ `retired_target`，一个板项都不开。

    改前红：改前的寻址只看"台账里有没有那一行"；销号发生在名册那一侧，台账行
    永远都在 ⇒ 改前会照样给它开一条板项（发给一个已经退场的代理）。

    销号走的是真实现（`Secretary.retire`），不手写名册行：链尾那一行先收工
    （`status=done`），再让它的父销号。
    """
    env = _env(tmp_path, levels=3)
    chain = env["chain"]
    tail = chain[-1]
    env["cond"].finish(tail, status="done", outcome="ok", detail="链尾收工")
    retired = env["writer"].retire(owner=chain[-2], name=env["names"][-1],
                                   by_task_id=chain[-2], reason="链尾这一支已经不需要了")
    assert retired.get("action") == "retired", retired
    res = _guide(env, _chain_text(chain))
    data = res.data
    assert data["status"] == "refused", data
    assert data["refused"] == "retired_target", data
    assert "已销号" in str(data["error"]), data["error"]
    assert _relay_rows(env["ws"]) == [], _relay_rows(env["ws"])
    for tid in chain:
        assert _items(env["cond"], tid) == [], (tid, _items(env["cond"], tid))


def test_c2_without_the_roster_read_the_retired_tail_gets_delivered(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 c 的改前红（可跑）：把"读名册那一侧"打桩成空 ⇒ 销号看不见 ⇒ c 必红。

    空 `roster_rows` 就是改前那一层（"台账里有这一行就发"，从不问名册）。
    父链校验仍然过（它读的是台账），于是这一条会一路投给一个已经销号的代理
    —— 判据 c 的 `refused == retired_target` 当场拿不到。
    """
    monkeypatch.setattr(SEC.Secretary, "roster_rows", lambda self, owner: ([], []))
    with pytest.raises(AssertionError):
        test_c_a_retired_tail_is_refused(tmp_path)


# ---------------------------------------------------------------- d) 回执沿链回传

def test_d_the_receipt_comes_back_along_the_chain_with_per_hop_times(
        tmp_path: pathlib.Path) -> None:
    """判据 d（正控）：发送方拿到 `delivered_to`、每跳时间与贯穿全链的 `relay_id`。

    改前红：`delivered_to` / `hops` / `relay_id` 三格都不存在（改前只有 `item_id`
    与 `ancestors`）。

    时间用 `time.perf_counter` 计（`time.monotonic` 在本机实测只有毫秒粒度，一跳
    几十微秒会被读成 0）—— 所以这一条同时钉住"每跳时间不是一格恒 0 的装饰"。
    """
    got = _forwarded_chain(tmp_path)
    data = got["data"]
    hops = data["hops"]
    assert len(hops) == 4, hops
    assert [h["hop"] for h in hops] == [1, 2, 3, 4], hops
    assert [h["of"] for h in hops] == [4, 4, 4, 4], hops
    assert all(str(h.get("at") or "") for h in hops), hops
    elapsed = [int(h["elapsed_us"]) for h in hops]
    assert elapsed == sorted(elapsed), ("累计时间必须单调不减", elapsed)
    assert max(elapsed) > 0, ("每跳时间全是 0 ⇒ 它不是读数", elapsed)
    assert all(int(h["delta_us"]) >= 0 for h in hops), hops
    # 回执与盘上那一份是同一件事：同一个 relay_id、同一条链尾
    assert data["relay_id"], data
    rows = _relay_rows(got["env"]["ws"])
    assert {r["relay_id"] for r in rows} == {data["relay_id"]}, rows
    assert data["delivered_to"] == [got["env"]["chain"][-1]], data["delivered_to"]
    assert [r["to"] for r in rows] == [got["env"]["chain"][1], got["env"]["chain"][2],
                                       got["env"]["chain"][3],
                                       got["env"]["chain"][3]], rows


# ---------------------------------------------------------------- e) 轮查工具给链

def _true_chain(rows: list[dict[str, Any]], tid: str) -> list[str]:
    """从台账独立算一遍真值（不调被测函数：判据要拿另一条实现对照）。"""
    by_id = {str(r.get("task_id") or ""): r for r in rows
             if not str(r.get("kind") or "")}
    out: list[str] = []
    cur = tid
    while cur and cur in by_id and cur not in out:
        out.append(cur)
        parent = str(by_id[cur].get("parent_task_id") or "")
        cur = parent if parent != cur else ""
    return list(reversed(out))


def test_e_the_patrol_tools_report_the_absolute_chain_for_every_node(
        tmp_path: pathlib.Path) -> None:
    """判据 e：轮查读数里每一行都有 `chain` / `chain_text`，且与真实父子关系一致。

    两条都钉：`conductor.watch`（M 的轮查工具）与 `conductor.ledger(view="tree")`
    （同一份台账的树读数）。第 4 层那个节点必须拿到四个编号的链 —— 深层节点只给
    "父是谁"的话，M 还得自己一层层拼，而拼错一个号就会发给另一支。

    改前红：两格都不存在（`rows[]` 里只有 `parent_task_id` 与 `level`）。
    """
    env = _env(tmp_path, levels=3)
    truth = {tid: _true_chain(env["st"].rows("tasks"), tid) for tid in env["chain"]}
    with calling_as(env["top"], "M", session_root=str(env["ws"]), sid=SID):
        watch = env["reg"].call("conductor.watch", role="M", task_id=env["top"])
        ledger = env["reg"].call("conductor.ledger", role="M", view="tree")
    assert watch.ok, watch.to_dict()
    assert ledger.ok, ledger.to_dict()
    seen = 0
    for rows in (watch.data["rows"], ledger.data["rows"]):
        for row in rows:
            tid = str(row["task_id"])
            if tid not in truth:
                continue
            seen += 1
            assert row["chain"] == truth[tid], (tid, row["chain"], truth[tid])
            assert row["chain_text"] == _chain_text(row["chain"]), (tid, row)
            assert row["chain"][0] == env["top"], (tid, row["chain"])
            assert row["chain"][-1] == tid, (tid, row["chain"])
    assert seen >= 8, ("两条读数都该覆盖整棵树", seen)
    deepest = env["chain"][-1]
    deep_rows = [r for r in watch.data["rows"] if str(r["task_id"]) == deepest]
    assert deep_rows and deep_rows[0]["chain"] == truth[deepest], deep_rows
    assert len(deep_rows[0]["chain"]) == 4, deep_rows
    # 从中间某一层起手看那一支：链仍然必须从顶趟写起（"从 M 到该节点"），
    # 不许因为被看的根换了就把上面那几跳截掉 —— 截掉的链拿去发消息会发错支。
    mid = env["chain"][1]
    with calling_as(env["top"], "M", session_root=str(env["ws"]), sid=SID):
        sub = env["reg"].call("conductor.watch", role="M", task_id=mid)
    for row in sub.data["rows"]:
        tid = str(row["task_id"])
        assert row["chain"] == truth[tid], (tid, row["chain"], truth[tid])
        assert row["chain"][0] == env["top"], (tid, row["chain"])


def test_e2_the_chain_cells_are_not_vacuous(tmp_path: pathlib.Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 e 的反真空：把追父链打成恒空 ⇒ 每行的 `chain` 都空 ⇒ e 必红。

    恒空就是"这两格只是占位"那一版实现：键在、意思没有。判据 e 必须因此红。
    """
    real = COND.absolute_chain

    monkeypatch.setattr(COND, "absolute_chain", lambda rows, tid: [])
    env = _env(tmp_path, levels=3)
    with calling_as(env["top"], "M", session_root=str(env["ws"]), sid=SID):
        watch = env["reg"].call("conductor.watch", role="M", task_id=env["top"])
    bad = [r for r in watch.data["rows"] if r["chain"] != _true_chain(
        env["st"].rows("tasks"), str(r["task_id"]))]
    assert bad, "恒空的链居然与真值一致 ⇒ 这条反真空没打上"
    monkeypatch.setattr(COND, "absolute_chain", real)
    with calling_as(env["top"], "M", session_root=str(env["ws"]), sid=SID):
        again = env["reg"].call("conductor.watch", role="M", task_id=env["top"])
    assert all(r["chain"] for r in again.data["rows"]), again.data["rows"]


# ---------------------------------------------------------------- f) 反真空

def test_f_leaking_the_body_to_every_hop_makes_a_red(tmp_path: pathlib.Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把"只有链尾读内容"打桩成"每一跳都交给代理本人" ⇒ 判据 a 必红。

    打桩打在 `Secretary.relay_in` 上：还有下一跳时先就地交付一次（正文落到这一跳
    那位代理的板项上），再走真实转发。判据 a 的那三条"中间代理 0 条"必须因此红。
    """
    real = SEC.Secretary.relay_in

    def leaky(self: Any, **kw: Any) -> dict[str, Any]:
        if kw.get("remaining_chain"):
            self.deliver_local(body=str(kw.get("body") or ""), chain_text="stub",
                               origin="stub")
        return real(self, **kw)

    monkeypatch.setattr(SEC.Secretary, "relay_in", leaky)
    with pytest.raises(AssertionError):
        _forwarded_chain(tmp_path)
