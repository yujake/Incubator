# -*- coding: utf-8 -*-
"""A 线（委托链与角色实现）的负控与判据：秘书 · 手稿写权移交 · 派活质量的机器侧。

依据：`draft/53`（秘书定位 v3）· `draft/55`（秘书接口规范：知识面 / 动作面 / 工具面 /权限 / 交流协议）· `draft/54 §2`（不走 13 步：1 个共享模块 + 2 个钩子 +
`manuscripts.revise`）·`draft/56 §2 主线 A`（条目 / 线内顺序 / 验收 / 不许碰）。

这份文件里的判据分四组，每一组都对着一个改前必红的负控：

1. 手稿通道：`manuscripts.revise` 今天不存在（追加修订行、不改旧行）；
智能体的写路径关闭（只保留"查"），执笔改由本角色的秘书。
2. 秘书本体：四职责 + 台账（`out/secretary/<role>.jsonl`，每角色一份、追加式）+
fail-open（超时/出错 ⇒ 原样放行 + 留痕）；唯一例外是手稿执笔失败必须报错留痕（不许静默放行，否则手稿会缺行）；不做任何统计（拒绝率/重复率/闭环率/花销告警）。
3. 派活质量的机器侧：错名并列候选（含 writers 子注册表名，不自动改写）、
同 `input_key` 的既有终态行摆到派活前、拒绝进叙事（`task_end` 的机器半）、血缘 `lineage=()` → `None`（否则 `cycle` 判据不可达）、预算只记录不阻断。
4. 停机判据：`running_loops` 按角色配平 + 排除"被拒的续跑"（`resume_refused`）。

三态纪律贯穿：秘书没跑成（fail-open）与"跑成了没问题"不折平（`fail_open` 字段）；手稿"没写"与"写了空"不折平（写入期拒绝空手稿）。
"""
from __future__ import annotations

import importlib
import json
import pathlib
import threading
from typing import Any

import pytest

from agentflow import manuscripts as MS
from agentflow import schema as S
from agentflow import sessions as SESS
from agentflow import stopctl as SC
from agentflow.store import Store


# ---------------------------------------------------------------- 工具


def _sec():
    """延迟 import：秘书模块改前不存在 ⇒ 每条判据各自红（不是整个文件收集失败）。"""
    return importlib.import_module("agentflow.secretary")


def _mk_store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _cond(store: Store, **kw):
    from agentflow import conductor as CO

    return CO.Conductor(store, backend="subagent", **kw)


# ================================================================ 1 手稿通道


def test_revise_appends_a_revision_row_and_keeps_the_old_one(tmp_path: pathlib.Path):
    """判据：`manuscripts.revise` 追加一条修订行，旧行逐字节不动（append-only）。"""
    root = tmp_path / "ws"
    root.mkdir()
    orig = MS.write(root, sender="D", recipient="F", summary="交给你", body="第一版。")
    before = MS.row_of(root, orig["id"])
    assert callable(getattr(MS, "revise", None)), "manuscripts 今天没有 revise（待新增）"
    rev = MS.revise(root, mid=orig["id"], summary="交给你（订正）", body="第二版。",
                    reason="第一版引错了手稿号")
    # 旧行还在、逐字节没变
    assert MS.row_of(root, orig["id"]) == before, "旧行被改了：修订必须是追加、不是改写"
    # 修订行自证"我订正的是谁"
    assert rev["revises"] == orig["id"], rev
    assert rev["id"] != orig["id"], "修订行要有自己的编号（编号空间是账本的行号）"
    assert "第二版" in MS.read(root, rev["id"])["text"]
    # 可查：这一份被订正过几次
    assert [r["id"] for r in MS.revisions_of(root, orig["id"])] == [rev["id"]]
    # 拒绝：订正一份不存在的手稿 = 凭空引用
    with pytest.raises(ValueError):
        MS.revise(root, mid="9999", summary="x", body="y")


def test_agent_side_handoff_without_a_secretary_writes_nothing(tmp_path: pathlib.Path):
    """判据（验收 ①）：关掉 `handoff` 写路径后，智能体侧再写手稿必须不落行。

    "智能体只保留查"（`draft/53` §2.1 / `draft/55` §3.2）：形状保留（本体仍旧说
    "我要交接什么"），但执笔权在秘书手里。没有秘书 ⇒ 这一步不写，且如实报错。
    """
    from agentflow.agent_loop import AgentLoop
    from agentflow.llmseam import LlmSeam
    from agentflow.tools import build_registry

    root = tmp_path / "ws"
    root.mkdir()
    loop = AgentLoop(role="D", session_root=root, registry=build_registry(),
                     seam=LlmSeam.for_role("D", session_root=root, from_env=False))
    out = loop._do_handoff({"to": "F", "summary": "交给你", "body": "证明它。"})
    assert out.get("ok") is False, out
    assert MS.rows(root) == [], "智能体侧仍然自己写了手稿（写路径没关）"
    assert "秘书" in str(out.get("error") or ""), out


def test_secretary_writes_the_row_with_the_served_role_as_sender(tmp_path: pathlib.Path):
    """判据：秘书执笔，但行里的 `sender` 仍是被服务的角色（作者=角色、执笔=秘书）。"""
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    s = sec.Secretary("D", root=root)
    rec = s.handoff_add(to="F", summary="把猜想交给你", body="## 任务\n证明它。",
                        refs=(), task_id="t-0001")
    assert rec["sender"] == "D", rec
    assert rec["id"] == S.format_id(0)
    assert MS.rows(root) and MS.rows(root)[0]["sender"] == "D"
    # 台账记下"我替谁执笔了哪一行"
    led = s.decisions()
    assert led and led[-1]["mid"] == rec["id"] and led[-1]["role"] == "D", led


def test_secretary_ledger_is_per_role_appended(tmp_path: pathlib.Path):
    """判据：每个角色一份台账（`out/secretary/<role>.jsonl`），追加式、脚本发号。"""
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    d = sec.Secretary("D", root=root)
    m = sec.Secretary("M", root=root)
    d.note_decision(duty=2, kind="secretary_decision", decision="建议重排", reason="重复候选")
    m.note_decision(duty=2, kind="secretary_decision", decision="可派", reason="没有重复")
    assert (root / "out" / "secretary" / "D.jsonl").is_file()
    assert (root / "out" / "secretary" / "M.jsonl").is_file()
    rows = [json.loads(x) for x in
            (root / "out" / "secretary" / "D.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert [r["seq"] for r in rows] == [1], rows
    assert all(r["role"] == "D" for r in rows), "台账混写了别的角色"


def test_secretary_handoff_failure_is_loud_not_silent(tmp_path: pathlib.Path):
    """判据：手稿执笔失败必须报错留痕（唯一不许 fail-open 的一格）。"""
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    s = sec.Secretary("D", root=root)
    with pytest.raises(ValueError):
        s.handoff_add(to="F", summary="", body="有正文但没有一句话")
    assert MS.rows(root) == []
    led = s.decisions()
    assert led and led[-1].get("fail_open") is False and led[-1].get("error"), led


def test_secretary_fails_open_on_its_own_error(tmp_path: pathlib.Path, monkeypatch):
    """判据（`draft/53` §9.7）：秘书自己出错 ⇒ 原样放行 + 留痕（不许阻塞一条委托）。"""
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    s = sec.Secretary("D", root=root)
    monkeypatch.setattr(s, "_role_brief", lambda role: (_ for _ in ()).throw(RuntimeError("boom")))
    payload = {"to": "F", "summary": "一句话", "body": "正文"}
    got = s.optimize_outbound("handoff", dict(payload))
    assert got["payload"] == payload, "fail-open 必须是原样放行"
    assert got["fail_open"] is True and got["problem"], got
    assert s.decisions()[-1]["fail_open"] is True


def test_secretary_tools_face_is_empty_and_it_does_no_statistics():
    """判据（`draft/55` §3.3 / §4 末）：不进工具注册表、不做任何统计。"""
    sec = _sec()
    from agentflow.tools import build_registry

    names = set(build_registry().registry.names())
    assert not [n for n in names if "secretary" in n or "秘书" in n], sorted(names)
    s = sec.Secretary("M", root=".")
    banned = ("rate", "ratio", "statistics", "stats", "metric", "report_rate",
              "closure_rate", "duplicate_rate", "alert")
    for name in banned:
        assert not any(name in a for a in dir(s)), f"秘书上出现了统计面：{name}"


def test_secretary_knowledge_is_read_only_and_open_for_all_roles(tmp_path: pathlib.Path):
    """判据（`draft/53` §2.2）：组织图全开（任意角色），但数据面 ≤ 本体。"""
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    s = sec.Secretary("D", root=root)
    k = s.knowledge()
    assert set(k["roles"]) >= {"A", "B", "C", "D", "E", "F", "G", "H", "M"}, k["roles"]
    assert "D" in k["briefs"], "连本角色的 brief 都读不到"
    assert k["writes"] == frozenset(sec.STATEMENT_WRITE_TABLES), (
        "秘书的写集只有命题写入代理那两张表（手稿通道与自己的台账不走 store.tx）："
        "2026-10-09 业主把'B 的写入'交给秘书之后，这一格不再是 ∅")
    # 数据面 ≤ 本体：它只读"委托事实"与硬性要求，不读研究叙事正文
    assert k["reads_narrative"] is False


def test_v_secretary_does_not_read_f_narrative(tmp_path: pathlib.Path):
    """判据（`draft/55` §1.5 ②）：数据面 <= 本体；且 V 的秘书不读 F 的叙述。

    I12 的独立性不许被秘书绕过：V 的秘书只读"委托本身 + 硬性要求 + 全角色定位
    + V 自己的台账"，不读任何人的研究叙事（含 F 的）。
    """
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    v = sec.Secretary("V", root=root)
    assert v.may_read_narrative("F") is False
    assert v.may_read_narrative("V") is False
    # 一般角色的秘书：数据面 <= 本体 ⇒ 只读自己所服务的那名智能体的叙述；
    # 别人的叙述不许读、也不许转述（组织图另说：定位面对每名秘书全开）。
    d = sec.Secretary("D", root=root)
    assert d.may_read_narrative("D") is True
    assert d.may_read_narrative("F") is False


def test_secretary_prescreens_and_only_engages_on_alarm(tmp_path: pathlib.Path):
    """判据（`draft/53` §6 / `draft/55` §5.2）：机器预筛 + 按需介入（不是每条都叫模型）。"""
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    s = sec.Secretary("M", root=root)
    ok = s.prescreen(to="D", action="register_conjecture",
                     params={"statement": "任一有限图都有...", "origin": "M 派活"})
    assert ok == [], ok
    bad = s.prescreen(to="D", action="register_conjecture", params={})
    assert bad and any("statement" in x for x in bad), bad
    assert s.should_engage(alarms=bad, duplicates=0, overdue=0, novel=True) is True
    assert s.should_engage(alarms=[], duplicates=0, overdue=0, novel=False) is False


def test_secretary_tool_names_fallback_uses_the_registry_it_can_build(
        tmp_path: pathlib.Path):
    """    判据（2026-10-04 主控探针实测的缺陷）：`registry=None` 时 fallback 必须带 `store`。

    改前：没有 `registry` 时 fallback 是 `build_registry()`（不带 `store`）——实测 68 件真名，而
    `fs.read` 不在里面；`build_registry(store=...)` 是 81 件、`fs.read` 在里面。后果是真名被判成错名：任何
    `registry=None` 的调用方（`for_role(..., registry=None)` 是默认）都会对 `fs.read` 报`'fs.read' 不是注册表里的真名；并列候选：[…]`。假阳性比漏报更坏
    ——它会让本体去改一个本来对的写法。

    三条一起判（①②是负控的两侧，③是三态）：① `registry=None` + 有 store ⇒ 真名表里有 `fs.read`，且对 `fs.read` 不报警；② 反负控：真不存在的名字仍要报警，且候选首选是
    `fs.read`；③ 没有 store ⇒ 空表，且不报"不是真名"（"没读到"不许读成"没有真名"）。
    """
    sec = _sec()
    st = _mk_store(tmp_path)
    s = sec.Secretary("M", root=st.root, store=st)          # registry 缺省 = None
    names = s._tool_names()
    assert "fs.read" in names, f"fallback 没带 store ⇒ 真名表残缺（{len(names)} 件）"
    ok = s.prescreen(to="D", action="register_conjecture",
                     params={"statement": "x", "origin": "M 派活"}, tool="fs.read")
    assert not [a for a in ok if "不是注册表里的真名" in a], ok
    # 反负控：错名（真不存在）仍要报警，且并列候选首选应当是 fs.read
    bad = s.prescreen(to="D", action="register_conjecture",
                      params={"statement": "x", "origin": "M 派活"}, tool="fs.raed")
    hit = [a for a in bad if "不是注册表里的真名" in a]
    assert hit, bad
    assert "fs.read" in hit[0], hit[0]
    # 三态：没有 store ⇒ 空表（"没读到"），且不许因此报"不是真名"
    bare = sec.Secretary("M", root=st.root)
    assert bare._tool_names() == []
    quiet = bare.prescreen(to="D", action="register_conjecture",
                           params={"statement": "x", "origin": "M 派活"}, tool="fs.read")
    assert not [a for a in quiet if "不是注册表里的真名" in a], quiet


class _StubSeam:
    """替身缝：只实现 `Secretary.judge` 用到的那一个入口（`ask_json`）。

    它不联网、不花钱，并记下被问了几次 —— "按需介入"这条判据要能数出来。
    """

    def __init__(self, reply=None, problem="", detail=""):
        self.reply = reply
        self.problem = problem
        self.detail = detail
        self.calls: list[str] = []

    class _Call:
        def __init__(self, ok, problem, detail):
            self.ok, self.problem, self.detail = ok, problem, detail

    def ask_json(self, prompt, **kw):
        self.calls.append(str(kw.get("note") or ""))
        if self.problem:
            return None, self._Call(False, self.problem, self.detail or "超时")
        return dict(self.reply or {}), self._Call(True, "", "")


def test_secretary_judgment_is_model_backed_and_three_state(tmp_path: pathlib.Path):
    """判据：判断类走本智能体自己的缝；没缝/超时/坏结论一律 `checked=False`（不冒充可派）。"""
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    # ① 没缝 ⇒ 判断这一格"没查成"，而不是"可派"
    plain = sec.Secretary("M", root=root)
    got = plain.judge("duplicate_retry", {"input_key": "k"})
    assert got["checked"] is False and got["reason"], got
    # ② 有缝但 enable_model=False ⇒ 同上（模型调用被显式关掉）
    off = sec.Secretary("M", root=root, seam=_StubSeam({"decision": "可派"}), enable_model=False)
    assert off.judge("rearrange", {})["checked"] is False
    # ③ 打开：结论被采信，且词表外的结论不采信
    seam = _StubSeam({"decision": "建议重排", "reason": "应改走两步", "basis": ["specs/d.py"]})
    on = sec.Secretary("M", root=root, seam=seam, enable_model=True)
    judged = on.judge("duplicate_retry", {"input_key": "k"})
    assert judged["checked"] is True and judged["decision"] == "建议重排", judged
    assert judged["basis"] == ["specs/d.py"], judged
    bogus = sec.Secretary("M", root=root, seam=_StubSeam({"decision": "大概行吧"}),
                          enable_model=True)
    assert bogus.judge("duplicate_retry", {})["checked"] is False, "词表外的结论不许采信"
    # ④ 超时（缝没查成）⇒ 判断没做，台账里写明
    to = sec.Secretary("M", root=root, seam=_StubSeam(problem="judge_timeout"), enable_model=True)
    assert to.judge("rearrange", {})["checked"] is False


def test_should_engage_actually_gates_the_model_call(tmp_path: pathlib.Path):
    """判据：`should_engage` 有真调用点 —— 干净的派活一次模型都不叫，重复候选才叫。"""
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    st = _mk_store(tmp_path)
    cond = _cond(st)
    cond.summon("C", "hottest", {"top_n": 5}, by="M", input_key="k1")
    dups = cond.duplicate_candidates("C", "hottest", "k1")

    seam = _StubSeam({"decision": "建议重排", "reason": "同一件事已经交付过"})
    s = sec.Secretary("M", root=root, seam=seam, enable_model=True)
    clean = s.assess_delegation(to="C", action="hottest", params={"top_n": 5}, input_key="k9")
    assert clean["decision"] == "可派" and clean["engaged"] is False, clean
    assert seam.calls == [], f"干净的派活也叫了模型：{seam.calls}"
    dup = s.assess_delegation(to="C", action="hottest", params={"top_n": 5},
                              input_key="k1", duplicates=dups)
    assert len(seam.calls) == 1, f"重复候选时应当**恰好**叫一次模型：{seam.calls}"
    assert dup["judge"]["checked"] is True and dup["decision"] == "建议重排", dup
    # 台账里同时留着原文与判断三态（`checked` / `decision` / `reason`）
    led = s.decisions()
    assert led[-1]["judge"]["checked"] is True and led[-1]["decision"] == "建议重排", led[-1]


def test_production_assembly_opens_the_judgment_with_the_same_seam(tmp_path: pathlib.Path):
    """判据（主控裁定 A5 的第 ① ② 条）：生产装配用本体自己的那一个缝且打开判断。

    为什么必须测装配那一层：`Secretary.judge` 的代码在不在，与"生产里会不会跑"
    是两件事 —— 缺省 `enable_model=False` 时三条判断在生产里等于不存在，
    而"把该不该派的判断全写死成确定性规则"正是用户点名不要的形态。
    """
    from agentflow import agent_loop as AL

    root = tmp_path / "ws"
    root.mkdir()
    st = _mk_store(tmp_path)
    seam = _StubSeam({"decision": "可派"})
    got = AL._secretary_for("M", root=root, store=st, registry=None, seam=seam, sid="s1")
    assert got.seam is seam, "装配时必须传**同一个**缝实例（同一份账本/预算/角色）"
    assert got.enable_model is True, "生产装配必须打开判断类（A5 的裁定）"
    assert got.sid == "s1" and got.role == "M"


def test_judge_failure_never_breaks_the_loop(tmp_path: pathlib.Path):
    """判据（A5 的第 ② 条后半）：缝为 None / 抛异常 ⇒ `checked=False` 且循环照跑。"""

    class _Boom:
        def ask_json(self, prompt, **kw):
            raise RuntimeError("缝炸了")

    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    boom = sec.Secretary("M", root=root, seam=_Boom(), enable_model=True)
    judged = boom.judge("rearrange", {"to": "D"})
    assert judged["checked"] is False and "缝炸了" in judged["reason"], judged
    out = boom.optimize_outbound("summon", {"role": "D", "action": "register_conjecture",
                                            "params": {}})
    assert out["payload"]["role"] == "D" and out["fail_open"] is False, out

    from agentflow.agent_loop import AgentLoop
    from agentflow.llmseam import LlmSeam
    from agentflow.tools import build_registry

    loop = AgentLoop(role="M", session_root=root, registry=build_registry(),
                     seam=LlmSeam.for_role("M", session_root=root, from_env=False),
                     secretary=boom)
    note = loop._outbound_hook("summon", {"role": "D", "action": "register_conjecture"})
    assert "assessment" in note or note.get("assessment_fail_open"), note
    assert loop._inbound_hook([]) == {}


def test_judge_cost_is_attributable_to_a_ledger_row(tmp_path: pathlib.Path):
    """判据（A5 的第 ③ 条 + `draft/56 §2` A 验收的"决定台账 0→N"读数）。

    离线替身（`ModelGateway` + 替身 transport，不联网、不调模型、临时工作区）：
    让秘书真的走一次 `judge`，然后核三件事 ——

    1. 决定台账 `out/secretary/M.jsonl` 里出现了那一行，且 `judge.cost.ledger`
       指得回 `usage_ledger` 里真有的 `usage_id`；
    2. 那一笔账挂不上任务号（`task_id=None`）—— 与 A1 的"未接线不许折成假字符串"
       同一条口径，`verify_all` 不报 `dangling_usage_task`；
    3. 台账里的 `before/after` 与结论三态都在（人看过程、本体看结果）。
    """
    import json as _json

    from agentflow import verify as V
    from agentflow.modelgw import ModelGateway, ModelSpec
    from agentflow.llmseam import LlmSeam
    from agentflow.tokenmeter import TokenMeter

    st = _mk_store(tmp_path)
    root = st.root

    def _transport(url, headers, data, timeout_sec):
        body = _json.dumps({
            "choices": [{"message": {"role": "assistant", "content":
                                     _json.dumps({"decision": "建议不派",
                                                  "reason": "同一件事已经交付过",
                                                  "basis": ["tasks: 同 key 终态行"]},
                                                 ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }, ensure_ascii=False)
        return 200, body

    seam = LlmSeam.for_role("M", session_root=root,
                            gateway=ModelGateway(ModelSpec(api_key="k"), transport=_transport),
                            meter=TokenMeter(st), sid="sec-cost", from_env=False)
    s = _sec().for_role("M", root=root, store=st, seam=seam, enable_model=True, sid="sec-cost")
    got = s.judge("duplicate_retry", {"to": "C", "action": "hottest", "input_key": "k1",
                                      "duplicates": [{"task_id": "t-0001"}]})
    assert got["checked"] is True and got["decision"] == "建议不派", got
    cost = got["cost"]
    assert cost["ledger"], f"判断的花销没有归因到账本行：{cost}"
    rows = st.rows("usage_ledger")
    assert [r["usage_id"] for r in rows] == [cost["ledger"]], (cost, rows)
    assert rows[0].get("task_id") in (None, ""), rows[0]
    assert rows[0]["scope"] == "reason" and rows[0]["usd"] > 0, rows[0]
    report = V.verify_all(st)
    assert [i for i in report.issues if i.code == "dangling_usage_task"] == []
    # 决定台账：一行、带 cost、带三态、带原文
    led = s.decisions()
    assert len(led) == 1 and led[0]["judge"]["cost"]["ledger"] == cost["ledger"], led
    assert led[0]["role"] == "M" and led[0]["seq"] == 1 and led[0]["at"], led[0]
    assert led[0]["judge"]["checked"] is True, led[0]

    # 缝报不出花销时（meter=None）如实写"查不到/没入账"，不许折成"花了 0"
    off = LlmSeam.for_role("M", session_root=root,
                           gateway=ModelGateway(ModelSpec(api_key="k"), transport=_transport),
                           sid="sec-cost2", from_env=False)
    s2 = _sec().for_role("M", root=root, store=st, seam=off, enable_model=True, sid="sec-cost2")
    got2 = s2.judge("rearrange", {"to": "D"})
    assert got2["checked"] is True
    assert got2["cost"]["ledger"] == "" and got2["cost"]["reason"], got2["cost"]
    assert got2["cost"]["charged"] is False, got2["cost"]


def test_last_judge_cost_is_directly_callable_and_three_state(tmp_path: pathlib.Path):
    """判据（C 的 F7 直接测试要求）：`Secretary.last_judge_cost` 直接调用、覆盖两档。

    为什么必须有一条直接调用它的测试（不是靠工具名串或间接覆盖）：
    `tools/coverage_zero_test.py` 把它算作"零直接测试"，于是发布门的 `coverage` 步
    `gate=1`、`release_all` 那一步 exit 1 —— 一个函数挡着整个发布门。

    两档都要有：取不到 ⇒ 如实给理由（"没查成"不许折成"没花过钱"）；
    取得到 ⇒ 给 `usage_id` 与 `call_index`（这正是 A5"花费可归因"的那一半）。
    """
    import json as _json

    from agentflow.llmseam import LlmSeam
    from agentflow.modelgw import ModelGateway, ModelSpec
    from agentflow.tokenmeter import TokenMeter

    sec = _sec()
    st = _mk_store(tmp_path)
    root = st.root
    s = sec.for_role("M", root=root, store=st, sid="cost-direct")
    # ① 会话里没有这次判断的事件 ⇒ 如实给"查不到"（不是 0、也不是空串了事）
    miss = s.last_judge_cost("duplicate_retry")
    assert miss["ledger"] == "" and miss["reason"].startswith("查不到"), miss
    assert miss.get("call_index") == 0, miss

    # ② 真发一次判断（离线替身 transport，不联网）⇒ 直接调它必须给出 usage_id/call_index
    def _transport(url, headers, data, timeout_sec):
        body = _json.dumps({
            "choices": [{"message": {"role": "assistant", "content": _json.dumps(
                {"decision": "建议重排", "reason": "该走两步", "basis": ["specs/d.py"]},
                ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
        }, ensure_ascii=False)
        return 200, body

    seam = LlmSeam.for_role("M", session_root=root,
                            gateway=ModelGateway(ModelSpec(api_key="k"), transport=_transport),
                            meter=TokenMeter(st), sid="cost-direct", from_env=False)
    s2 = sec.for_role("M", root=root, store=st, seam=seam, enable_model=True, sid="cost-direct")
    got = s2.judge("rearrange", {"to": "D"})
    assert got["checked"] is True, got
    cost = s2.last_judge_cost("rearrange")          # ← 直接调用（这就是那条判据）
    assert cost["ledger"] and cost["ledger"] == got["cost"]["ledger"], (cost, got)
    assert cost["charged"] is True and cost["call_index"] == 0, cost
    assert cost["prompt_sha256"] and cost["tokens"] == 13, cost
    assert [r["usage_id"] for r in st.rows("usage_ledger")] == [cost["ledger"]], \
        st.rows("usage_ledger")


def test_secretary_assesses_duplicates_and_surfaces_them(tmp_path: pathlib.Path):
    """判据（`draft/53` §10）：派活去重归发件方秘书；机器只把同 key 的既有终态行摆出来。"""
    sec = _sec()
    st = _mk_store(tmp_path)
    root = str(st.root)
    cond = _cond(st)
    cond.summon("C", "hottest", {"top_n": 5}, by="M", input_key="k1")
    cands = cond.duplicate_candidates("C", "hottest", "k1")
    assert len(cands) == 1, cands
    s = sec.Secretary("M", root=root, store=st)
    got = s.assess_delegation(to="C", action="hottest", params={"top_n": 5},
                              input_key="k1", duplicates=cands)
    assert got["decision"] in ("建议重排", "建议不派", "可派"), got
    assert got["decision"] != "可派", "同 key 已有终态行时不许判『可派』"
    assert got["basis"], got


# ================================================================ 3 派活质量的机器侧


def test_secretary_consumes_the_todo_queue_and_reminds_closure(tmp_path: pathlib.Path):
    """判据（F-05 的消费端）：待办队列由秘书消费，读不成与"没有待办"分开报。

    生产端是机器（`search_requests` / `reprocess_requests` 的 pending + `running` 的任务行）；
    消费端是各角色自己的秘书。三态纪律：表读不出来 ⇒ `checked=False` + `reason`
    （不是 `todos=[]`），且 `remind_closure()` 走"没读成"那一支留痕、绝不当成清零。
    """
    from conftest import add_request

    sec = _sec()
    st = _mk_store(tmp_path)
    s = sec.Secretary("D", root=st.root, store=st)
    empty = s.inbox_todos()
    assert empty["checked"] is True and empty["todos"] == [], empty
    add_request(st, "r-0001", topic="periodic elliptic operators")
    add_request(st, "r-0002", topic="Floquet Bloch", done=True, result_lit_ids=["0001"])
    got = s.inbox_todos()
    assert got["checked"] is True and [t["id"] for t in got["todos"]] == ["r-0001"], got
    assert got["todos"][0]["state"] == "unclaimed" and got["by_kind"] == {"search_request": 1}, got
    reminded = s.remind_closure()
    assert [r["task_id"] for r in reminded] == ["r-0001"], reminded
    assert s.decisions()[-1]["duty"] == 3, s.decisions()[-1]
    # 读不成 ⇒ 如实报"没读成"，并且不当成"没有待办"
    class _Broken:
        root = st.root

        def rows(self, table):
            raise OSError("表读不出来")

    bad = sec.Secretary("D", root=st.root, store=_Broken())
    broken = bad.inbox_todos()
    assert broken["checked"] is False and "读不出来" in broken["reason"], broken
    assert bad.remind_closure() == []
    assert bad.decisions()[-1]["fail_open"] is True, bad.decisions()[-1]


# ------------------------------------------- 3b 职责 3 的生产调用点（收尾点）

def _finished_run(st: Store, cond, task: str = "顶趟") -> str:
    """开一趟顶趟并立刻收尾，返回顶趟行的 `task_id`。"""
    tid = cond.open_top_level_run("M", task)
    cond.finish_top_level_run(tid, stop_reason="final", detail="收工")
    return tid


def _run_row(st: Store, tid: str) -> dict:
    row = next((r for r in st.rows("tasks") if str(r.get("task_id") or "") == tid), None)
    assert row is not None, f"顶趟行 {tid} 不在台账里"
    return row


def test_closure_reminders_are_produced_at_the_top_level_finish(tmp_path: pathlib.Path):
    """判据（主控 2026-10-04 裁定：职责 3 是"接上"，不是"登记"）。

    改前红：`remind_closure` 在生产里只有定义、没有调用点（`conductor.py` 与
    `agent_b/register_statement.py` 那两处只是注释在说"秘书会提醒"）⇒ 收尾读数里
    什么都不会有。改后：造一条"提交了但没人接手"的待办 ⇒ 收尾读数点名它。

    两半一起判：
    ① 干净的一趟（没有待办）⇒ `checked=True, count=0`，两个分组都空
       （反负控：不许凭空列人；也不许把"没有未闭环"写成"没查成"）；
    ② 有待办的一趟 ⇒ 读数点名那条、分组是 `unclaimed`，并且顶趟行的 detail 里
       有一句话摘要（"每趟的读数"要有落点），台账里逐条留痕。
    """
    from conftest import add_request

    sec = _sec()
    st = _mk_store(tmp_path)
    s = sec.Secretary("M", root=st.root, store=st)
    cond = _cond(st, secretary=s)

    # ① 干净
    clean_tid = _finished_run(st, cond, "干净的一趟")
    clean = cond.stats()["closure_reminders"]
    assert clean["checked"] is True and clean["count"] == 0, clean
    assert clean["by_state"] == {} and clean["by_to"] == {}, clean
    assert "0 条未闭环" in _run_row(st, clean_tid)["detail"], _run_row(st, clean_tid)["detail"]

    # ② 提交了但没人接手（不改写任何行：只读扫表）
    add_request(st, "r-0001", topic="periodic elliptic operators")
    busy_tid = _finished_run(st, cond, "有待办的一趟")
    got = cond.stats()["closure_reminders"]
    assert got["checked"] is True and got["count"] == 1, got
    assert [x["task_id"] for x in got["reminded"]] == ["r-0001"], got
    assert got["by_state"] == {"unclaimed": 1} and got["by_to"] == {"M": 1}, got
    detail = _run_row(st, busy_tid)["detail"]
    assert "闭环提醒 1 条" in detail and "unclaimed" in detail, detail
    # 每条进决定台账：最后两行是"摘要 + 逐条"，逐条那行带 task_id/state/to
    tail = s.decisions()[-2:]
    assert [r["duty"] for r in tail] == [3, 3], tail
    assert tail[1]["target"]["task_id"] == "r-0001", tail[1]
    assert tail[1]["target"]["state"] == "unclaimed", tail[1]


def test_closure_reading_says_not_checked_when_no_secretary_is_wired(tmp_path: pathlib.Path):
    """三态：没有装配秘书 ⇒ `checked=False` + 理由 —— "没查成"不是"没有未闭环"。

    这一格最容易被读错：收尾读数空着时，读的人会以为"这一趟没有未闭环"。
    所以两处都要如实说：`stats()` 里给理由，顶趟行的 detail 里写"没查成"。
    """
    st = _mk_store(tmp_path)
    cond = _cond(st)                                   # 不给 secretary
    tid = _finished_run(st, cond)
    got = cond.stats()["closure_reminders"]
    assert got["checked"] is False and "没有装配秘书" in got["reason"], got
    assert got["count"] == 0 and got["reminded"] == [], got
    assert "闭环提醒没查成" in _run_row(st, tid)["detail"], _run_row(st, tid)["detail"]


def test_closure_reminder_failure_does_not_break_the_finish(tmp_path: pathlib.Path):
    """fail-open（与其余四职责同姿态）：秘书坏了照样收尾，且如实记 `fail_open`。"""
    sec = _sec()
    st = _mk_store(tmp_path)

    class _Boom:
        def remind_closure(self, *a, **kw):
            raise RuntimeError("秘书坏了")

    cond = _cond(st, secretary=_Boom())
    tid = _finished_run(st, cond)
    got = cond.stats()["closure_reminders"]
    assert got["checked"] is False and got.get("fail_open") is True, got
    assert "没跑成" in got["reason"], got
    row = _run_row(st, tid)
    assert row["status"] == "done", "提醒失败不许打断收尾（顶趟那一行仍然要收）"
    assert "闭环提醒没查成" in row["detail"], row["detail"]


# ------------------------------------------- 3c 生产面接线（`R2b-⑲`：五个方法各一个落点）
#
# 改前基线（`temp/_reachability_probe.py`，口径 = 自检/测试/探针不算入口）：
# `negotiate` 0 · `handoff_revise` 只落在 `selftest()` 里 · `handoff_query` 同 ·
# `handoffs_digest` 0 · `decision_problems` 0 ⇒ 这五个在生产链路上都走不到。
# 接线后各 生产面 1（读数逐条见交付说明）。


def _loop_with_secretary(tmp_path, *, role="D", conductor=None):
    """造一个带秘书的循环（钩子单测用；不启真模型）。

    注册表必须是真的那一份：秘书的 `optimize_outbound` / `rework_inbound` 会读
    "本角色拿得到哪些工具"（`agent_prompts.role_tools(registry)`），拿一个空 dict 会炸
    —— 那正是"提示词面与执行面必须是同一个注册表"这条纪律在测试里的体现。
    """
    from agentflow.agent_loop import AgentLoop
    from agentflow.llmseam import LlmSeam
    from agentflow.tools import build_registry

    st = _mk_store(tmp_path)
    root = pathlib.Path(st.root)
    reg = build_registry(store=st).registry
    sec = _sec().Secretary(role, root=root, store=st, registry=reg)
    loop = AgentLoop(role=role, session_root=root, registry=reg,
                     seam=LlmSeam(role=role, session_root=root, price=(0.0, 0.0), sid="t"),
                     conductor=conductor, secretary=sec, sid="t", store=st)
    # S6-a：公聊的可见面是"发信人的直接子代理" ⇒ 发公聊要有台账号（生产形态下
    # `run()` 一定绑上它）。这个夹具补上它，于是"秘书的问题不阻断发信"这几条
    # 判据量的仍然是秘书那一层，而不是"没有身份"。
    loop.my_task_id = "t-0001"
    return st, sec, loop


def test_negotiate_is_reachable_from_the_outbound_hook(tmp_path: pathlib.Path):
    """`R2b-⑲`：委派评估摆了重复候选 ⇒ 秘书真的发起协商；同一处再犯 ⇒ 上报本体。

    改前：`negotiate` 生产面 0（只有 `selftest()` 与 docstring 提到它）⇒ 这条路径不存在。
    """
    class _Cond:
        def duplicate_candidates(self, role: str, action: str, key: str) -> list[dict]:
            return [{"task_id": "t-0001", "status": "done"}]

    st, sec, loop = _loop_with_secretary(tmp_path, conductor=_Cond())
    payload = {"role": "D", "action": "register_conjecture", "params": {"statement": "x"}}
    first = loop._outbound_hook("summon", payload)
    assert first.get("negotiation"), first
    assert first["negotiation"]["outcome"] == "待回应", first
    assert not first.get("escalate_to_body"), "第一轮就上报 = 协商没意义"
    assert sec.decisions()[-1]["duty"] == 2, sec.decisions()[-1]     # 协商进台账（职责 2）
    # `negotiate` 的口径是"最多 2 轮，之后上报本体"（`MAX_NEGOTIATION_ROUNDS=2`）⇒
    # 第三轮（`rounds` 已有 2 条）必须给出上报那一档。
    second = loop._outbound_hook("summon", payload)
    assert second.get("negotiation") and not second.get("escalate_to_body"), second
    third = loop._outbound_hook("summon", payload)
    assert third.get("escalate_to_body"), third
    assert "两轮" in third["escalate_to_body"]["why"], third


def test_handoff_query_runs_before_writing_the_manuscript(tmp_path: pathlib.Path):
    """`R2b-⑲`：写手稿之前先查一次"这件事是不是已经交接过"（判重复委派；只摆读数）。"""
    st, sec, loop = _loop_with_secretary(tmp_path)
    first = loop._do_handoff({"to": "F", "summary": "同一句话", "body": "正文一"})
    assert first["ok"] and first["existing_same_summary"]["count"] == 0, first
    second = loop._do_handoff({"to": "F", "summary": "同一句话", "body": "正文二"})
    assert second["ok"], second
    assert second["existing_same_summary"]["count"] == 1, second
    assert second["existing_same_summary"]["ids"] == [first["id"]], second


def test_handoff_revise_is_reachable_from_the_handoff_shape(tmp_path: pathlib.Path):
    """`R2b-⑲`：`handoff` 带 `revises` ⇒ 走秘书的 `handoff_revise`（追加修订行、旧行保留）。"""
    from agentflow import manuscripts as _MS

    st, sec, loop = _loop_with_secretary(tmp_path)
    first = loop._do_handoff({"to": "F", "summary": "初版", "body": "v1"})
    rev = loop._do_handoff({"to": "F", "summary": "订正", "body": "v2",
                            "revises": first["id"]})
    assert rev["ok"] and rev["revises"] == first["id"], rev
    assert _MS.revisions_of(st.root, first["id"]), "修订行没落盘（`MS.revise` 没被走到）"
    assert _MS.row_of(st.root, first["id"]), "旧行必须保留"


def test_handoffs_digest_is_reachable_from_the_inbound_hook(tmp_path: pathlib.Path):
    """`R2b-⑲`：收件那一刻本体能看到手稿通道的摘要（空通道要如实说"读成了、没有"）。"""
    st, sec, loop = _loop_with_secretary(tmp_path)
    empty = loop._inbound_hook([{"sender": "M", "body": "在吗"}])
    assert "handoffs_digest" in empty, empty
    # "读成了、最近没有交接"由摘要自己的文案说清（`MS.digest` 给的是"（还没有交接手稿）"），
    # 而不是靠"空字符串"表达 —— 空串与"没读成"必须分得开。
    assert "还没有交接" in empty["handoffs_digest"], empty["handoffs_digest"]
    loop._do_handoff({"to": "F", "summary": "有手稿了", "body": "x"})
    after = loop._inbound_hook([{"sender": "M", "body": "在吗"}])
    assert after["handoffs_digest"] != empty["handoffs_digest"], after


def test_decision_problems_show_up_in_the_run_notes(tmp_path: pathlib.Path):
    """`R2b-⑲`：秘书台账的坏行进这一趟的读数（不是门：不改变任何判定）。"""
    from agentflow import agent_loop as AL
    from agentflow.llmseam import LlmSeam

    st = _mk_store(tmp_path)
    sec = _sec()
    s = sec.Secretary("M", root=st.root, store=st)
    s.note_decision(duty=1, decision="正常一行", reason="x")
    path = pathlib.Path(sec.decisions_path(st.root, "M"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{这不是 JSON\n")
    assert s.decision_problems(), "前置：坏行要能被报出来"

    root = pathlib.Path(st.root)
    from agentflow.tools import build_registry

    run = AL.run_role("M", "空任务", store=st, registry=build_registry(store=st).registry,
                      seam=LlmSeam.for_role("M", session_root=root, from_env=False),
                      session_root=root, from_env=False)
    assert any("秘书台账" in n for n in run.notes), run.notes


def _stmt_row(st: Store, sid: str, **kw) -> None:
    """写一条合规的命题行（形状照 `tests/test_statements_table.py::_stmt`）。"""
    from conftest import TS as _TS

    from agentflow import schema as _S

    base = dict(
        stmt_id=sid, origin="external_lit", kind="theorem", label="Theorem 1.5",
        statement_text="随机游走的距离有 CLT 型极限",
        statement_full="设 G 是有限连通图，X_n 是它上面的随机游走；则极限是正态",
        proof_text="Proof. 见附录 A。", source_lit_id="0000", quote_verified=True,
        quote_reason="逐字比对通过", evidence_kind="cross_check", status="active",
        created_at=_TS,
    )
    base.update(kw)
    row = _S.Statement(**base)
    row.validate()
    with st.tx("statements", actor="test", note="secretary_pending") as tx:
        tx.upsert("statements", row.to_dict(), note="secretary_pending")


def test_pending_inbox_lists_the_own_result_without_proof(tmp_path: pathlib.Path):
    """判据（F-05 消费端 · 负控）：`own_result` 无 `proof_text` 必须被列出。

    条目只来自既有标记（`bits` 缺位 / `proof_text` 空 / `quote_verified is None` 过窗口），
    不许新造字段或词表；接手方从声明派生（`capabilities.WRITE_SETS` ⇒ `statements` 的写者是 B）。
    """
    sec = _sec()
    st = _mk_store(tmp_path)
    _stmt_row(st, "0001", origin="own_result", proof_text="", source_lit_id=None,
              quote_verified=None, quote_reason="证明还没做完")
    s = sec.Secretary("B", root=st.root, store=st)
    got = s.pending_inbox(window_sec=0)
    kinds = {i["kind"] for i in got["items"]}
    assert got["checked"] is True and got["count"] >= 1, got
    assert "missing_proof" in kinds, got
    proof = [i for i in got["items"] if i["kind"] == "missing_proof"][0]
    assert proof["id"] == "0001" and proof["missing"] == "proof_text", proof
    assert proof["who"] == "B" and proof["quote_reason"] == "证明还没做完", proof
    # 逐条落台账（只记录，不写库表）
    assert s.decisions() and s.decisions()[-1]["duty"] == 3, s.decisions()[-1]
    # 全局口径（M 的秘书）看得到同一行
    m = sec.Secretary("M", root=st.root, store=st)
    assert m.pending_inbox(scope="global", window_sec=0)["count"] >= 1


def test_pending_inbox_does_not_list_a_complete_row(tmp_path: pathlib.Path):
    """负控（防"什么都往里塞"的假阳性）：证据齐全的行必须不列。"""
    from agentflow import evidencebits as EB

    sec = _sec()
    st = _mk_store(tmp_path)
    # 五元位全部已定（`na` = 问过了、不适用 ⇒ 不是待办），且各自的伴随凭据齐全
    # （`bits_of` 是位的唯一构造处，所以夹具也走它 —— 手写一份会与判据漂移）。
    full_bits = EB.bits_of(
        numeric="na", numeric_reason="不适用：纯组合论证",
        proof="正文", proof_process="逐步论证见附录 A",
        reviewed={"verdict": "verified"}, reviewed_by={"verdict": "verified", "by": "V"},
        formal="na", formal_reason="不适用：不形式化",
        audited={"round": 1, "verdict": "pass"},
        audited_by={"round": 1, "verdict": "pass", "by": "H"},
        origin="own_result", quote_verified=True,
    )
    _stmt_row(st, "0002", origin="own_result", proof_text="证明：见附录 A。",
              quote_verified=True, quote_reason="逐字比对一致", bits=full_bits)
    s = sec.Secretary("B", root=st.root, store=st)
    got = s.pending_inbox(window_sec=0)
    assert got["checked"] is True, got
    assert [i for i in got["items"] if i["id"] == "0002"] == [], got
    # 读不成 ⇒ 如实报"没读成"，不当成"没有待办"
    class _Broken:
        root = st.root

        def rows(self, table):
            raise OSError("表读不出来")

    bad = sec.Secretary("B", root=st.root, store=_Broken())
    broken = bad.pending_inbox()
    assert broken["checked"] is False and "读不出来" in broken["reason"], broken
    assert bad.pending_inbox(scope="nonsense")["checked"] is False


def _schema_allows_own_result_without_proof() -> bool:
    """B 的 schema 半落了吗（`schema.Statement.validate` 还拦不拦 `own_result` 无证明）。"""
    from agentflow import schema as _S

    try:
        _S.Statement(stmt_id="0000", origin="own_result", kind="theorem", label="L",
                     statement_text="t", statement_full="t", proof_text="",
                     source_lit_id=None, quote_verified=None, quote_reason="证明还没做完",
                     evidence_kind="heuristic", status="active",
                     created_at="2026-01-01T00:00:00+00:00", bits={}).validate()
    except ValueError:
        return False
    return True


@pytest.mark.skipif(not _schema_allows_own_result_without_proof(),
                    reason="硬顺序（主控裁定）：等 B 先删 schema.py 的 own_result raise，"
                           "再由 A 线改写入口 —— 先改写入口那一笔会在事务里抛")
def test_register_statement_marks_a_missing_proof_instead_of_refusing(tmp_path: pathlib.Path):
    """F-05 的生产端写入口（主控裁定）：`own_result` 无证明 ⇒ 落库 + 如实标记，不拦。

    判据四件：① 不再 `_refuse`；② 行真的落库；③ `proof_text` 留空、`quote_verified=None`
    且 `quote_reason` 写明"证明还没做完/未核到"；④ 等级现算是"猜想"而不是证明级
    （`evidencebits.derive_grade` 是唯一的等级来源，不许落盘一份自报等级）。

     本条当前被 gate 住（`skipif`）：它依赖 B 先删 `schema.py` 里那条 raise
    （硬顺序）。gate 是"这一格没查成"，不是绿 —— 交付说明里如实标注。
    """
    from agentflow import evidencebits as EB
    from agentflow.agent_b import AgentB
    from agentflow.store import Store

    st = Store(tmp_path / "ws")
    st.init()

    class _NoExtract:
        def extract(self, doc, lit_id, meta):
            return [], []

    b = AgentB(st, extractor=_NoExtract(), extract_text=lambda *a, **k: "", config={})
    out = b.register_statement(
        statement_full="设 G 是有限连通图，则 X_n 的极限是正态", kind="theorem",
        label="Conjecture 1.1", statement_text="X_n 的极限是正态",
        origin="own_result", doc_id="0000", proof_text="",
        quote_verified=None, quote_reason="证明还没做完（推到第 3 步卡住）",
    )
    assert out.get("ok") is True, out
    assert out.get("refusal_reason") is None and out.get("kind") != "missing_proof_text", out
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    row = rows[0]
    assert str(row.get("proof_text") or "") == "", row
    assert row.get("quote_verified") is None and str(row.get("quote_reason") or ""), row
    assert EB.derive_grade(row.get("bits") or {}) == "conjecture", row.get("bits")


def test_every_role_can_get_its_own_secretary(tmp_path: pathlib.Path):
    """判据（`draft/53` §5 第 3 步：批量给 A-H 装 = 配置 + 每角色一条测试）。

    同一个类、每角色一份配置：台账不混写、行里的 `sender` 是被服务的那名角色、
    定位面读得到（组织图全开）、写集 = 命题写入代理的两张表。

    写集那一格 2026-10-09 改了口径（业主：「写入侧应该都是B的活，让B的秘书帮它洗格式、
    拿编号、改表、查重，即B不直接用增工具，秘书实际操作增、改…查工具，B纯粹负责消化理解」）：
    它此前断言 `writes == frozenset()`（"秘书不写任何库表"），而业主把那件事反过来了。
    改成"写集恒等于 `STATEMENT_WRITE_TABLES`"，并在同一断言里钉住它不是空集 ——
    空集会让"秘书有没有写集"这句声明退化成没有内容（这次改动的反真空）。
    契约那一半（谁都可以拿秘书、台账不混写）逐字不变。
    """
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    roles = list(S.ROLES) + ["M"]
    for i, role in enumerate(roles):
        s = sec.for_role(role, root=root)
        assert s.role == role and s.writes == frozenset(sec.STATEMENT_WRITE_TABLES), role
        assert s.writes, f"{role} 的写集是空的 ⇒ 这条声明没有内容（B 的写入代理要落两张表）"
        assert s.knowledge()["briefs"], f"{role} 的定位面读不到"
        rec = s.handoff_add(to="M" if role != "M" else "D", summary=f"{role} 的交接",
                            body=f"{role} 干完了这一步。")
        assert rec["sender"] == role, (role, rec)
        assert rec["id"] == S.format_id(i), (role, rec["id"])
        assert sec.decisions_path(root, role).is_file(), role
    # 每角色一份：文件数 = 角色数（不许混写，也不许多写）
    written = sorted(p.name for p in (root / "out" / "secretary").glob("*.jsonl"))
    assert written == sorted(f"{r}.jsonl" for r in roles), written


def test_conductor_surfaces_same_key_terminal_rows(tmp_path: pathlib.Path):
    """判据（验收 ② 的机器半）：同 `(role, action, input_key)` 的既有终态行摆到派活前。"""
    st = _mk_store(tmp_path)
    cond = _cond(st)
    r1 = cond.summon("C", "hottest", {"top_n": 5}, by="M", input_key="k1")
    assert r1.status == "done", r1
    got = cond.duplicate_candidates("C", "hottest", "k1")
    assert [r["task_id"] for r in got] == [r1.task_id], got
    # 不同 key / 不同动作 ⇒ 不算重复（不许把"另一件事"读成重复）
    assert cond.duplicate_candidates("C", "hottest", "k2") == []
    assert cond.duplicate_candidates("C", "cold", "k1") == []


def test_conductor_refusal_writes_the_task_end_narrative(tmp_path: pathlib.Path):
    """判据（E-03 的机器半 / `draft/53` §10）：拒绝也必须写 `task_end`。

    真机基线：refused 905 行里 361 行没有 `task_end` —— "留痕" ≠ "被处理"，
    而"没有叙事"连"留痕"都不是。
    """
    st = _mk_store(tmp_path)
    cond = _cond(st)
    r = cond.summon("C", "hottest", {"top_n": 5}, by="M", input_key="k1")
    events, problems = SESS.read_session(st.root)
    assert not problems, problems
    ends = [e for e in events if e.get("kind") == "task_end" and e.get("task_id") == r.task_id]
    assert ends, [e.get("kind") for e in events]
    assert ends[0]["outcome"] == r.outcome and ends[0]["refusal_reason"], ends


def test_scheduler_lineage_default_is_none_so_ancestry_is_rebuilt():
    """判据（F1 血缘 / `44 J-32`）：`TaskCall.lineage` 缺省 `()` 会让 `cycle` 判据不可达。

    验收 ③：`lineage=()` 时 `cycle` 判据不可达（红）。修法：缺省 `None` ⇒
    `Conductor` 从 `tasks` 表重建祖先链（台账是权威来源）。
    """
    from agentflow import scheduler as SChed

    call = SChed.TaskCall(role="C", action="hottest")
    assert call.lineage is None, "缺省 () ⇒ Conductor 收到空链 ⇒ cycle 判据永远不可达"

    got: dict[str, Any] = {}

    class _Cap:
        def summon(self, role, action, params, **kw):
            got.update(kw)
            return None

    sem = threading.Semaphore(1)
    SChed._guarded(call, conductor=_Cap(), token=_SC_cancel_token(),
                   sem=sem, probe=SChed.ConcurrencyProbe())
    assert got["lineage"] is None, got


def _SC_cancel_token():
    from agentflow.cancellation import CancelToken

    return CancelToken()


def test_wrong_tool_name_lists_parallel_candidates_and_never_rewrites():
    """判据（L-05h 的机器半 / `draft/55` §3.2）：错名 ⇒ 并列候选，不自动改写。"""
    from agentflow.tools import base as B

    reg = B.ToolRegistry()
    reg.register(B.ToolSpec(name="fs.read", summary="读文件",
                            params={"type": "object", "properties": {}},
                            handler=lambda **kw: B.ok({}), roles=("D",)))
    # writers 子注册表里的那批（`review_tools.register(include_writers=True)` 装进来的）
    reg.register(B.ToolSpec(name="review.report", summary="落 findings",
                            params={"type": "object", "properties": {}},
                            handler=lambda **kw: B.ok({}), roles=("H",)))
    with pytest.raises(B.ToolError) as e1:
        reg.get("fs.raed")
    msg = str(e1.value)
    assert "fs.read" in msg, f"错名没给并列候选：{msg}"
    assert "候选" in msg and "不自动改写" in msg, msg
    with pytest.raises(B.ToolError) as e2:
        reg.get("review.reportt")
    assert "review.report" in str(e2.value), str(e2.value)


def test_budget_is_recorded_and_does_not_block(tmp_path: pathlib.Path):
    """判据（F2 / E-02）：预算字段的记录（不阻断）——记录得到、判决不因此改变。

     2026-10-15 业主裁定 A7：读数里只剩钱（`usd_budget` / `usd_left`），
    `token_budget` / `tokens_left` 两格已删；`spent_tokens` 留着当读数。
    """
    from agentflow import policy as P

    st = _mk_store(tmp_path)
    cond = _cond(st, policy=P.Policy(usd_budget=1.0))
    r = cond.summon("C", "hottest", {"top_n": 5}, by="M", input_key="k1")
    assert r.outcome == "refused" and r.refusal_reason == "not_wired", r
    note = cond.budget_note()
    assert note["usd_budget"] == 1.0, note
    assert note["usd_left"] is not None and note["spent_tokens"] == 0, note
    assert "token_budget" not in note and "tokens_left" not in note, note
    assert note["recorded_only"] is True, note


# ================================================================ 4 停机判据


def test_running_loops_balances_roles_and_ignores_refused_resume(tmp_path: pathlib.Path):
    """判据（E-13）：`running_loops` 按角色配平 + 排除 `resume_refused`（假阳性）。"""
    root = tmp_path / "ws"
    root.mkdir()
    SESS.append(root, {"kind": "agent_run_start", "role": "M"}, sid="s1")
    SESS.append(root, {"kind": "agent_run_start", "role": "C"}, sid="s1")
    SESS.append(root, {"kind": "agent_run_end", "role": "M"}, sid="s1")
    SESS.append(root, {"kind": "agent_run_start", "role": "D", "resume_refused": "no_checkpoint"},
                sid="s2")
    got = SC.running_loops(root)
    roles = sorted(str(r["role"]) for r in got["running"])
    assert roles == ["C"], f"没有按角色配平、或把被拒的续跑算成在跑：{got}"


# ================================================================ 5 CLI 卫生


def test_cli_dropped_the_research_subcommand_and_the_old_menu_wording() -> None:
    """判据（F4 / L-04b / L-04h）：删 `research` 子命令 + `MENU` 旧措辞。"""
    from agentflow import cli

    text = "\n".join(t for _k, t, _f in cli.MENU)
    assert "本地书架" not in text, f"MENU 还留着图书馆时代的措辞：{text}"
    parser = cli.build_parser()
    sub = next(a for a in parser._subparsers._group_actions if a.choices)  # type: ignore[attr-defined]
    assert "research" not in sub.choices, sorted(sub.choices)
    assert not hasattr(cli, "cmd_research"), "research 子命令的处理函数还在"
# ------------------------------------------- R7-⑭：两条"直接补测试"（各自一条直接判据）

def test_rework_inbound_runs_through_the_inbound_hook(tmp_path: pathlib.Path):
    """`R7-⑭` ①：收件加工这条路真的被走到（不是"顺带被别处覆盖"）。

    生产入口只有一处：`AgentLoop._inbound_hook()`（`agent_loop.py:2506`）—— 本体在
    `heard` 非空时把每条新消息交给 `secretary.rework_inbound`。这条用例从那个入口
    进去，逐条钉产物：补的是本角色定位（不加码不减码）、原文一字不动、台账留 duty=4。
    改前（`R2b-⑲` 之前）这条路的生产面是 0（只有 `selftest` 提到它）。
    """
    st, sec, loop = _loop_with_secretary(tmp_path, role="D")
    heard = [{"sender": "M", "body": "把这件事做了"}]
    out = loop._inbound_hook(heard)

    reworked = out.get("reworked")
    assert isinstance(reworked, list) and len(reworked) == 1, out
    one = reworked[0]
    assert one["fail_open"] is False and one["problem"] == "", one
    assert one["item"] == heard[0], "原文一字不动（不加码不减码）"
    add = str(one["addendum"])
    assert add, one
    # 钉的是"补的确实是本角色当前的产出物口径"，不是某个写死的表名：
    # 2026-10-10 那条 D 的交付物声明从 `analysis_reports`（C 的报告通道、D 写不了）
    # 改成它真交付的东西之后，写死表名的那一版当场红了 —— 判据要比的东西是声明本身。
    from agentflow import capabilities as _C

    _deliverable = _C._specs.builtin_specs()["D"].brief.deliverable
    assert _deliverable in add, f"补的该是本角色（D）的产出物口径：{add}"
    assert "研究循环" in add, f"还该补它在条线上的位置（duty 那一句）：{add}"

    last = sec.decisions()[-1]
    assert last["duty"] == 4 and last["kind"] == _sec().KIND_OPTIMIZED, last
    assert last["before"] and last["after"], "原文与加工后要并列留痕（`draft/55` §5.1）"


def test_declarations_candidates_is_one_shared_judgement_used_by_prescreen(tmp_path):
    """    `R7-⑭` ②：`declarations_candidates` 是内部 helper —— 直接钉转发与边界。

    它给谁用（现算：三处引用全在 `secretary.py` 自己内部 `:401` / `:407` / `:624`）：`Secretary.prescreen()`（动作错名 / 工具错名的并列候选）
    与`Secretary.optimize_outbound()`（把候选交给 `judge` 做判断）。它自己不是生产入口，生产路径是 `AgentLoop._outbound_hook` →
    `optimize_outbound` → `prescreen` ⇒下面用"经 prescreen 有没有把候选说出来"给这条路径作证。

    判据只有一份：它必须逐字等于 `tools.base.candidate_tool_names`（`secretary.py:116`的 docstring 就是这条纪律）。不主张「它总能猜到真名」
    ——它给的是并列候选（排过序的近似名），真名在不在候选里由那张表说了算，所以这里只钉"真名出现在候选里"这一档，加上 `limit` 与空真名表两条边界。
    """
    from agentflow.tools import base as B
    from agentflow.tools import build_registry

    names = sorted(build_registry().registry.names())
    for typo in ("table.creat", "manuscripts.red"):
        assert _sec().declarations_candidates(typo, names) == B.candidate_tool_names(typo, names), (
            "转发一旦被重写就会分叉：机器给的候选与秘书给的候选不再是同一批")
    one = _sec().declarations_candidates("table.creat", names, limit=1)
    assert len(one) == 1 and len(_sec().declarations_candidates("table.creat", names)) <= 3, (
        f"`limit` 只管截断（不改变「看起来像哪一个」这件事本身）：{one}")
    assert _sec().declarations_candidates("table.creat", []) == [], (
        "空真名表 ⇒ 没有候选（读不到不是没问题，调用方那一层另行报三态）")
    # 三条判据里的第 1 条（同尾名并列）用一张写死的小表钉住：这张表与注册表无关，
    # 所以它钉的是"规则本身"，不是"当前注册表里恰好有哪些名字"。
    tiny = ["fs.read", "table.read", "review.report", "table.create"]
    same_tail = _sec().declarations_candidates("read", tiny)
    assert "fs.read" in same_tail and "table.read" in same_tail, same_tail
    assert _sec().declarations_candidates("table.creat", tiny, limit=1) == ["table.create"], (
        "尾名/全名近似那一档的小表读数")
    # 反真空：至少有一个"少打一个字母"的错名能把真名列进候选 —— 一个都没有时，
    # 上面那几条等式仍然绿，但它们钉住的就只是"两边都返回 []"，等于什么都没钉。
    sample = next((n for n in names if n[:-1] and n in _sec().declarations_candidates(n[:-1], names)),
                  "")
    assert sample, "这张候选表上一个自造错名都列不出真名 ⇒ 这条判据是真空的（先查候选算法）"

    # 经 prescreen（职责 1 的预筛）走到它：错名必须把并列候选一字不动地说出来
    st, sec, loop = _loop_with_secretary(tmp_path, role="D")
    live = sorted(sec._tool_names())
    want = _sec().declarations_candidates("table.creat", live)
    assert want, "这张真名表上这个错名应当有候选（否则下面那条断言什么都没钉住）"
    alarms = sec.prescreen(to="F", action="", params={}, tool="table.creat")
    assert any(f"并列候选：{want}" in a for a in alarms), alarms
    out = loop._outbound_hook("summon", {"to": "F", "action": "", "params": {},
                                         "name": "table.creat"})
    assert f"并列候选：{want}" in json.dumps(out, ensure_ascii=False), out
# ------------------- R8：结构化交互的收发交秘书接管（出站门 + `message` 分支）
#
# 所有者裁定逐字："如果有些形状涉及到结构化交互，则需要秘书接管。"
# 判据是"这个形状是不是跨智能体的结构化交互" —— 是 ⇒ 必须在出站门里；
# 不是 ⇒ 登记它"谁接住"（不登记就是漏项，形状表与登记表等额）。

STRUCTURED_INTERACTION = {
    "summon": "跨智能体的结构化交互：委托（to/action/params）",
    "summon_many": "同上（一批委托）",
    "handoff": "跨智能体的结构化交互：手稿通道（to/summary/body/revises）",
    "message": "跨智能体的结构化交互：私聊/公共频道（to/subject/body/reply_to + 协作边准入）",
}
NOT_STRUCTURED = {
    "tool": "不是交互：工具面有代码的硬闸（参数表被拒后注入，draft/63 §4-2 的已决定现状）",
    "note": "不是交互：写自己的台账/笔记，代码接住",
    "ask_user": "不是交互（对象是用户，不是智能体）：直接问用户（userio）",
    "final": "不是交互：终态字段闸 `notify_reading`",
    # S1k-2 的两个新形状：它们动的是名册（父与它自己名下子代理的账），不是"跨智能体
    # 结构化交互"那一类 —— 秘书就是执行者（`Secretary.retire` / `roster_view`），
    # 不需要再过一遍"发件前优化"那道门（过门反而会把执行者当成被优化的载荷）。
    "retire": "不是交互：退役由秘书自己执行（Secretary.retire 的三分支）",
    "roster": "不是交互：查名册是只读视图（Secretary.roster_view）",
    # S-H（裁定 14）：叫停走的是停机信号那条路（`Conductor.interrupt_child` +
    # `stopctl` 的一份信号一个目标），不经秘书的"发件前优化"那道门 ——
    # 被叫停的是子代理的当前那一轮，没有任何载荷要优化。
    "interrupt": "不是交互：叫停落在停机信号上（Conductor.interrupt_child）",
}


def _gate_problems(gate) -> list[str]:
    """门元组 ⇒ 问题清单（空 = 与登记表等额）。写成函数才能拿合成输入做负控。"""
    want, got = set(STRUCTURED_INTERACTION), set(gate)
    problems: list[str] = []
    if got - want:
        problems.append(f"门里多了不属于结构化交互的形状：{sorted(got - want)}")
    if want - got:
        problems.append(f"门里少了属于结构化交互的形状：{sorted(want - got)}")
    return problems


def test_the_secretary_outbound_gate_covers_exactly_the_structured_interactions():
    from agentflow import agent_loop as AL

    both = set(STRUCTURED_INTERACTION) | set(NOT_STRUCTURED)
    assert set(AL.SHAPES) == both, (
        f"形状表与登记表不等额 ⇒ 新增/改名了没登记：{sorted(set(AL.SHAPES) ^ both)}")
    assert _gate_problems(AL.SECRETARY_OUTBOUND_SHAPES) == []
    assert set(AL.SECRETARY_OUTBOUND_SHAPES) <= set(AL.SHAPES)


def test_negative_control_the_gate_judge_sees_both_directions():
    """负控：① 把 `message` 从门里去掉 ⇒ 判据必须报"少了"；② 把 `tool` 加进去 ⇒ 必须报"多了"。"""
    without_message = tuple(k for k in STRUCTURED_INTERACTION if k != "message")
    assert any("少了" in p and "message" in p for p in _gate_problems(without_message)), \
        "把 message 从门里去掉都判不出来 ⇒ 这条判据是真空的"
    with_tool = tuple(STRUCTURED_INTERACTION) + ("tool",)
    assert any("多了" in p and "tool" in p for p in _gate_problems(with_tool)), \
        "把 tool 加进门里都判不出来 ⇒ 这条判据是真空的"


def _message_payload(**over) -> dict:
    row = {"to": "#public", "subject": "主题", "body": "正文"}
    row.update(over)
    return row


def test_message_goes_through_the_secretary_gate_and_leaves_a_duty_1_row(tmp_path):
    st, sec, loop = _loop_with_secretary(tmp_path, role="D")
    out = loop._outbound_hook("message", _message_payload())

    assert "alarms" in out, f"message 没进门 ⇒ 秘书没被调用（出站门元组）：{out}"
    assert out["alarms"] == [] and out["fail_open"] is False, out
    assert sec.decisions()[-1]["duty"] == 1, sec.decisions()[-1]
    # 门不是"所有形状都过"：不属于结构化交互的形状不进秘书（反真空）
    assert loop._outbound_hook("tool", _message_payload()) == {}
    assert loop._outbound_hook("note", _message_payload()) == {}


def test_message_without_a_collaboration_edge_is_alarmed_and_refused_by_the_hard_gate(tmp_path):
    from agentflow import agent_loop as AL
    from agentflow import agent_prompts as AP

    role = "D"
    fresh = next(t for t in S.ROLES
                 if t != role and t not in AP.partners_out(role) and role not in AP.partners_out(t))
    st, sec, loop = _loop_with_secretary(tmp_path, role=role)
    payload = _message_payload(to=fresh)

    out = loop._outbound_hook("message", payload)
    assert any("没有协作边" in a for a in out["alarms"]), out
    assert payload == _message_payload(to=fresh), "秘书不许改载荷"
    assert sec.decisions()[-1]["duty"] == 1, sec.decisions()[-1]
    # 硬闸照旧（秘书那一层是"建议 + 台账"，不是替代硬闸）
    res = loop._do_message(payload)
    assert res["ok"] is False and "没有协作边" in res["error"], res
    # 单一来源：秘书报的那句与硬闸那句逐字相同（两处调的是同一个函数）
    assert out["alarms"][0] == res["error"], (out["alarms"][0], res["error"])
    assert AL.message_admission(role, fresh) == res["error"]


def test_a_broken_secretary_cannot_stop_a_message(tmp_path, monkeypatch):
    """反负控：秘书自己抛异常 ⇒ 消息照发 + 台账 `fail_open=True`（不许让秘书挡住发信）。"""
    st, sec, loop = _loop_with_secretary(tmp_path, role="D")

    def boom(*a, **kw):
        raise RuntimeError("秘书炸了")

    # 断在 `message` 那一支自己的预筛上（对 `message` 不再跑 `prescreen` —— 见
    # `optimize_outbound` 里那段"为什么不跑委派预筛"）：这样 fail-open 那条路与
    # 台账行都真的被走到。
    monkeypatch.setattr(sec, "_message_alarms", boom)
    out = loop._outbound_hook("message", _message_payload())
    assert out.get("fail_open") is True, out
    assert sec.decisions()[-1]["duty"] == 1 and sec.decisions()[-1]["fail_open"] is True, \
        sec.decisions()[-1]
    res = loop._do_message(_message_payload())
    assert res["ok"] is True and res["message_sent"], res


def test_message_format_problems_are_alarms_not_blocks(tmp_path):
    """追加要求（所有者）：智能体侧的交互工具不刻意拦格式 —— 缺 `subject` 只报警。

    硬闸只留权限级那一条（协作边 / `#public` / `reply_to`，且走共用判据）；
    格式（`subject`/`body` 空、措辞不好、`to` 不像角色名）一律不许退回或阻断发信。
    """
    st, sec, loop = _loop_with_secretary(tmp_path, role="D")
    payload = _message_payload(subject="")

    out = loop._outbound_hook("message", payload)
    assert any("subject" in a for a in out["alarms"]), out
    assert any("不替它编内容" in a for a in out["alarms"]), out
    assert payload == _message_payload(subject=""), "秘书不许改载荷"
    # 格式缺了照样发得出去（权限级准入没被触发）
    res = loop._do_message(payload)
    assert res["ok"] is True and res["message_sent"], res


def _admission_source_problems(loop_src: str, sec_src: str) -> list[str]:
    """"协作边准入只有一处实现"的判据：扫调用，不扫措辞（docstring 里提一嘴不算）。"""
    import ast as _ast

    def calls(tree) -> int:
        n = 0
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Attribute) and node.attr == "partners_out":
                n += 1
            elif isinstance(node, _ast.Name) and node.id == "partners_out":
                n += 1
        return n

    problems: list[str] = []
    if "def message_admission(" not in loop_src:
        problems.append("`agent_loop.py` 里没有 `message_admission` 的定义 ⇒ 唯一那份判据不见了")
    if calls(_ast.parse(loop_src)) < 1:
        problems.append("`agent_loop.py` 里没有协作边查询 ⇒ 判据被搬走了")
    if calls(_ast.parse(sec_src)) != 0:
        problems.append("`secretary.py` 里出现了协作边查询 ⇒ 第二份准入判据（漂了没有任何东西会红）")
    return problems


def test_the_collaboration_edge_judgement_has_exactly_one_implementation():
    root = pathlib.Path(__file__).resolve().parent.parent
    loop_src = (root / "src/agentflow/agent_loop.py").read_text(encoding="utf-8")
    sec_src = (root / "src/agentflow/secretary.py").read_text(encoding="utf-8")

    assert _admission_source_problems(loop_src, sec_src) == []
    assert "partners_out" not in sec_src, "秘书那一侧连措辞里都不该出现它（免得下次有人照着抄）"


def test_negative_control_a_copied_admission_judgement_is_caught():
    root = pathlib.Path(__file__).resolve().parent.parent
    loop_src = (root / "src/agentflow/agent_loop.py").read_text(encoding="utf-8")
    copied = "def _admission(role, to):\n    return to in AP.partners_out(role)\n"
    assert _admission_source_problems(loop_src, copied), "把内联那份抄回秘书都判不出来 ⇒ 判据是真空的"


def test_the_inbound_hook_reworks_everything_it_hears(tmp_path, monkeypatch):
    """入站半边（本来就有）：收到的每一条都过 `rework_inbound`，摘要那两档三态齐全。"""
    st, sec, loop = _loop_with_secretary(tmp_path, role="D")
    heard = [{"sender": "M", "body": "在吗"}]

    out = loop._inbound_hook(heard)
    assert isinstance(out.get("reworked"), list) and out["reworked"], out
    assert out["reworked"][0]["item"] == heard[0], "收件加工不许改原文"
    assert out["reworked"][0]["addendum"], out["reworked"][0]
    assert "handoffs_digest" in out and "handoffs_digest_problem" not in out, out

    def boom():
        raise RuntimeError("读不到")

    monkeypatch.setattr(sec, "handoffs_digest", boom)
    bad = loop._inbound_hook(heard)
    assert "handoffs_digest_problem" in bad and "handoffs_digest" not in bad, bad
    assert loop._inbound_hook([]) == {}, "没有新消息时钩子是 no-op"


# ================================================================ 5 入库审美（业主 2026-10-14 第 12 条前半）


def _canned(payload: dict):
    """固定回一个 JSON 的替身缝（不联网、不记账、不落会话）。"""

    class _Canned:
        def __init__(self) -> None:
            self.payload = dict(payload)
            self.prompts: list[str] = []

        def ask_json(self, prompt, **kw):
            import types as _t

            self.prompts.append(str(prompt))
            return dict(self.payload), _t.SimpleNamespace(ok=True, problem="", detail="")

    return _Canned()


def test_the_aesthetic_verdict_and_the_delegation_verdict_are_two_vocabularies(tmp_path):
    """两根轴的词表不许互相串（`JUDGE_VERDICTS` 是唯一一处定义）。

    为什么这条值得单判：把「太平凡」写进派活那一栏（或反过来把「可派」写进审美那一栏），
    下游读的是同一个 `decision` 字段而没有任何地方会报错 ——
    这与本仓"同一件事两个名字"的老毛病同族。所以每一类只认自己那张词表。
    """
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    # ① 审美那一类收到派活轴的结论 ⇒ 不采信
    s1 = sec.Secretary("B", root=root, seam=_canned({"decision": "建议不派", "reason": "x"}),
                       enable_model=True)
    got1 = s1.judge("statement_aesthetic", {"statement_full": "a+b=b+a"})
    assert got1["checked"] is False and "建议不派" in got1["reason"], got1
    # ② 派活那一类收到审美轴的结论 ⇒ 同样不采信
    s2 = sec.Secretary("M", root=root, seam=_canned({"decision": "太平凡", "reason": "x"}),
                       enable_model=True)
    got2 = s2.judge("duplicate_retry", {"to": "D"})
    assert got2["checked"] is False and "太平凡" in got2["reason"], got2
    # ③ 各回各的 ⇒ 都采信（反真空：不是"一律不采信"）
    s3 = sec.Secretary("B", root=root, seam=_canned({"decision": "太平凡", "reason": "两条都答不上"}),
                       enable_model=True)
    got3 = s3.judge("statement_aesthetic", {"statement_full": "a+b=b+a"})
    assert got3["checked"] is True and got3["decision"] == "太平凡", got3
    assert set(sec.STATEMENT_VERDICTS) == {"合格", "太平凡", "判不了"}
    assert "太平凡" not in sec.DECISIONS, "审美轴的结论不许混进派活那一栏"


def test_the_statement_judgement_belongs_to_B_only(tmp_path):
    """这一问只属于 B 的秘书：别的角色的秘书调用它 ⇒ `checked=False` + 说清为什么。

    三态纪律的另一面：不是 B ⇒ 不是"合格"，是"这一格没查成"（缺理由的放行会被读成通过）。
    """
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()
    a = sec.Secretary("A", root=root, seam=_canned({"decision": "合格", "reason": "有用"}),
                      enable_model=True)
    got = a.judge_statement(statement_full="某定理")
    assert got["checked"] is False and "B" in got["reason"], got
    b = sec.Secretary("B", root=root, seam=_canned({"decision": "合格", "reason": "有用"}),
                      enable_model=True)
    ok = b.judge_statement(statement_full="某定理", basis_hint="L3 要用")
    assert ok["checked"] is True and ok["decision"] == "合格", ok


def test_the_filing_gate_refuses_only_on_too_trivial(tmp_path):
    """入库口那一道闸：只有「判了 + 判的是太平凡」才拦（其余一律放行）。

    六个放行档逐个过一遍：合格 / 判不了 / 没查成 / 不是 B / 不是入库那件工具 / 没秘书。
    把它们折成"拦或不拦"两种结局是这一格最容易犯的错 —— 那会让"这一格没查成"决定产出入库。
    """
    import types

    from agentflow.agent_loop import AgentLoop

    def gate(role, secretary, name="own.register_statement"):
        return AgentLoop._statement_filing_refusal(
            types.SimpleNamespace(role=role, secretary=secretary, my_task_id="t-000001"),
            name, {"statement_full": "a+b=b+a"})

    class _Sec:
        def __init__(self, out):
            self.out = out

        def judge_statement(self, **kw):
            return self.out

    refused = gate("B", _Sec({"checked": True, "decision": "太平凡", "reason": "两条都答不上"}))
    assert refused is not None and refused["ok"] is False, refused
    assert refused["kind"] == "statement_too_trivial", refused
    assert "太平凡" in refused["error"] and "最接近的那一条" in refused["error"], refused
    assert refused["secretary"]["decision"] == "太平凡", refused
    for label, args in (
        ("合格", ("B", _Sec({"checked": True, "decision": "合格"}))),
        ("判不了", ("B", _Sec({"checked": True, "decision": "判不了"}))),
        ("没查成", ("B", _Sec({"checked": False, "reason": "没有缝"}))),
        ("不是 B", ("A", _Sec({"checked": True, "decision": "太平凡"}))),
        ("不是入库那件工具", ("B", _Sec({"checked": True, "decision": "太平凡"}))),
        ("没秘书", ("B", None)),
    ):
        if label == "不是入库那件工具":
            assert gate(args[0], args[1], name="table.create") is None, label
        else:
            assert gate(*args) is None, label


def test_the_filing_gate_is_fail_open_when_the_judgement_explodes(tmp_path):
    """判断炸了 ⇒ 不拦（fail-open），但必须留痕：秘书台账里要有一行说清这一格没查成。

    为什么不是"炸了就拦"：拦下来等于让"没查成"决定产出（三态纪律）；而静默放行又会让
    "秘书这趟根本没工作"永远查不出来。所以走 fail-open + 留痕这一对。
    """
    import types

    from agentflow.agent_loop import AgentLoop

    rows: list[dict] = []

    class _Boom:
        def judge_statement(self, **kw):
            raise RuntimeError("缝炸了")

        def note_decision(self, **kw):
            rows.append(dict(kw))
            return {}

    got = AgentLoop._statement_filing_refusal(
        types.SimpleNamespace(role="B", secretary=_Boom(), my_task_id="t-000001"),
        "own.register_statement", {"statement_full": "a+b=b+a"})
    assert got is None, "判断炸了不该把入库这条路堵死（fail-open）"
    assert rows, "fail-open 不等于静默：秘书台账里必须有这一格的一行"
    assert "缝炸了" in rows[0]["reason"] and rows[0]["fail_open"] is True, rows[0]


def test_the_judge_prompt_names_that_kinds_own_vocabulary(tmp_path):
    """提示词说的词表 = 校验认的词表（2026-10-14 真机读数）。

    真机上一次就现形：加 `statement_aesthetic` 那一类时，`judge()` 的校验换成了按类别取，
    而 `_judge_prompt` 的抬头仍写着 `DECISIONS`（派活那一轴）。于是 B 的秘书被问
    「这条命题太平凡吗」，它照提示词答了 `建议不派`，然后被校验层判「不在词表里 ⇒ 不采信」——
    两处各写一份词表，提示词说的与判据认的不是同一张，而两边都自洽。

    判据要两个方向都验：这一类自己的词表在、另一轴的词表不在。
    """
    sec = _sec()
    aesthetic = sec._judge_prompt("statement_aesthetic", {"statement_full": "x"})
    for word in sec.STATEMENT_VERDICTS:
        assert word in aesthetic, (word, aesthetic[:200])
    assert "建议不派" not in aesthetic, "派活那一轴的词混进了审美的提示词"
    delegation = sec._judge_prompt("duplicate_retry", {})
    assert "建议不派" in delegation, "派活那一轴的提示词丢了词表"
    assert "太平凡" not in delegation, "审美那一轴的词混进了派活的提示词"
    # 反真空：每一类都必须能在提示词里读到它自己的词表
    for kind, verdicts in sec.JUDGE_VERDICTS.items():
        text = sec._judge_prompt(kind, {})
        assert all(v in text for v in verdicts), (kind, text[:200])


def test_the_same_statement_is_not_judged_twice(tmp_path):
    """同一个命题只判一次：第二次沿用（不花钱、结论逐字相同），换文本才再判一次。

    2026-10-14 第五趟真机读数：同一份 21 字的 `statement_full` 被提交了 6 次，
    每一次都发了一次模型调用、都得到同一个「太平凡」，一次 run 因此烧掉 26 次调用里的 20 次
    与 $0.226，而 `statements` 仍是 0 行。判断的对象只有那段文本（加一句自证不平凡的说明），
    所以同题再问一遍不会有别的结论 —— 记下来，省掉那几次调用。

    负控（三态那一条）：没查成不许缓存 —— 把"这一次没查成"变成"以后都别查了"，
    等于让一次超时永久关掉一道门；缝好起来之后必须还能真判。
    """
    sec = _sec()
    root = tmp_path / "ws"
    root.mkdir()

    class _Counting:
        def __init__(self, payload):
            self.payload = payload
            self.calls = 0

        def ask_json(self, prompt, **kw):
            import types as _t

            self.calls += 1
            return dict(self.payload), _t.SimpleNamespace(ok=True, problem="", detail="")

    # ① 同一份文本问两次 ⇒ 只花一次调用，第二次标 reused 且结论逐字相同
    seam = _Counting({"decision": "太平凡", "reason": "两条依据都缺", "basis": ["x"]})
    s = sec.Secretary("B", root=root, seam=seam, enable_model=True)
    first = s.judge_statement(statement_full="对任意正整数 n，n^2+n 一定是偶数。")
    second = s.judge_statement(statement_full="对任意正整数 n，n^2+n 一定是偶数。")
    assert first["checked"] is True and first["decision"] == "太平凡", first
    assert seam.calls == 1, f"同一个命题被真问了 {seam.calls} 次"
    assert second["decision"] == first["decision"] and second.get("reused") is True, second
    assert second["reason"] == first["reason"], second
    assert second["cost"]["ledger"] == "", "沿用那一次不该记成花了钱"
    # 台账里要留一行说清是沿用（读数不许静默）
    rows = [json.loads(x) for x in s.decisions_path().read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any("沿用" in str(r.get("reason") or "") for r in rows), rows[-2:]

    # ② 换了文本（或补上判据）⇒ 那是新的一次判断，必须真问
    third = s.judge_statement(statement_full="对任意正整数 n，n^2+n 一定是偶数。",
                              basis_hint="判据①：L3 那一步要用到它。")
    assert seam.calls == 2, f"换了文本却没再问（calls={seam.calls}）"
    assert third.get("reused") is None, third

    # ③ 负控（三态）：没查成的不许被记住
    class _Boom:
        def ask_json(self, prompt, **kw):
            raise RuntimeError("缝炸了")

    s2 = sec.Secretary("B", root=root / "two", seam=_Boom(), enable_model=True)
    (root / "two").mkdir()
    miss = s2.judge_statement(statement_full="同一条")
    assert miss["checked"] is False, miss
    assert not s2._statement_verdicts, "没查成的结论被缓存了（等于一次超时永久关掉这道门）"
    ok_seam = _Counting({"decision": "合格", "reason": "有用", "basis": ["L3"]})
    s2.seam = ok_seam
    again = s2.judge_statement(statement_full="同一条")
    assert again["checked"] is True and ok_seam.calls == 1, again


def test_the_filing_refusal_says_the_same_statement_will_get_the_same_answer(tmp_path):
    """拦下来的那句话必须写明原样再交一遍不会有别的结论（真机上一次 run 白烧 20 次调用）。"""
    import types

    from agentflow.agent_loop import AgentLoop

    class _Sec:
        def judge_statement(self, **kw):
            return {"checked": True, "decision": "太平凡", "reason": "两条判据都答不上",
                    "basis": [], "reused": True}

    got = AgentLoop._statement_filing_refusal(
        types.SimpleNamespace(role="B", secretary=_Sec(), my_task_id="t-1"),
        "own.register_statement", {"statement_full": "x"})
    assert got is not None and got["kind"] == "statement_too_trivial", got
    assert "原样再交一次不会有别的结论" in got["error"], got["error"]
    assert got["secretary"]["reused"] is True, got


# ---------------------------------------------------------------- 封野路（2026-10-19 晚）


def test_the_two_tables_are_named_the_same_in_both_places():
    """"这两张表只经秘书"这句声明有两处落点，清单必须逐字一致（反漂移）。

    为什么这条判据必须存在：`secretary.STATEMENT_WRITE_TABLES` 是"秘书的写集声明"，
    `store.STATEMENT_WRITE_TABLES` 是"通用写口的禁区"（`store.direct_write_refusal`
    读它）。`store` 在依赖图最底层、不能 import `secretary` ⇒ 清单只能有两处；
    而两处一旦漂了，会出现最坏的那种形态：一张表被两边都认为不归自己管
    （秘书不写它、通用写口也不拒它）—— 于是野路重新打开，而没有任何一条测试变红。
    """
    from agentflow import secretary as SEC
    from agentflow import store as store_mod

    assert tuple(store_mod.STATEMENT_WRITE_TABLES) == tuple(SEC.STATEMENT_WRITE_TABLES), (
        store_mod.STATEMENT_WRITE_TABLES, SEC.STATEMENT_WRITE_TABLES)
    # 反真空：清单不能是空的（空集让上面那条恒真，也让"禁区"一个表都不禁）
    assert len(store_mod.STATEMENT_WRITE_TABLES) == 2, store_mod.STATEMENT_WRITE_TABLES


def test_the_direct_write_refusal_speaks_for_exactly_those_two_tables():
    """`store.direct_write_refusal` 只拒那两张表，且拒信逐字指路（含"删除不受限"）。"""
    from agentflow import store as store_mod

    for table in ("statements", "dependencies"):
        why = store_mod.direct_write_refusal(table)
        assert why.startswith(store_mod.DIRECT_WRITE_REFUSED), why
        assert "Secretary.record_statement" in why, why
        assert "own.register_statement" in why, why
        assert "table.delete" in why, why
    for table in ("literature", "relations", "tasks", "counters", ""):
        assert store_mod.direct_write_refusal(table) == "", table

