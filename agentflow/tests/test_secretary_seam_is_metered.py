# -*- coding: utf-8 -*-
"""验收②的缺陷 3：秘书那条缝没接电表（`secretary.seam_for_secretary` 造缝时不传 `meter=`）。

## 改的是什么（现场读数逐字）

`temp/_five_verify_20261105/ws02/sessions/20261105.jsonl` 里 3 条 `llm_call`
（`role=secretary:B`、`task_id=t-000001`、`usd` 合计 0.002101 美元），每条
`ledger={"charged": false, "reason": "no_meter"}`，而 `usage_ledger` 是 0 行 ——
那笔钱在 `reconcile_usage` 里既不是已归口、也不是 `unattributed`，是没有下落。

根因只有一处：`seam_for_secretary` 调 `LlmSeam.for_secretary` 时没传 `meter=`，
而它支持（`**kw` → `LlmSeam.meter`）。所以修法也只在那一处：`store` 在手上就现造
`TokenMeter(store)` 并传进去（见 `secretary.seam_for_secretary` 的 "## 账" 一节）。

## 四条判据（本文件逐条钉住）

| 判据 | 读法 |
|---|---|
| a | 召唤上下文里真调一次秘书判定 ⇒ `usage_ledger` 一行、`task_id` 是那个召唤号、`tasks.usd` 同步、`reconcile_usage` 相等 |
| b | 不在任何召唤里 ⇒ 账本行 `task_id=None`、`note` 写明 `unattributed`、`reconcile_usage.unattributed` 点名（不是 `no_meter`） |
| c | 反真空：把 `meter=` 摘掉 ⇒ 账本 0 行、`llm_call.ledger.reason == "no_meter"`（回到改前形态） |
| d | 全仓 AST 扫"造 LlmSeam"的调用点：每一处要么传了 `meter`，要么在 :data:`_EXEMPT_UNMETERED` 里逐条登记理由；`for_role_wired` 的每一处要么传 `store=`，要么在 :data:`_EXEMPT_WIRED` 里登记 |

## 为什么用替身网关而不是真网关

判据问的是"钱有没有下落"，不是"模型答得对不对"。替身网关（离线、不读 key、不碰网络）
回一份带固定 usage 的 `Reply`，于是 `usd` 是确定值、账本行可逐位核对 —— 真网关那一版
读数在 `temp/_five_verify_20261105/evidence/fix_03_secretary_meter.json`（真调 3 次，
合计约 $0.002）。本文件不花一分钱，适合进 CI。
"""
from __future__ import annotations

import ast
import json
import pathlib
from typing import Any

import pytest

from agentflow import conductor as CO
from agentflow import llmseam as LS
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import tokenmeter as TM
from agentflow.interactions import next_prefixed_id
from agentflow.store import Store

#: 判据正文：本文件里每条判定用不同的一段，避免命中 `proposition_verdicts` 的回放缓存。
FULL_A = "电表判据 a：设 G 是有限群，则 G 的阶整除其中心化子的指标。"
FULL_B = "电表判据 b：设 R 是诺特环，则 R 上的每个理想都有限生成。"
FULL_C = "电表判据 c：反真空——摘掉 meter 之后这次调用不许入账。"

#: 替身网关回的判词（`proposition_identity` 的词表内取值；判据只关心钱，不关心判词好坏）。
REPLY = json.dumps({"decision": "different", "reason": "替身网关", "canonical_name": "",
                    "same_as": "", "condition": "", "conclusion": ""},
                   ensure_ascii=False)


class _FakeGw:
    """只回 usage 的假网关（离线；形状与 `tests/test_ledger_charging.py` 的 `FakeGw` 同族）。"""

    def __init__(self, *, text: str = REPLY) -> None:
        self.text = text

    def complete(self, prompt: str, *, scope: str = "", system: Any = None,
                 max_tokens: Any = None, tools: Any = None) -> Any:
        return type("Reply", (), {
            "ok": True, "text": self.text,
            "tokens_in": 10000, "tokens_out": 1000,
            "scope": scope, "attempts": 1,
            "error_detail": "", "error_kind": "",
        })()


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path)
    st.init()
    return st


def _seed_task(st: Store) -> str:
    """造一行 running 的 `tasks`（`_sync_task_usage` 要它才回写）。"""
    with st.tx("tasks", actor="test", note="seed-task") as tx:
        tid = next_prefixed_id(tx.rows("tasks"), "task_id", "t")
        row = S.Task(task_id=tid, role="B", action="run_once", status="running",
                     started_at=S.now_iso())
        row.validate()
        tx.upsert("tasks", row.to_dict(), note="seed")
    return tid


def _calls(st: Store) -> list[dict]:
    """本工作区会话记录里的 `llm_call` 事件（逐笔，含它自己那份 `ledger` 读数）。"""
    out: list[dict] = []
    for p in sorted((pathlib.Path(st.root) / "sessions").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("kind") == "llm_call":
                out.append(ev)
    return out


def _judge(sec: Any, full: str) -> dict:
    return sec.adjudicate_proposition(
        {"statement_full": full, "label": "电表判据", "kind": "theorem"}, task_id="")


@pytest.fixture
def gateway_seen(monkeypatch: pytest.MonkeyPatch) -> dict:
    """把 `for_secretary` 的网关换成替身，`meter=` 仍由生产代码传（那一层不替换）。

    这是本文件的关键：桩打在"网关"上而不是"meter 透传"上 —— 若 `seam_for_secretary`
    又把 `meter=` 丢了，`seen` 里就没有 `meter`，a 会当场红。
    """
    orig = LS.LlmSeam.for_secretary.__func__
    seen: dict = {}

    def _fake(cls, *, owner_role: str = "", session_root: Any, gateway: Any = None,
              from_env: bool = True, settings_path: Any = None, **kw: Any) -> Any:
        seen.clear()
        seen.update(kw)
        seen["owner_role"] = owner_role
        return orig(cls, owner_role=owner_role, session_root=session_root,
                    gateway=_FakeGw(), from_env=False, price=(1.0, 2.0), **kw)

    monkeypatch.setattr(LS.LlmSeam, "for_secretary", classmethod(_fake))
    return seen


# ============================================================ a：召唤上下文 ⇒ 挂到 task
def test_a_a_judgement_inside_a_summon_lands_on_the_task_and_syncs_tasks_usd(
        tmp_path: pathlib.Path, gateway_seen: dict) -> None:
    """a：真调一次秘书判定（替身网关回 usage）⇒ 账本一行、`task_id` 对、`tasks.usd` 同步。

    改前红：`meter` 没传 ⇒ `_charge_ledger` 落 `no_meter`、账本 0 行，而这里断言的是
    "那一行在、且挂在这个召唤号上"。
    """
    st = _ws(tmp_path)
    tid = _seed_task(st)
    sec = SEC.for_role_wired("B", root=st.root, store=st)

    # 装配读数：生产代码把 TokenMeter 传给了 for_secretary（这是本判据守的那根线）。
    assert isinstance(gateway_seen.get("meter"), TM.TokenMeter), gateway_seen
    assert sec.seam is not None and sec.seam.meter is not None

    with CO.calling_as(tid, role="B"):
        got = _judge(sec, FULL_A)

    rows = [dict(r) for r in st.rows("usage_ledger")]
    assert len(rows) == 1, rows
    row = rows[0]
    assert str(row.get("task_id")) == tid, row
    assert float(row.get("usd") or 0.0) > 0, row
    assert dict(got.get("cost") or {}).get("charged") is True, got.get("cost")

    task = next(dict(r) for r in st.rows("tasks") if r.get("task_id") == tid)
    assert int(round(float(task.get("usd") or 0.0) * 1_000_000)) == int(
        round(float(row.get("usd") or 0.0) * 1_000_000)), (task, row)

    reading = TM.reconcile_usage(st)
    assert reading["equal"] is True and reading["diff_usd"] == 0.0, reading
    assert reading["unattributed"]["count"] == 0, reading
    assert reading["named_residual"] == [] and reading["dangling"] == [], reading

    calls = _calls(st)
    assert [dict(c.get("ledger") or {}).get("reason") for c in calls] == ["charged"], calls


# ============================================================ b：无台账号 ⇒ unattributed
def test_b_outside_a_summon_the_charge_is_named_unattributed(
        tmp_path: pathlib.Path, gateway_seen: dict) -> None:
    """b：不在任何召唤上下文里 ⇒ 账本行 `task_id=None`、`note` 写 `unattributed`、对账点名。

    "没有台账号"是合法读数（说得出为什么），不是 `no_meter`（没有入账）。两者在
    `reconcile_usage` 上的形态完全不同：前者进 `unattributed` 那一栏，后者根本看不见。
    """
    st = _ws(tmp_path)
    sec = SEC.for_role_wired("B", root=st.root, store=st)
    _judge(sec, FULL_B)          # 刻意不在 calling_as 里

    rows = [dict(r) for r in st.rows("usage_ledger")]
    assert len(rows) == 1, rows
    assert rows[0].get("task_id") in (None, ""), rows[0]
    assert "unattributed" in str(rows[0].get("note") or ""), rows[0]

    reading = TM.reconcile_usage(st)
    assert reading["unattributed"]["count"] == 1, reading
    assert reading["unattributed"]["usd"] > 0, reading
    assert reading["unattributed"]["usage_ids"] == [str(rows[0].get("usage_id"))], reading
    # 不是 no_meter：会话事件自己说这笔钱进了账本。
    reasons = [dict(c.get("ledger") or {}).get("reason") for c in _calls(st)]
    assert reasons == ["charged"], reasons


# ============================================================ c：反真空（摘掉 meter）
def test_c_removing_the_meter_takes_it_back_to_no_meter_and_zero_ledger_rows(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：把 `meter=` 摘掉 ⇒ 账本 0 行、`llm_call.ledger.reason == "no_meter"`。

    没有这一条，a 证明的只是"今天恰好记上了"，不证明"记上是 meter 这根线干的"。
    """
    orig = LS.LlmSeam.for_secretary.__func__

    def _fake(cls, *, owner_role: str = "", session_root: Any, gateway: Any = None,
              from_env: bool = True, settings_path: Any = None, **kw: Any) -> Any:
        kw.pop("meter", None)     # 等价于改前那一行：造缝时不传 meter
        return orig(cls, owner_role=owner_role, session_root=session_root,
                    gateway=_FakeGw(), from_env=False, price=(1.0, 2.0), **kw)

    monkeypatch.setattr(LS.LlmSeam, "for_secretary", classmethod(_fake))
    st = _ws(tmp_path)
    tid = _seed_task(st)
    sec = SEC.for_role_wired("B", root=st.root, store=st)
    with CO.calling_as(tid, role="B"):
        _judge(sec, FULL_C)

    assert sec.seam is not None and sec.seam.meter is None, sec.seam
    assert st.rows("usage_ledger") == [], st.rows("usage_ledger")
    reasons = [dict(c.get("ledger") or {}).get("reason") for c in _calls(st)]
    assert reasons == ["no_meter"], reasons


# ============================================================ d：全仓扫描（无 meter 的造缝点）
#: `LlmSeam` 造缝点里按设计不接电表的那些：逐条登记理由，新增一处不登记就红。
#: 键是 `(文件, 最近的函数/类名)`，不是行号 —— 行号会漂，函数名不会（本仓的同一口径）。
_EXEMPT_UNMETERED: dict[tuple[str, str], str] = {
    ("src/agentflow/llmseam.py", "selftest"):
        "模块自检：网关是 None/Boom/Garbage/Good 的离线替身，不发真请求、不花钱",
    ("src/agentflow/judges.py", "selftest"):
        "判据自检：Fake 网关 + price=(0,0)，离线、零花销",
    ("src/agentflow/deliver.py", "selftest"):
        "交付门自检：_Fake 网关 + price=(0,0)，离线、零花销",
    ("src/agentflow/agent_loop.py", "run_role"):
        "条件性缺口（已登记，未修）：调用方不给 seam= 时 run_role 现造的本体缝没接 meter；"
        "生产入口 cli.run-agent 会传 cli._seam 造的带电表缝，所以只在直接调 run_role 的路径上漏",
    ("src/agentflow/autonomy.py", "run_autonomous"):
        "条件性缺口（已登记，未修）：只给 gateway= 而不给 seam= 时现造的共用缝没接 meter；"
        "生产入口 cli 会传带电表的 seam，所以只在直接调 run_autonomous(gateway=…) 的路径上漏",
}

#: `for_role_wired(...)` 是"造秘书"的那一支：`meter` 经它的 `store=` 进来。
_EXEMPT_WIRED: dict[tuple[str, str], str] = {}


def _scan_seam_sites() -> list[dict]:
    """扫 `src/agentflow`：哪些地方造 `LlmSeam`、哪些地方调 `for_role_wired`。

    刻意用 AST 而不是正则：正则会把 `LlmSeam.for_role` 与 `registry.for_role` 混在一起，
    "扫不到"于是被读成"没问题"（三态纪律：没查成不许折成查过了没问题）。
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
    sites: list[dict] = []

    def _owner(node: ast.AST, parents: list[ast.AST]) -> str:
        for p in reversed(parents):
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return str(p.name)
        return "<module>"

    for p in sorted(root.rglob("*.py")):
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
        lines = src.splitlines()
        rel = p.relative_to(root.parent.parent).as_posix()

        def _walk(node: ast.AST, parents: list[ast.AST]) -> None:
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, ast.Call):
                    fn = ch.func
                    kind = ""
                    if isinstance(fn, ast.Name) and fn.id == "LlmSeam":
                        kind = "LlmSeam"
                    elif (isinstance(fn, ast.Attribute)
                          and fn.attr in ("for_role", "for_secretary")
                          and isinstance(fn.value, ast.Name)
                          and fn.value.id == "LlmSeam"):
                        kind = f"LlmSeam.{fn.attr}"
                    elif isinstance(fn, ast.Name) and fn.id == "for_role_wired":
                        kind = "for_role_wired"
                    if kind:
                        kws = {k.arg for k in ch.keywords if k.arg}
                        sites.append({
                            "file": rel, "line": ch.lineno, "kind": kind,
                            "owner": _owner(ch, parents),
                            "has_meter": "meter" in kws,
                            "has_store": "store" in kws,
                            "snippet": lines[ch.lineno - 1].strip()[:120],
                        })
                _walk(ch, parents + [ch])

        _walk(tree, [])
    return sites


def test_d_every_llmseam_site_is_either_metered_or_registered_with_a_reason() -> None:
    """d：全仓每一处造缝点 —— 传了 `meter`，或在豁免表里逐条写明理由。

    这条判据的形状：不接电表是允许的，但必须是登记过的（离线替身 / 条件性缺口）。
    新增一处不传 `meter` 的造缝点而不登记 ⇒ 本测试红 —— 那正是缺陷 3 复发的入口。
    """
    sites = _scan_seam_sites()
    seam_sites = [s for s in sites if s["kind"] != "for_role_wired"]
    wired_sites = [s for s in sites if s["kind"] == "for_role_wired"]
    # 反真空：扫不到任何一处 ⇒ "没有未接电表的点"这个结论不成立（没查成 ≠ 干净）。
    assert seam_sites and wired_sites, (seam_sites, wired_sites)

    unmetered: list[str] = []
    for s in seam_sites:
        if s["has_meter"]:
            continue
        key = (s["file"], s["owner"])
        if key in _EXEMPT_UNMETERED:
            continue
        unmetered.append(f"{s['file']}:{s['line']} {s['kind']} in {s['owner']} —— {s['snippet']}")
    assert not unmetered, (
        "这些造缝点没传 `meter` 也没登记理由（钱会落 no_meter）：\n" + "\n".join(unmetered))

    # 秘书那一条缝必须在"传了 meter"的名单里 —— 它正是缺陷 3 的落点。
    assert any(s["file"] == "src/agentflow/secretary.py" and s["has_meter"]
               for s in seam_sites), [s for s in seam_sites
                                      if s["file"] == "src/agentflow/secretary.py"]

    unwired: list[str] = []
    for s in wired_sites:
        if s["has_store"]:
            continue
        key = (s["file"], s["owner"])
        if key in _EXEMPT_WIRED:
            continue
        unwired.append(f"{s['file']}:{s['line']} —— {s['snippet']}")
    assert not unwired, (
        "这些 `for_role_wired(...)` 没传 `store=`（meter 接不上）：\n" + "\n".join(unwired))
