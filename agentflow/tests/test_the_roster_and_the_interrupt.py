"""判据：名册补三样 + 逐子代理叫停（S-H / 业主 2026-10-10 裁定 14）。

## 这一组守六件事

1. 名册补的三格（`status` / `in_flight` / `last_reading`）：`status` 是机器可判的
   （`running` 在跑 / `idle` 在飞但闲着 / `ready` 不在跑、仍可续 / `retired` 已销号），
   前三档照 DSH `list-agents.js:24-29` 逐字，第四档是如实加的一档（理由见
   `secretary._status_enum`：把销号读成 `ready` 会让模型去叫一个再也叫不醒的名字）；
   `in_flight` 是"它名下此刻还在跑几件"（反真空：夹具里必须有一行 > 0，否则那一格没被测到）；
   `last_reading` 是它最近一条报告的摘要 —— DSH 的 `list_agents` 没有这一格，
   它的存在正是业主要求"保住我们的最近读数"。
2. `scope="descendants"` 全树：每一行带 `parent` 与 `depth`（改前只有下一层）；
   缺省仍是下一层（老行为逐字不变），不认的取值当面拒绝（不静默折回缺省）。
3. 逐行 diagnostic：改前"名册里有一行读不出来"⇒ 整份拒；现在好行照常渲染、
   坏行逐条落进 `diagnostics`（带类别）。只有一条好行都没有时才整体拒（三态）。
4. `interrupt` 只停一个目标：信号按台账号一份，`interrupt_applies` 只认精确的那个
   （别人的信号读到的是"查过了、不适用"，不是"没查成"）。
5. 授权（DSH `:853-866`）：不许停自己；判不了（三态）⇒ 拒绝；非后代 ⇒ 拒绝；
   不在册 / 已结束 ⇒ 静默 no-op（`accepted=True` + `no_op=True`）。
6. 不递归 + 队列保留：叫停不碰收件箱（判据：消息条数在两个时刻相同），
   也不动目标自己的子代理（判据：它的子代理那一行还在飞）。
"""

from __future__ import annotations

import pathlib
from typing import Any

from agentflow import agent_loop as AL
from agentflow import manuscripts as MS
from agentflow import stopctl as SC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store


def _env(tmp_path: pathlib.Path) -> tuple[Store, Conductor, Secretary]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return st, cond, Secretary("M", root=ws, store=st)


def _child(cond: Conductor, parent: str, *, role: str = "D", status: str = "done",
           key: str = "s1h@c", depth: int = 2) -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": depth, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-10T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-10T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def test_the_roster_rows_carry_the_three_new_cells(tmp_path: pathlib.Path) -> None:
    """正控（三格）：`status` / `in_flight` / `last_reading` 都在，且读数是对的。

    反真空：夹具里特意造了一行"还在跑"的子代理 —— 没有它，`in_flight > 0` 那一格
    永远测不到（一个全为 0 的格子与"这一格没实现"长得一样）。
    """
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    running = _child(cond, owner, status="running", key="s1h@run")
    idle = _child(cond, owner, status="done", key="s1h@idle")
    assert sec.roster_add(owner=owner, role="D", task_id=running, brief="还在跑那件")["problem"] == ""
    assert sec.roster_add(owner=owner, role="D", task_id=idle, brief="跑完那件")["problem"] == ""
    MS.write(tmp_path / "ws", sender="D", recipient="M", summary="我读到第三行",
             body="正文", task_id=running)

    view = sec.roster_view(owner=owner)
    assert view["checked"] is True, view
    rows = {r["name"]: r for r in view["rows"]}
    assert set(rows) == {"D1", "D2"}, rows
    d1, d2 = rows["D1"], rows["D2"]
    # ① status：在跑的 running / 跑完的 idle
    assert d1["status"] == "running", d1
    assert d2["status"] == "idle", d2
    # ② in_flight：D1 名下有一件在飞（反真空那一格）
    assert d1["in_flight"] == 1, d1
    assert d2["in_flight"] == 0, d2
    # ③ last_reading：手稿摘要真的进到那一行（DSH 没有这一格 —— 别丢）
    assert d1["last_reading"] == "我读到第三行", d1
    assert d2["last_reading"] == "", d2
    # 老那一格不许被挤掉（"净减一样、别丢"）
    assert {"state", "retirable", "items_open", "task_id", "role", "brief"} <= set(d1), d1


def test_ready_and_retired_are_two_different_readings(tmp_path: pathlib.Path) -> None:
    """正控（第四档的理由）：不在台账里的读 `ready`，销号的读 `retired`。

    这一条钉的是"如实加一档"那件事：DSH 的三值里没有 `retired`，而把销号读成 `ready`
    （= "仍可续"）会让模型去 `send_message` 一个再也叫不醒的名字。
    """
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    # `ready` 那一档的夹具：名册里有一个台账里没有的台账号（未登记）。
    # 不用 `_child` 造它 —— 造了行就落到 `idle` 那一档，这一格就测不到了。
    assert sec.roster_add(owner=owner, role="D", task_id="t-quest",
                          brief="台账里读不到那样")["problem"] == ""
    # `retired` 那一档：真有一行、且已结束、名下无子 ⇒ 可退役（三分支的第三支）。
    done = _child(cond, owner, status="done", key="s1h@fin")
    assert sec.roster_add(owner=owner, role="D", task_id=done, brief="跑完那件")["problem"] == ""

    view = sec.roster_view(owner=owner)
    rows = {r["name"]: r for r in view["rows"]}
    assert rows["D1"]["status"] == "ready", rows["D1"]
    assert rows["D1"]["state"] == "未登记", rows["D1"]
    assert rows["D2"]["status"] == "idle", rows["D2"]
    retired = sec.retire(owner=owner, name="D2", by_task_id=owner)
    assert retired.get("action") == "retired", retired
    view2 = {r["name"]: r for r in sec.roster_view(owner=owner)["rows"]}
    assert view2["D2"]["status"] == "retired", view2["D2"]
    # 反真空：销号那一档不许与 `ready` 折成同一个读数（它们旁边那格 state 也不同）
    assert view2["D1"]["status"] != view2["D2"]["status"], view2


def test_descendants_scope_gives_the_whole_tree(tmp_path: pathlib.Path) -> None:
    """正控（全树）：`scope="descendants"` 带 `parent`/`depth`；缺省仍是下一层。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    mid = _child(cond, owner, status="running", key="s1h@mid")
    leaf = _child(cond, mid, status="done", key="s1h@leaf")
    assert sec.roster_add(owner=owner, role="D", task_id=mid, brief="中间那层")["problem"] == ""
    assert sec.roster_add(owner=mid, role="E", task_id=leaf, brief="叶子那件")["problem"] == ""

    shallow = sec.roster_view(owner=owner)
    assert [r["name"] for r in shallow["rows"]] == ["D1"], shallow["rows"]
    assert "parent" not in shallow["rows"][0], "缺省那一档不许凭空多出 parent/depth"

    deep = sec.roster_view(owner=owner, scope="descendants")
    got = [(r["name"], r["parent"], r["depth"]) for r in deep["rows"]]
    assert got == [("D1", "", 1), ("E1", "D1", 2)], got
    assert deep["scope"] == "descendants", deep
    # 深的那一层也有三格读数（全树不是"只把名字列出来"）
    leaf_row = deep["rows"][1]
    assert leaf_row["status"] == "idle" and leaf_row["in_flight"] == 0, leaf_row

    # ---- 协议那一跳（`draft/105` A9 的那条缝）
    #
    # 上面那些断言走的是秘书那一侧（直接调 `roster_view(scope=…)`），所以它们
    # 在"解码器把 `scope` 丢掉"的那段时间里照样全绿 —— 而模型在协议上根本递不进这一格。
    # 这一段把那一跳也测到：解码器必须原样带过 `scope`，且缺省形状一个键都不多。
    key, payload, problem = AL._decode_shape({"roster": {"of": "self", "scope": "descendants"}})
    assert (key, problem) == ("roster", ""), (key, problem)
    assert payload == {"of": "self", "scope": "descendants"}, payload
    _, plain, _ = AL._decode_shape({"roster": {"of": "D1"}})
    assert plain == {"of": "D1"}, plain
    _, blank, _ = AL._decode_shape({"roster": {"of": "self", "scope": ""}})
    assert blank == {"of": "self"}, blank


def test_bad_lines_are_diagnosed_per_line(tmp_path: pathlib.Path) -> None:
    """正控（逐行 diagnostic）：坏行不再让整份名册读不出来。

    三态的另一半：一条好行都没有而坏行有 ⇒ 仍然整体拒（那时"名册是空的"与
    "名册读不成"会被折成同一句话，而那正是要挡的形态）。
    """
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    kid = _child(cond, owner, status="done", key="s1h@ok")
    assert sec.roster_add(owner=owner, role="D", task_id=kid, brief="好行")["problem"] == ""
    rpath = pathlib.Path(sec.root) / "runs" / f"roster-{owner}.jsonl"
    if not rpath.is_file():        # 名册文件名口径变了也要让这条判据说话，不是静默跳过
        import agentflow.secretary as SE
        rpath = SE.roster_path(sec.root, owner)
    with rpath.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{不是 JSON\n")
    view = sec.roster_view(owner=owner)
    assert view["checked"] is True, view
    assert [r["name"] for r in view["rows"]] == ["D1"], view["rows"]
    assert len(view["diagnostics"]) == 1, view["diagnostics"]
    assert view["diagnostics"][0]["kind"] == "corrupt", view["diagnostics"]

    # 负控：把好行也弄坏 ⇒ 整体拒（不许说"名册是空的"）
    body = rpath.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in body if ln.startswith("{不是")]
    rpath.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    dead = sec.roster_view(owner=owner)
    assert dead["checked"] is False and "读不出来" in dead["reason"], dead
    assert dead["diagnostics"], dead


def test_the_interrupt_signal_only_applies_to_its_target(tmp_path: pathlib.Path) -> None:
    """正控（作用面）：信号只被精确的那一个目标读到，读到即消费（一次性）。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    kid = _child(cond, owner, status="running", key="s1h@stop")
    ok = cond.interrupt_child(parent_task_id=owner, child_task_id=kid, by="M")
    assert ok["accepted"] is True and ok["code"] == "accepted", ok
    state = SC.read_interrupt(tmp_path / "ws", kid)
    assert state is not None and state["by_task_id"] == owner, state
    assert SC.interrupt_applies(state, kid)["applies"] is True
    other = SC.interrupt_applies(state, "t-9999")
    assert other == {"checked": True, "applies": False,
                     "reason": f"这份信号是给 {kid} 的，不是我（t-9999）"}, other
    # 读到即消费（一次性信号）：撤走之后读到 None，而审计留在流水里。
    SC.consume_interrupt(tmp_path / "ws", kid, sid="t")
    assert SC.read_interrupt(tmp_path / "ws", kid) is None
    hist = SC.interrupt_history(tmp_path / "ws")
    assert hist and hist[-1]["target_task_id"] == kid, hist


def test_the_interrupt_authorization_is_three_valued(tmp_path: pathlib.Path) -> None:
    """负控（授权）：不许停自己 / 非后代 / 判不了；不在册或已结束 ⇒ 静默 no-op。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    mine = _child(cond, owner, status="running", key="s1h@mine")
    sibling = cond.open_top_level_run("M", "另一趟（不是我这一支）")
    other = _child(cond, sibling, status="running", key="s1h@other")

    selfstop = cond.interrupt_child(parent_task_id=owner, child_task_id=owner, by="M")
    assert selfstop["code"] == "unauthorized" and not selfstop["accepted"], selfstop
    stranger = cond.interrupt_child(parent_task_id=owner, child_task_id=other, by="M")
    assert stranger["code"] == "unauthorized", stranger
    unknown = cond.interrupt_child(parent_task_id=owner, child_task_id="", by="M")
    assert unknown["code"] == "bad_request", unknown
    # 判不了那一档：台账里没有目标那一行 ⇒ `inside_subtree` 读成 checked=False ⇒ 拒绝
    blind = cond.interrupt_child(parent_task_id=owner, child_task_id="t-0000", by="M")
    assert blind["code"] == "unauthorized" and "判不了" in blind["why"][0], blind

    # no-op：已结束的子代理（DSH 逐字：已经结束的中断是 accepted no-op）
    done_kid = _child(cond, owner, status="done", key="s1h@done")
    noop = cond.interrupt_child(parent_task_id=owner, child_task_id=done_kid, by="M")
    assert noop["accepted"] is True and noop["no_op"] is True, noop
    assert SC.read_interrupt(tmp_path / "ws", done_kid) is None, "no-op 不许留下信号"
    # 正控对照：还在飞的那个受理
    assert cond.interrupt_child(parent_task_id=owner, child_task_id=mine,
                                by="M")["accepted"] is True


def test_the_interrupt_keeps_the_queue_and_does_not_recurse(tmp_path: pathlib.Path) -> None:
    """正控（不递归 + 队列保留）：叫停不动收件箱，也不动目标自己的子代理。

    照 DSH 的四条 no-op：`{keepInbox:true}`（排队消息留着）与"它起的子代理继续跑"。
    """
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    mid = _child(cond, owner, status="running", key="s1h@mid2")
    grand = _child(cond, mid, status="running", key="s1h@grand")
    AL.send_message(tmp_path / "ws", sender="M", to="D", subject="排队的一条",
                    body="等你回来做", sid="t")
    before = AL.inbox_digest(tmp_path / "ws", "D", sid="t")[0]

    got = cond.interrupt_child(parent_task_id=owner, child_task_id=mid, by="M")
    assert got["accepted"] is True, got
    after = AL.inbox_digest(tmp_path / "ws", "D", sid="t")[0]
    assert before == after, "叫停动了收件箱 ⇒ 排队消息被吞了（DSH 的 keepInbox 说留着）"
    # 不递归：它自己起的那个子代理还在飞（台账里那一行没被动过）
    rows = {str(r.get("task_id")): r for r in cond._tasks()}
    assert str(rows[grand].get("status")) == "running", rows[grand]
    assert str(rows[mid].get("status")) == "running", "叫停不许改台账状态（它只是发信号）"


def test_the_loop_reads_the_signal_and_stops_with_its_own_reason(tmp_path: pathlib.Path) -> None:
    """正控（接进循环）：信号在盘上 ⇒ 那一趟以 `interrupted_by_parent` 收工。

    这一条判的是"接线"而不是"机制"：`_user_stop_reason` 是循环每步开头唯一读停机的地方。
    """
    _st, cond, sec = _env(tmp_path)
    loop = AL.AgentLoop(role="D", session_root=tmp_path / "ws", registry=None, seam=None,
                        conductor=cond, sid="t")
    loop.my_task_id = "t-child"
    run = AL.LoopRun(role="D", task="t")
    assert loop._user_stop_reason(run) == "", "没有信号时不许停"
    SC.request_interrupt(tmp_path / "ws", "t-child", by="M", by_task_id="t-parent")
    assert loop._user_stop_reason(run) == SC.INTERRUPT_REASON
    # 一次性：第二次读到的是"没有信号"（审计留在流水里，见上一条判据）
    assert loop._user_stop_reason(run) == ""
    assert SC.read_interrupt(tmp_path / "ws", "t-child") is None


def test_the_shape_and_the_badge_are_registered() -> None:
    """反真空：形状进了 `SHAPES`、协议里写着它、停止理由有徽标、登记表不多不少。"""
    from agentflow import agent_prompts as AP
    from agentflow.webui import server as W

    assert "interrupt" in AL.SHAPES, AL.SHAPES
    text = AP.LOOP_PROTOCOL
    assert '"interrupt"' in text, "协议里没写这个形状 ⇒ 模型永远不会用"
    assert "不要用全局叫停" in text, "协议没教它与全局叫停的区别"
    assert SC.INTERRUPT_REASON in W._STOP_BADGES, sorted(W._STOP_BADGES)
    assert W._STOP_BADGES[SC.INTERRUPT_REASON][0] != "badge-fail", "它不是失败，是上级喊停"
    # 形状表与登记表等额那一条在 `test_secretary` 里（两个方向都判）；这里只做正面读数。
    import test_secretary as TS

    assert "interrupt" in TS.NOT_STRUCTURED, sorted(TS.NOT_STRUCTURED)
    assert "interrupt" not in AL.SECRETARY_OUTBOUND_SHAPES, \
        "叫停不是「发件前优化」那一类（它没有载荷要优化）"
