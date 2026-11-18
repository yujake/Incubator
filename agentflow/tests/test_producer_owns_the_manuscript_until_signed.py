# -*- coding: utf-8 -*-
"""业主 2026-11-18 裁定：「谁写稿，谁就对稿负责」—— 送审责任从角色 F 泛化到产出者。

## 缺口（79cb25a0 只覆盖 F）

`agent_loop._manuscript_pending` 改前第一句就是 `if str(self.role) != "F": return`，
于是「已登记、V 签还没到」这一条只对 F 生效：E 的 `reports/e-proof-*.md`、B 写的
`reports/b-proof-*.md` 若已登记未送审，它们的产出者照样可以挂机（本文件 b/c
改前红的就是这一格）。「谁写稿，谁就对稿负责」要求判定依据是这份稿是谁写的，
不是角色字面量。

## 产出者从哪一格读出来

1. 台账里的生产者字段：`ARTIFACTS.jsonl` 的 `producer`（`artifacts.owners_of`，
   取最后一条登记）—— 这是"谁把这份稿登记进盘"的直接记录；
2. 没有台账行时退回稿族：`manuscriptproducers.producer_of(rel)["producer_role"]`
   （事实来源是路径的族前缀，`PRODUCER_OF_FAMILY` 是唯一映射表）；
3. 两个都没有 ⇒ `producer_role=""`，这一份不进任何角色的待办（不猜）。

「已登记」也有两路证据：稿头元信息（`proofregistry.parse_entry` 的 `checked`，
F/B 写）或产物台账那一行（E 的 `exhaustionreport.land_manuscript` 只登记台账、
稿头不带 `- 版本：`）。改前只有一个 `parse_entry` 口径 ⇒ E 的稿永远读成"草稿"。

## 判据（a–f）

a. F 名下的已登记未签稿 ⇒ 原行为保持（`_pending_work.busy` / 不许 park；79cb25a0
   的 9 条判据见 `tests/test_f_registered_unsigned_is_pending.py`，本文件只回归这一格）。
b. E 名下的已登记未签稿 ⇒ E 也不许挂机（改前红：只有 F 生效）。
c. B 名下的已登记未签稿 ⇒ 同上（改前红）。
d. 负控三档：d1 盘上没有 `reports/`；d2 只有草稿（未登记）；d3 已登记且已签
   ⇒ 三个产出者都照旧可以挂机（不许把正常挂机堵死）。
e. 负控：不属于产出者的角色（A/C/G/H/M）不因这一条被拦（防误伤）。
f. 反真空：把 ① 的产出者判定打回 hard-code `"F"` ⇒ b/c 必红。

## 读数要逐份点名（判据 b/c 里断言）

`_pending_work.manuscripts` 每份带：稿路径 + 正文 sha + 等待时长（`waiting_sec` /
`waiting_text`，唯一取时口 `clock.now()`）+ `next_action`（summon 形状：`role="V"`，
点这份稿）。等待时长从登记时刻算：稿头 `- 登记时间：` 或台账那一行的 `at`。

边界：全部 tmp 工作区、假时钟，零真实模型调用、不碰 `projects/`。
"""
from __future__ import annotations

import pathlib
import types
from typing import Any, Mapping, Sequence

import pytest

from _credential_fixture import issue_credential
from agentflow import artifacts as A
from agentflow import clock as CLK
from agentflow import proofregistry as PR
from agentflow import researchpending as RP
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

AT = "2026-11-18T10:02:18+08:00"
#: 假时钟的"现在"：比 `AT` 晚 1800 秒（等待时长逐秒可断言）。
NOW = "2026-11-18T10:32:18+08:00"
WAIT_SEC = 1800
SID = "probe-producer-owns-the-manuscript"
TASK = "谁写稿，谁就对稿负责"

#: 产出者 ⇒ 它自己那一族（唯一来源是 `manuscriptopen.ROLE_FAMILIES`）。
PRODUCERS: dict[str, str] = {"F": "f-proof", "E": "e-proof", "B": "b-proof"}
#: 不产出手稿的角色（负控：不因这一条被拦）。
NON_PRODUCERS: tuple[str, ...] = ("A", "C", "G", "H", "M")
BODY = "1. 取 ε>0，按定义逐点验证。（前提）"


def _body_of(role: str) -> str:
    """每族一份不同的正文：签按正文 sha 分文件，三族同文会互相借光。"""
    return f"{BODY}（{role} 的稿）"


# ---------------------------------------------------------------- 夹具


@pytest.fixture()
def bench():
    """假时钟：等待时长可逐秒断言；挂机那一拍不真睡。"""
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    CLK.reset_programs()
    fake = CLK.use(CLK.FakeClock(wall=NOW, monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    build_registry(store=st, conductor=cond, workspace_root=ws)
    return st, cond, ws


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, role: str) -> AgentLoop:
    me = cond.open_top_level_run(role, TASK)
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role=role, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=role, session_root=ws, gateway=None,
                                  price=(0.0, 0.0), sid=f"{SID}-{role}"),
                     store=st, sid=f"{SID}-{role}", max_steps=4,
                     workspace_root=str(ws), my_task_id=me)


def _child_task(cond: Conductor, parent: str) -> str:
    """名册里一条真任务（`clock.start_timer(wait_for="task:…")` 要能解析到它）。"""
    return cond._write_new_row({
        "task_id": "", "role": "E", "action": "run_once", "called_by": "F",
        "parent_task_id": parent, "depth": 2, "input_key": "producer@E",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "", "detail": "夹具子代理", "error": None,
        "started_at": AT, "ended_at": None, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="test:child")


def _mailbox(*, msg_ids: Sequence[str] = (), item_ids: Sequence[str] = (),
             wake_ids: Sequence[str] = ()) -> dict[str, Any]:
    return {"msg_ids": list(msg_ids), "item_ids": list(item_ids),
            "wake_ids": list(wake_ids), "children": {"settled": []},
            "messages": [], "items": []}


def _run_obj() -> Any:
    return types.SimpleNamespace(park={}, notes=[], summons=[], messages_sent=[],
                                 steps=[], handed_off=None)


def _write_manuscript(ws: pathlib.Path, *, role: str, mid: str = "000001",
                      registered: bool = True, ledger: str | None = None
                      ) -> tuple[str, str]:
    """落一份某角色那一族的稿。

    `registered=True` 走两路证据之一：F/B 写稿头元信息（`- 正文sha：` / `- 版本：`），
    E 没有那几行（`exhaustionreport.compose_manuscript` 的真实形状）⇒ 只靠台账。
    `ledger` 给了就往 `ARTIFACTS.jsonl` 登记一条（`producer=ledger`）。
    """
    family = PRODUCERS[role]
    prefix = {"f-proof": "f-proof-", "e-proof": "e-proof-",
              "b-proof": "b-proof-"}[family]
    rel = f"reports/{prefix}{mid}.md"
    body = _body_of(role)
    sha = PR.proof_sha(body)
    fp = PR.proposition_fingerprint(f"证明：中心化引理（夹具 {role}-{mid}）")
    head = [f"# {role} 的证明手稿：夹具 {mid}", ""]
    if registered and family != "e-proof":
        if family == "f-proof":
            head.append("- 计划：0000 · 子目标：s1")
        head.extend([f"- 正文sha：{sha}", f"- 命题指纹：{fp}",
                     "- 命题类型：conjecture", f"- 登记时间：{AT}",
                     f"- 标签：夹具 {mid}", f"- 版本：{AT}@{sha}"])
    elif registered:
        # E 的真实稿头：实验号 / 命题 / 命题键 / 程序（没有注册元信息那三行）。
        head.extend([f"- 实验号：exp:{mid}",
                     f"- 命题：证明：中心化引理（夹具 E-{mid}）",
                     f"- 命题键：PK-E-{mid}",
                     "- 程序：code/enum.py（sha256 " + "0" * 64 + "）"])
    text = "\n".join(head) + (
        f"\n\n## 命题\n\n证明：中心化引理（夹具 {role}-{mid}）\n\n"
        f"## 证明\n\n{body}\n\n## 依赖\n\n（自足证明，空表就是声明。）\n")
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if ledger:
        A.record(ws, path=rel, producer=ledger, kind=f"{family}-manuscript",
                 at=AT, note="test:producer-owns")
    return rel, sha


def _parked_timer(cond: Conductor, loop: AgentLoop, ws: pathlib.Path) -> str:
    """挂一条等子任务的计时器：没有 parked waiter 时 `_park_gate` 本来就不会 park。"""
    child = _child_task(cond, loop.my_task_id)
    CLK.start_timer(ws, wait_for=f"task:{child}", task_id=loop.my_task_id,
                    reason="夹具：挂着等子代理")
    return child


def _assert_producer_is_blocked(loop: AgentLoop, *, rel: str, sha: str) -> None:
    """判据 b/c 共用：产出者有已登记未签稿 ⇒ 待办逐份点名、不许挂机。"""
    work = loop._pending_work(_mailbox())
    assert work.get("checked") is True, work
    assert work.get("busy") is True, work
    manuscripts = dict(work.get("manuscripts") or {})
    assert manuscripts.get("checked") is True, manuscripts
    assert int(manuscripts.get("count") or 0) == 1, manuscripts
    assert str(manuscripts.get("producer") or "") == str(loop.role), manuscripts
    items = [dict(x) for x in (manuscripts.get("items") or ())]
    assert len(items) == 1, items
    item = items[0]
    assert str(item.get("manuscript") or "") == rel, item
    assert str(item.get("sha") or "") == sha, item
    assert str(item.get("producer_role") or "") == str(loop.role), item
    assert int(item.get("waiting_sec") or -1) == WAIT_SEC, item
    assert str(item.get("waiting_text") or ""), item
    action = dict(item.get("next_action") or {})
    assert str(action.get("tool") or "") == "framework_summon", action
    assert str(action.get("role") or "") == "V", action
    assert str(action.get("manuscript") or "") == rel, action
    assert rel in str(action.get("task") or ""), action
    # 理由里逐份点名：稿路径 + 正文 sha 前 12 + 等了多久。
    why = str(work.get("why_text") or "")
    assert rel in why, why
    assert sha[:12] in why, why
    assert str(item.get("waiting_text") or "") in why, why
    # 这一拍必须问模型（park 会吞掉「派 V」那一拍）。
    gate = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox())
    assert gate.get("pending_work") is True, gate
    assert gate.get("decision") != "park", gate
    assert gate.get("skip_model") is False, gate


def _assert_park_is_allowed(loop: AgentLoop) -> None:
    """判据 d/e 共用：这一条不成立时照旧可以挂机。"""
    work = loop._pending_work(_mailbox())
    assert work.get("busy") is False, work
    manuscripts = dict(work.get("manuscripts") or {})
    assert int(manuscripts.get("count") or 0) == 0, manuscripts
    gate = loop._park_gate(step=2, run=_run_obj(), mailbox=_mailbox())
    assert gate.get("pending_work") is False, gate
    assert gate.get("decision") == "park", gate
    assert gate.get("skip_model") is True, gate


# ============================================================ a：F 的回归
def test_a_f_is_still_blocked_by_its_own_unsigned_manuscript(tmp_path, bench):
    """a F 名下未签稿 ⇒ 原行为保持（79cb25a0 的 b 条：不许 park）。

    夹具刻意是"只有稿头元信息、没有台账行"的 F 稿 —— 79cb25a0 的判据就是这么造的；
    产出者判定必须还能从稿族读出 F（不能因为改成读台账就把它丢了）。
    """
    st, cond, ws = _ws(tmp_path)
    rel, sha = _write_manuscript(ws, role="F")
    loop = _loop(st, cond, ws, "F")
    _parked_timer(cond, loop, ws)
    _assert_producer_is_blocked(loop, rel=rel, sha=sha)
    # 稿族兜底：没有台账行时产出者来自稿族这一格（不是角色字面量）。
    item = dict((loop._pending_work(_mailbox()).get("manuscripts") or {})["items"][0])
    assert str(item.get("producer_source") or "") == "manuscript_family", item


# ============================================================ b：E
def test_b_e_is_blocked_by_its_own_unsigned_manuscript(tmp_path, bench):
    """b E 名下未签稿 ⇒ E 也不许挂机（改前红：`_manuscript_pending` 只认 role=="F"）。

    E 的稿头没有 `- 版本：`（`exhaustionreport.compose_manuscript` 的真实形状）⇒
    「已登记」只能从产物台账那一行读出来 —— 这一条同时钉住第二路登记证据。
    """
    st, cond, ws = _ws(tmp_path)
    rel, sha = _write_manuscript(ws, role="E", ledger="E")
    loop = _loop(st, cond, ws, "E")
    _parked_timer(cond, loop, ws)
    _assert_producer_is_blocked(loop, rel=rel, sha=sha)
    item = dict((loop._pending_work(_mailbox()).get("manuscripts") or {})["items"][0])
    # 产出者是从台账的 producer 字段读出来的，不是从角色字面量。
    assert str(item.get("producer_source") or "") == "artifacts", item
    # 收工那一半：E 的按签拦收工也要看到它（不许把等签的稿读成可收工）。
    close = loop._v_wait_gate_reading()
    assert close.get("checked") is True, close
    assert close.get("complete") is False, close
    assert "还没收工" in str(close.get("why") or ""), close
    # M 的同一份读数（复用同一个扫描）：E 的这一份也进 `manuscript_unsigned`。
    m_reading = RP.pending_reading(st)
    assert int((m_reading.get("counts") or {}).get("manuscript_unsigned") or 0) == 1, \
        m_reading.get("counts")


# ============================================================ c：B
def test_c_b_is_blocked_by_its_own_unsigned_manuscript(tmp_path, bench):
    """c B 名下未签稿 ⇒ 同上（改前红：只 F 生效）。"""
    st, cond, ws = _ws(tmp_path)
    rel, sha = _write_manuscript(ws, role="B", ledger="B")
    loop = _loop(st, cond, ws, "B")
    _parked_timer(cond, loop, ws)
    _assert_producer_is_blocked(loop, rel=rel, sha=sha)
    close = loop._v_wait_gate_reading()
    assert close.get("checked") is True, close
    assert close.get("complete") is False, close


# ============================================================ d：负控三档
def test_d1_no_reports_dir_all_producers_may_park(tmp_path, bench):
    """d1 盘上没有 `reports/` ⇒ 三个产出者都照旧可以挂机。"""
    st, cond, ws = _ws(tmp_path)
    for role in PRODUCERS:
        loop = _loop(st, cond, ws, role)
        _parked_timer(cond, loop, ws)
        _assert_park_is_allowed(loop)


def test_d2_a_draft_is_not_a_waiting_manuscript(tmp_path, bench):
    """d2 只有草稿（没有稿头元信息、没有台账行）⇒ 三个产出者都照旧可以挂机。"""
    st, cond, ws = _ws(tmp_path)
    for role in PRODUCERS:
        _write_manuscript(ws, role=role, registered=False)
    for role in PRODUCERS:
        loop = _loop(st, cond, ws, role)
        _parked_timer(cond, loop, ws)
        _assert_park_is_allowed(loop)


def test_d3_a_signed_manuscript_is_not_waiting(tmp_path, bench):
    """d3 已登记且已签 ⇒ 三个产出者都照旧可以挂机（「未签」这一刀真的在量）。"""
    st, cond, ws = _ws(tmp_path)
    for role in PRODUCERS:
        rel, _sha = _write_manuscript(ws, role=role,
                                      ledger=role if role == "E" else None)
        issue_credential(ws, proof_text=_body_of(role), manuscript=rel,
                         artifact_path=rel)
    for role in PRODUCERS:
        loop = _loop(st, cond, ws, role)
        _parked_timer(cond, loop, ws)
        _assert_park_is_allowed(loop)


# ============================================================ e：非产出者不被误伤
def test_e_non_producer_roles_are_not_blocked_by_this_rule(tmp_path, bench):
    """e A/C/G/H/M 名下没有稿这一格 ⇒ 不因这一条被拦（负控，防误伤）。

    盘上同时放着 F/E/B 三份已登记未签稿：它们只拦自己的产出者。
    """
    st, cond, ws = _ws(tmp_path)
    for role in PRODUCERS:
        _write_manuscript(ws, role=role,
                          ledger=role if role == "E" else None)
    for role in NON_PRODUCERS:
        loop = _loop(st, cond, ws, role)
        _parked_timer(cond, loop, ws)
        _assert_park_is_allowed(loop)
        manuscripts = dict(loop._pending_work(_mailbox()).get("manuscripts") or {})
        why = str(manuscripts.get("why") or "")
        assert "不产出" in why or "不是" in why, (role, manuscripts)


# ============================================================ f：反真空
def test_f_hard_coding_the_producer_back_to_f_turns_b_and_c_red(tmp_path, bench,
                                                               monkeypatch):
    """f 把 ① 的产出者判定打回 hard-code `"F"` ⇒ b/c 必红。

    打桩只改"这份稿是谁写的"那一格（`agent_f.pending.manuscript_producer`）：登记
    与未签两刀都不动。E/B 的稿被打桩成 F 写的 ⇒ 它们的待办读数必须归零、挂机必须
    成立；而 F 的读数会同时吃掉这两份 —— 这正是"按角色字面量判"的旧形态。
    """
    st, cond, ws = _ws(tmp_path)
    rel_e, _ = _write_manuscript(ws, role="E", ledger="E")
    rel_b, _ = _write_manuscript(ws, role="B", ledger="B", mid="000002")

    from agentflow.agent_f import pending as FP

    real = FP.manuscript_producer

    def _as_f(root: Any, rel: Any, **kw: Any) -> dict[str, Any]:
        got = dict(real(root, rel, **kw))
        got.update(producer_role="F", producer_source="hard-coded:role==F")
        return got

    monkeypatch.setattr(FP, "manuscript_producer", _as_f)

    loop_f = _loop(st, cond, ws, "F")
    _parked_timer(cond, loop_f, ws)
    work_f = loop_f._pending_work(_mailbox())
    assert int((work_f.get("manuscripts") or {}).get("count") or 0) == 2, work_f

    for role, rel in (("E", rel_e), ("B", rel_b)):
        loop = _loop(st, cond, ws, role)
        _parked_timer(cond, loop, ws)
        _assert_park_is_allowed(loop)
        with pytest.raises(AssertionError):
            _assert_producer_is_blocked(loop, rel=rel, sha="")


# ============================================================ 读数的唯一扫描
def test_g_the_three_readers_share_the_one_scan(tmp_path, bench, monkeypatch):
    """g 三个读者（F 的交差 / 挂机判据 / M 的读数）读的是同一次扫描。

    把 `agent_f.pending.scan_registered` 打桩成空 ⇒ E 的挂机判据与 M 的
    `manuscript_unsigned` 必须同时归零：若哪一处自己抄了一份扫 `reports/` 的逻辑，
    打桩就影响不到它（与 79cb25a0 的 e 条同一条纪律，扩到 E/B）。
    """
    st, cond, ws = _ws(tmp_path)
    _write_manuscript(ws, role="E", ledger="E")
    loop = _loop(st, cond, ws, "E")
    _parked_timer(cond, loop, ws)
    assert int((RP.pending_reading(st).get("counts") or {})
               .get("manuscript_unsigned") or 0) == 1

    from agentflow.agent_f import pending as FP

    monkeypatch.setattr(FP, "scan_registered", lambda _root, **_kw: {
        "checked": True, "rows": [], "problems": [], "why": "打桩：扫不到登记稿"})

    work = loop._pending_work(_mailbox())
    assert int((work.get("manuscripts") or {}).get("count") or 0) == 0, work
    assert work.get("busy") is False, work
    assert int((RP.pending_reading(st).get("counts") or {})
               .get("manuscript_unsigned") or 0) == 0
